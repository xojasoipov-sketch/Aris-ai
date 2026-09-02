"""Uzoq muddatli xotiraning javobga ulanishi (Z45).

NEGA BU TESTLAR BOR.

Ega o'zi haqidagi profilni yubordi va u `memory_entries` jadvaliga
muvaffaqiyatli yozildi. Lekin jonli tekshiruvda ma'lum bo'ldiki, javob
yozuvchi zanjir xotirani UMUMAN o'qimasdi:

    grep -rl "PgMemoryStore\\|MemoryQuery" src/zet/core/ src/zet/agents/
    → hech nima

Ya'ni profil saqlanardi-yu, hech qachon ishlatilmasdi — bu ilgari
`conversation`/`message` jadvallarida ham uchragan naqsh: "yoziladi,
lekin hech kim o'qimaydi". Quyidagi testlar shu zanjirni qulflaydi:

    savol → recall(savol) → prompt ichida "ega haqida eslaganlaring"
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from zet.core.executor import Executor
from zet.domain.enums import PermissionLevel, StepStatus
from zet.domain.plan import Plan, PlanStep
from zet.prompts.answer import build_answer_prompt
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


@dataclass
class _Response:
    text: str


@dataclass
class _Result:
    response: _Response
    cost_usd: float = 0.0


class _FakeRouter:
    """`ModelRouter` o'rniga — yuborilgan xabarlarni saqlab qoladi."""

    def __init__(self, reply: str = "javob") -> None:
        self.reply = reply
        self.messages: list[Any] = []
        self.system: str | None = None

    async def complete(self, **kwargs: Any) -> _Result:
        self.messages = list(kwargs["messages"])
        self.system = kwargs.get("system")
        return _Result(response=_Response(self.reply))

    @property
    def last_user_content(self) -> str:
        return str(self.messages[-1].content)


def _step(position: int = 1) -> PlanStep:
    return PlanStep(
        position=position,
        description=f"Qadam {position}",
        tool_name=None,
        permission_required=PermissionLevel.READ,
    )


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


class TestRecalledMemoryReachesThePrompt:
    """Xotira yozuvlari LLM'ga yetib borishi kerak."""

    def test_prompt_contains_recalled_entries(self) -> None:
        prompt = build_answer_prompt(
            "Men qaysi loyihalar ustida ishlayapman?",
            step_description="Javob ber",
            recalled=["Active Projects\n\nZET, trading bot"],
        )

        assert "ZET, trading bot" in prompt
        assert "uzoq muddatli xotira" in prompt

    def test_prompt_has_no_memory_block_when_nothing_recalled(self) -> None:
        prompt = build_answer_prompt("Salom", step_description="Javob ber", recalled=[])

        assert "uzoq muddatli xotira" not in prompt

    def test_blank_entries_are_dropped(self) -> None:
        """Bo'sh yozuv blok ochib, LLM'ni chalg'itmasligi kerak."""
        prompt = build_answer_prompt(
            "Salom", step_description="Javob ber", recalled=["", "   ", "\n"]
        )

        assert "uzoq muddatli xotira" not in prompt


class TestExecutorUsesRecall:
    """Fikrlash qadami xotirani chaqiradi va natijani promptga qo'shadi."""

    async def test_recall_is_called_with_the_owner_question(
        self, tool_registry: ToolRegistry
    ) -> None:
        asked: list[str] = []

        async def recall(query: str) -> list[str]:
            asked.append(query)
            return ["Ega ismi Umid"]

        router = _FakeRouter()
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            router=router,  # type: ignore[arg-type]
            command_text="Meni tanaysanmi?",
            recall=recall,
        )

        ctx = await executor.execute_plan(Plan(summary="reja", steps=[_step()]))

        assert asked == ["Meni tanaysanmi?"]
        assert "Ega ismi Umid" in router.last_user_content
        assert ctx.results[1].output == "javob"

    async def test_without_recall_the_prompt_has_no_memory_block(
        self, tool_registry: ToolRegistry
    ) -> None:
        router = _FakeRouter()
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            router=router,  # type: ignore[arg-type]
            command_text="Salom",
        )

        await executor.execute_plan(Plan(summary="reja", steps=[_step()]))

        assert "uzoq muddatli xotira" not in router.last_user_content

    async def test_recall_failure_does_not_break_the_answer(
        self, tool_registry: ToolRegistry
    ) -> None:
        """Xotira (DB/embedding) yiqilsa javob baribir yozilishi kerak."""

        async def recall(query: str) -> list[str]:
            raise RuntimeError("embedding provider down")

        router = _FakeRouter()
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            router=router,  # type: ignore[arg-type]
            command_text="Salom",
            recall=recall,
        )

        ctx = await executor.execute_plan(Plan(summary="reja", steps=[_step()]))

        assert ctx.results[1].status == StepStatus.DONE
        assert ctx.results[1].output == "javob"

    async def test_recall_is_skipped_when_there_is_no_command_text(
        self, tool_registry: ToolRegistry
    ) -> None:
        """Bo'sh so'rov bilan qidiruv qilish — behuda embedding xarajati."""
        called = False

        async def recall(query: str) -> list[str]:
            nonlocal called
            called = True
            return []

        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            router=_FakeRouter(),  # type: ignore[arg-type]
            command_text="",
            recall=recall,
        )

        await executor.execute_plan(Plan(summary="reja", steps=[_step()]))

        assert called is False


class TestRecallFactory:
    """`deps._build_recall` — xotira do'konidan matn ro'yxatiga."""

    async def test_returns_entry_contents(self) -> None:
        from zet.api.deps import RECALL_LIMIT, RECALL_MIN_SIMILARITY, _build_recall

        captured: dict[str, Any] = {}

        class _Entry:
            content = "Ega Toshkentda yashaydi"

        class _Hit:
            entry = _Entry()

        class _Memory:
            async def search(self, query: Any) -> list[Any]:
                captured["query"] = query
                return [_Hit()]

        recall = _build_recall(_Memory())  # type: ignore[arg-type]
        result = await recall("Ega qayerda yashaydi?")

        assert result == ["Ega Toshkentda yashaydi"]
        assert captured["query"].text == "Ega qayerda yashaydi?"
        assert captured["query"].limit == RECALL_LIMIT
        assert captured["query"].min_similarity == RECALL_MIN_SIMILARITY

    def test_threshold_is_not_zero(self) -> None:
        """0 chegara = har savolga butun profil ilashadi (shovqin)."""
        from zet.api.deps import RECALL_MIN_SIMILARITY

        assert RECALL_MIN_SIMILARITY > 0.0
