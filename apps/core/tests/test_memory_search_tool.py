"""`memory.search` tooli va javob qadamining himoyasi (Z45.2).

NEGA BU TESTLAR BOR.

Jonli tekshiruvda ega "Men kimman?" deb so'radi. Profil xotirada bor
edi, lekin Planner xotira borligini BILMASDI — u faqat tool ro'yxatini
ko'radi. Natijada reja shunday tuzildi:

    0. note.list
    1. note.read("user_profile")   ← o'ylab topilgan fayl
    2. javob yozish (depends_on: [0, 1])

1-qadam uch marta yiqildi, 2-qadam esa "dependency_not_ready" bo'lib
umuman ishga tushmadi. Run FAILED, ega hech qanday javob ko'rmadi.

Ikki tuzatish qulflanadi:
  1. `memory.search` — Planner uchun xotiraga haqiqiy yo'l.
  2. Fikrlash qadami dependency yiqilsa ham ishlaydi — javob yoziladi,
     yiqilgan qadam esa kontekstga xato sifatida kiradi.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from zet.core.executor import Executor
from zet.domain.enums import PermissionLevel, StepStatus, TrustLevel
from zet.domain.memory import MemoryLayer
from zet.domain.plan import Plan, PlanStep
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.base import ToolError
from zet.tools.builtin import build_default_registry
from zet.tools.builtin.memory_search import MAX_LIMIT, MemorySearchTool
from zet.tools.registry import ToolRegistry


@dataclass
class _Entry:
    content: str
    summary: str | None = None
    layer: MemoryLayer = MemoryLayer.PERSONAL


@dataclass
class _Hit:
    entry: _Entry
    similarity: float


@dataclass
class _Response:
    text: str


@dataclass
class _Result:
    response: _Response
    cost_usd: float = 0.0


class _FakeRouter:
    def __init__(self, reply: str = "javob") -> None:
        self.reply = reply
        self.messages: list[Any] = []

    async def complete(self, **kwargs: Any) -> _Result:
        self.messages = list(kwargs["messages"])
        return _Result(response=_Response(self.reply))

    @property
    def last_user_content(self) -> str:
        return str(self.messages[-1].content)


class TestMemorySearchTool:
    async def test_returns_entries_with_similarity(self) -> None:
        async def search(query: str, limit: int, min_similarity: float) -> list[Any]:
            return [_Hit(_Entry("Ega Toshkentda yashaydi", "Identity"), 0.4212)]

        tool = MemorySearchTool(search_fn=search)
        result = await tool._execute({"query": "ega qayerda yashaydi"})

        assert result["total"] == 1
        entry = result["entries"][0]
        assert entry["content"] == "Ega Toshkentda yashaydi"
        assert entry["summary"] == "Identity"
        assert entry["layer"] == "personal"
        assert entry["similarity"] == 0.421

    async def test_limit_is_clamped(self) -> None:
        seen: dict[str, int] = {}

        async def search(query: str, limit: int, min_similarity: float) -> list[Any]:
            seen["limit"] = limit
            return []

        tool = MemorySearchTool(search_fn=search)

        await tool._execute({"query": "x", "limit": 999})
        assert seen["limit"] == MAX_LIMIT

        await tool._execute({"query": "x", "limit": 0})
        assert seen["limit"] == 1

    async def test_without_backend_it_fails_loudly(self) -> None:
        """Jim bo'sh ro'yxat "xotirada yo'q" bilan adashtirardi."""
        tool = MemorySearchTool()

        with pytest.raises(ToolError, match="ulanmagan"):
            await tool._execute({"query": "ega kim"})

    async def test_empty_query_is_rejected(self) -> None:
        async def search(query: str, limit: int, min_similarity: float) -> list[Any]:
            raise AssertionError("bo'sh so'rov bilan chaqirilmasligi kerak")

        tool = MemorySearchTool(search_fn=search)

        with pytest.raises(ToolError):
            await tool._execute({"query": "   "})

    def test_permission_is_read_and_trust_is_system(self) -> None:
        """Mazmun ega o'zi yozgan — tashqi manba emas."""
        tool = MemorySearchTool()

        assert tool.permission_level is PermissionLevel.READ
        assert tool.output_trust_level is TrustLevel.SYSTEM
        assert tool.idempotent is True

    def test_registered_in_the_default_registry(self, tmp_path: Path) -> None:
        """Planner uni ko'rmasa, ega profilini eslatma fayllaridan qidiradi."""
        registry = build_default_registry(notes_dir=tmp_path)

        assert registry.has("memory.search")


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


class TestThinkingStepSurvivesFailedDependencies:
    """Yiqilgan tool javobni butunlay o'chirib yubormasligi kerak."""

    def _plan(self) -> Plan:
        return Plan(
            summary="reja",
            steps=[
                PlanStep(
                    position=0,
                    description="Yo'q eslatmani o'qish",
                    tool_name="note.read",
                    tool_params={"title": "user_profile"},
                    permission_required=PermissionLevel.READ,
                ),
                PlanStep(
                    position=1,
                    description="Javob yozish",
                    tool_name=None,
                    permission_required=PermissionLevel.READ,
                    depends_on=[0],
                ),
            ],
        )

    async def test_answer_is_still_written(self, tool_registry: ToolRegistry) -> None:
        router = _FakeRouter("Profilingni topa olmadim.")
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            router=router,  # type: ignore[arg-type]
            command_text="Men kimman?",
        )

        ctx = await executor.execute_plan(self._plan())

        assert ctx.results[0].status == StepStatus.FAILED
        assert ctx.results[1].status == StepStatus.DONE
        assert ctx.results[1].output == "Profilingni topa olmadim."

    async def test_failure_reaches_the_prompt(self, tool_registry: ToolRegistry) -> None:
        """LLM nima yiqilganini bilsin — aks holda javob yolg'on chiqadi."""
        router = _FakeRouter()
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
            router=router,  # type: ignore[arg-type]
            command_text="Men kimman?",
        )

        await executor.execute_plan(self._plan())

        assert "0-qadam bajarilmadi" in router.last_user_content

    async def test_tool_steps_still_wait_for_dependencies(
        self, tool_registry: ToolRegistry
    ) -> None:
        """Istisno FAQAT fikrlash qadamiga tegishli."""
        plan = Plan(
            summary="reja",
            steps=[
                PlanStep(
                    position=0,
                    description="Yo'q eslatma",
                    tool_name="note.read",
                    tool_params={"title": "yoq"},
                    permission_required=PermissionLevel.READ,
                ),
                PlanStep(
                    position=1,
                    description="Eslatma yozish",
                    tool_name="note.write",
                    tool_params={"title": "x", "content": "y"},
                    permission_required=PermissionLevel.WRITE,
                    depends_on=[0],
                ),
            ],
        )
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
        )

        ctx = await executor.execute_plan(plan)

        assert ctx.results[1].status == StepStatus.SKIPPED
