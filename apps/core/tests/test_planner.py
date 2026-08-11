"""Z1.8 — Planner testlari.

FakeProvider bilan deterministik testlar — LLM'ga chiqilmaydi.

Tekshiriladi:
    - Oddiy intent'dan to'g'ri reja yaratiladi
    - DAG validatsiyasi (sikl → xato)
    - Mavjud bo'lmagan tool → repair urinishi
    - max_steps oshsa → xato
    - permission_required to'g'ri belgilanadi
    - LLM tool chaqirmasa → PlannerError
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.core.planner import Planner, PlannerError
from zet.domain.command import Intent
from zet.domain.enums import PermissionLevel, TaskClass
from zet.llm.base import ToolUse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter

_PROVIDER_NAME = "ollama"


def _fixed_now() -> datetime:
    return datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)


def _fake(**kwargs: object) -> FakeProvider:
    return FakeProvider(name=_PROVIDER_NAME, **kwargs)  # type: ignore[arg-type]


def _make_planner(
    session: AsyncSession,
    provider: FakeProvider,
    max_steps: int = 20,
) -> Planner:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    router = ModelRouter(
        providers={provider.name: provider},
        session=session,
        settings=settings,
        now_fn=_fixed_now,
    )
    return Planner(router, max_steps=max_steps)


def _plan_tool_use(
    summary: str = "Test reja",
    steps: list[dict] | None = None,
) -> ToolUse:
    """create_plan tool chaqiruvini yaratish."""
    if steps is None:
        steps = [
            {
                "position": 0,
                "description": "Vaqtni ol",
                "tool_name": "time.now",
                "permission_required": "read",
                "trust_context": "owner",
                "expected_outcome": "Hozirgi vaqt olinadi",
                "depends_on": [],
            },
            {
                "position": 1,
                "description": "Eslatma yoz",
                "tool_name": "note.write",
                "permission_required": "write",
                "trust_context": "owner",
                "expected_outcome": "Eslatma yaratiladi",
                "depends_on": [0],
            },
        ]
    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="create_plan",
        arguments={"summary": summary, "steps": steps},
    )


def _simple_intent(text: str = "Eslatma yoz") -> Intent:
    return Intent(
        action="note.write",
        objects=["eslatma"],
        task_class=TaskClass.NORMAL,
        requires_tools=["note.write"],
        original_text=text,
    )


class TestPlanner:
    async def test_simple_plan(self, session: AsyncSession) -> None:
        """Oddiy intent'dan ikki qadamli reja yaratiladi."""
        provider = _fake(scripted=[fake_response(text="", tool_uses=(_plan_tool_use(),))])
        planner = _make_planner(session, provider)
        plan = await planner.plan(
            _simple_intent(),
            available_tools=["time.now", "note.write"],
        )

        assert plan.summary == "Test reja"
        assert len(plan.steps) == 2
        assert plan.steps[0].tool_name == "time.now"
        assert plan.steps[1].tool_name == "note.write"
        assert plan.steps[1].depends_on == [0]

    async def test_permission_levels(self, session: AsyncSession) -> None:
        """Qadamlardagi permission to'g'ri saqlanadi."""
        steps = [
            {
                "position": 0,
                "description": "O'qish",
                "tool_name": "file.read",
                "permission_required": "read",
                "depends_on": [],
            },
            {
                "position": 1,
                "description": "Yozish",
                "tool_name": "file.write",
                "permission_required": "write",
                "depends_on": [0],
            },
            {
                "position": 2,
                "description": "Bajarish",
                "tool_name": "shell.exec",
                "permission_required": "execute",
                "depends_on": [1],
            },
        ]
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(_plan_tool_use("Fayl operatsiyalari", steps),),
                )
            ]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(
            _simple_intent(),
            available_tools=["file.read", "file.write", "shell.exec"],
        )

        assert plan.steps[0].permission_required == PermissionLevel.READ
        assert plan.steps[1].permission_required == PermissionLevel.WRITE
        assert plan.steps[2].permission_required == PermissionLevel.EXECUTE
        assert plan.needs_approval is True
        assert plan.max_permission == PermissionLevel.EXECUTE

    async def test_invalid_tool_triggers_repair(self, session: AsyncSession) -> None:
        """Mavjud bo'lmagan tool — birinchi urinishda xato, repair'da tuzatiladi."""
        bad_steps = [
            {
                "position": 0,
                "description": "Mavjud bo'lmagan tool",
                "tool_name": "imaginary.tool",
                "permission_required": "read",
                "depends_on": [],
            },
        ]
        good_steps = [
            {
                "position": 0,
                "description": "Vaqtni ol",
                "tool_name": "time.now",
                "permission_required": "read",
                "depends_on": [],
            },
        ]
        provider = _fake(
            scripted=[
                fake_response(text="", tool_uses=(_plan_tool_use("Xato", bad_steps),)),
                fake_response(text="", tool_uses=(_plan_tool_use("Tuzatilgan", good_steps),)),
            ]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(
            _simple_intent(),
            available_tools=["time.now", "note.write"],
        )

        assert plan.steps[0].tool_name == "time.now"
        assert len(provider.calls) == 2

    async def test_invalid_tool_no_repair_raises(self, session: AsyncSession) -> None:
        """Ikki marta ham noto'g'ri tool bo'lsa — PlannerError."""
        bad_steps = [
            {
                "position": 0,
                "description": "Noto'g'ri",
                "tool_name": "fake.tool",
                "permission_required": "read",
                "depends_on": [],
            },
        ]
        provider = _fake(
            scripted=[
                fake_response(text="", tool_uses=(_plan_tool_use("Xato", bad_steps),)),
                fake_response(text="", tool_uses=(_plan_tool_use("Xato2", bad_steps),)),
            ]
        )
        planner = _make_planner(session, provider)

        with pytest.raises(PlannerError, match="tool mavjud emas"):
            await planner.plan(
                _simple_intent(),
                available_tools=["time.now"],
            )

    async def test_max_steps_exceeded(self, session: AsyncSession) -> None:
        """max_steps oshsa PlannerError."""
        many_steps = [
            {
                "position": i,
                "description": f"Qadam {i}",
                "permission_required": "read",
                "depends_on": [i - 1] if i > 0 else [],
            }
            for i in range(5)
        ]
        provider = _fake(
            scripted=[
                fake_response(text="", tool_uses=(_plan_tool_use("Ko'p", many_steps),)),
                fake_response(text="", tool_uses=(_plan_tool_use("Ko'p2", many_steps),)),
            ]
        )
        planner = _make_planner(session, provider, max_steps=3)

        with pytest.raises(PlannerError, match="oshib ketdi"):
            await planner.plan(_simple_intent())

    async def test_no_tool_use_raises(self, session: AsyncSession) -> None:
        """LLM tool chaqirmasa — PlannerError."""
        provider = _fake(
            scripted=[
                fake_response(text="Reja tuzaman"),
                fake_response(text="Bajaraman!"),
            ]
        )
        planner = _make_planner(session, provider)

        with pytest.raises(PlannerError, match="create_plan"):
            await planner.plan(_simple_intent())

    async def test_dag_cycle_triggers_repair(self, session: AsyncSession) -> None:
        """DAG'da sikl bo'lsa — repair urinishi."""
        cyclic_steps = [
            {
                "position": 0,
                "description": "A",
                "permission_required": "read",
                "depends_on": [1],
            },
            {
                "position": 1,
                "description": "B",
                "permission_required": "read",
                "depends_on": [0],
            },
        ]
        good_steps = [
            {
                "position": 0,
                "description": "A",
                "permission_required": "read",
                "depends_on": [],
            },
            {
                "position": 1,
                "description": "B",
                "permission_required": "read",
                "depends_on": [0],
            },
        ]
        provider = _fake(
            scripted=[
                fake_response(text="", tool_uses=(_plan_tool_use("Siklli", cyclic_steps),)),
                fake_response(text="", tool_uses=(_plan_tool_use("Tuzatilgan", good_steps),)),
            ]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(_simple_intent())

        assert len(plan.steps) == 2
        assert plan.steps[1].depends_on == [0]

    async def test_no_available_tools_allows_null(self, session: AsyncSession) -> None:
        """Tool ro'yxati berilmasa, tool_name=null bo'lgan qadamlar qabul qilinadi."""
        steps = [
            {
                "position": 0,
                "description": "Fikrla",
                "tool_name": None,
                "permission_required": "read",
                "depends_on": [],
            },
        ]
        provider = _fake(
            scripted=[fake_response(text="", tool_uses=(_plan_tool_use("Oddiy", steps),))]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(_simple_intent())

        assert plan.steps[0].tool_name is None

    async def test_task_class_override(self, session: AsyncSession) -> None:
        """task_class parametri intent'dagi qiymatni override qiladi.

        COMPLEX → anthropic:sonnet (catalog), shuning uchun provider="anthropic".
        """
        provider = FakeProvider(
            name="anthropic",
            scripted=[fake_response(text="", tool_uses=(_plan_tool_use(),))],
        )
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        router = ModelRouter(
            providers={"anthropic": provider},
            session=session,
            settings=settings,
            now_fn=_fixed_now,
        )
        planner = Planner(router)
        plan = await planner.plan(
            _simple_intent(),
            available_tools=["time.now", "note.write"],
            task_class=TaskClass.COMPLEX,
        )

        # Reja yaratildi — demak COMPLEX marshrutlanish muvaffaqiyatli
        assert len(plan.steps) == 2

    async def test_user_prompt_contains_intent_info(self, session: AsyncSession) -> None:
        """LLM ga yuborilgan promptda intent ma'lumotlari bor."""
        provider = _fake(scripted=[fake_response(text="", tool_uses=(_plan_tool_use(),))])
        planner = _make_planner(session, provider)
        intent = Intent(
            action="reminder.create",
            objects=["uchrashuv", "10:00"],
            constraints=["o'zbek tilida"],
            requires_tools=["time.now", "note.write"],
            original_text="Ertaga 10:00 uchrashuv haqida eslatma yoz",
        )
        await planner.plan(intent, available_tools=["time.now", "note.write"])

        call = provider.calls[0]
        messages = call.get("messages", [])
        assert len(messages) >= 1  # type: ignore[arg-type]
        user_msg = messages[0]  # type: ignore[index]
        assert hasattr(user_msg, "content")
        assert "reminder.create" in user_msg.content
        assert "uchrashuv" in user_msg.content

    async def test_raw_llm_output_preserved(self, session: AsyncSession) -> None:
        """LLM ning xom javobi plan.raw_llm_output da saqlanadi."""
        provider = _fake(scripted=[fake_response(text="", tool_uses=(_plan_tool_use(),))])
        planner = _make_planner(session, provider)
        plan = await planner.plan(
            _simple_intent(),
            available_tools=["time.now", "note.write"],
        )

        assert plan.raw_llm_output.get("summary") == "Test reja"
        assert isinstance(plan.raw_llm_output.get("steps"), list)

    async def test_invalid_permission_defaults_to_read(self, session: AsyncSession) -> None:
        """Noto'g'ri permission_required → default READ."""
        steps = [
            {
                "position": 0,
                "description": "Test",
                "permission_required": "invalid_perm",
                "depends_on": [],
            },
        ]
        provider = _fake(
            scripted=[fake_response(text="", tool_uses=(_plan_tool_use("Test", steps),))]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(_simple_intent())

        assert plan.steps[0].permission_required == PermissionLevel.READ

    async def test_without_available_tools_any_tool_accepted(self, session: AsyncSession) -> None:
        """available_tools berilmasa, har qanday tool_name qabul qilinadi."""
        steps = [
            {
                "position": 0,
                "description": "Any tool",
                "tool_name": "some.random.tool",
                "permission_required": "read",
                "depends_on": [],
            },
        ]
        provider = _fake(
            scripted=[fake_response(text="", tool_uses=(_plan_tool_use("Test", steps),))]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(_simple_intent())

        assert plan.steps[0].tool_name == "some.random.tool"

    async def test_diamond_dag_plan(self, session: AsyncSession) -> None:
        """Olmossimon DAG: 0 → (1, 2) → 3 to'g'ri qabul qilinadi."""
        steps = [
            {"position": 0, "description": "A", "permission_required": "read", "depends_on": []},
            {"position": 1, "description": "B", "permission_required": "read", "depends_on": [0]},
            {"position": 2, "description": "C", "permission_required": "read", "depends_on": [0]},
            {
                "position": 3,
                "description": "D",
                "permission_required": "write",
                "depends_on": [1, 2],
            },
        ]
        provider = _fake(
            scripted=[fake_response(text="", tool_uses=(_plan_tool_use("Olmos", steps),))]
        )
        planner = _make_planner(session, provider)
        plan = await planner.plan(_simple_intent())

        assert len(plan.steps) == 4
        assert plan.steps[3].depends_on == [1, 2]
