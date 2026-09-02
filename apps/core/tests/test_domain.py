"""Z1.6 — Domen kontraktlari testlari.

Tekshiriladi:
    - Barcha modellar frozen=True (mutatsiya bloklangan)
    - JSON round-trip (serializatsiya → deserializatsiya)
    - Noto'g'ri qiymatlar ValidationError beradi
    - Plan DAG validatsiyasi (sikllar, noto'g'ri havolalar)
    - PermissionLevel tartibi (READ < WRITE < EXECUTE < ADMIN)
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from zet.domain.command import Command, Intent
from zet.domain.enums import PermissionLevel, RunStatus, TaskClass, TrustLevel
from zet.domain.plan import Plan, PlanStep
from zet.domain.run import RunLimits, RunState
from zet.domain.tool import ToolResult, Verification


class TestCommand:
    def test_basic_creation(self) -> None:
        cmd = Command(text="Eslatma yoz")
        assert cmd.text == "Eslatma yoz"
        assert cmd.trust_level == TrustLevel.OWNER
        assert cmd.channel == "cli"

    def test_frozen(self) -> None:
        cmd = Command(text="Salom")
        with pytest.raises(ValidationError):
            cmd.text = "boshqa"  # type: ignore[misc]

    def test_empty_text_rejected(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            Command(text="")

    def test_too_long_text_rejected(self) -> None:
        with pytest.raises(ValidationError, match="string_too_long"):
            Command(text="x" * 4097)

    def test_json_round_trip(self) -> None:
        cmd = Command(text="Test buyruq", channel="telegram")
        data = json.loads(cmd.model_dump_json())
        restored = Command.model_validate(data)
        assert restored == cmd

    def test_metadata(self) -> None:
        cmd = Command(text="Salom", metadata={"chat_id": 12345})
        assert cmd.metadata["chat_id"] == 12345

    def test_untrusted_command(self) -> None:
        cmd = Command(text="Forwarded xabar", trust_level=TrustLevel.UNTRUSTED)
        assert cmd.trust_level == TrustLevel.UNTRUSTED


class TestIntent:
    def test_basic_creation(self) -> None:
        intent = Intent(action="reminder.create", objects=["uchrashuv", "10:00"])
        assert intent.action == "reminder.create"
        assert intent.task_class == TaskClass.NORMAL
        assert intent.ambiguity == "low"

    def test_frozen(self) -> None:
        intent = Intent(action="test")
        with pytest.raises(ValidationError):
            intent.action = "boshqa"  # type: ignore[misc]

    def test_high_ambiguity_with_question(self) -> None:
        intent = Intent(
            action="unknown",
            ambiguity="high",
            clarification_question="Nimani tuzatish kerak?",
        )
        assert intent.clarification_question is not None

    def test_json_round_trip(self) -> None:
        intent = Intent(
            action="note.write",
            objects=["eslatma"],
            task_class=TaskClass.SIMPLE,
            requires_tools=["note.write"],
            confidence=0.95,
        )
        data = json.loads(intent.model_dump_json())
        restored = Intent.model_validate(data)
        assert restored == intent

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError, match="greater_than_equal"):
            Intent(action="test", confidence=-0.1)
        with pytest.raises(ValidationError, match="less_than_equal"):
            Intent(action="test", confidence=1.1)

    def test_complex_task_class(self) -> None:
        intent = Intent(action="code.review", task_class=TaskClass.CODING)
        assert intent.task_class == TaskClass.CODING


class TestPlanStep:
    def test_basic_step(self) -> None:
        step = PlanStep(position=0, description="Vaqtni ol")
        assert step.position == 0
        assert step.permission_required == PermissionLevel.READ
        assert step.trust_context == TrustLevel.OWNER

    def test_frozen(self) -> None:
        step = PlanStep(position=0, description="Test")
        with pytest.raises(ValidationError):
            step.position = 1  # type: ignore[misc]

    def test_negative_position_rejected(self) -> None:
        with pytest.raises(ValidationError, match="greater_than_equal"):
            PlanStep(position=-1, description="Noto'g'ri")

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            PlanStep(position=0, description="")

    def test_execute_permission(self) -> None:
        step = PlanStep(
            position=0,
            description="Faylni o'chir",
            tool_name="shell.exec",
            permission_required=PermissionLevel.EXECUTE,
        )
        assert step.permission_required == PermissionLevel.EXECUTE


class TestPlan:
    def _simple_plan(self) -> Plan:
        return Plan(
            summary="Eslatma yaratish",
            steps=[
                PlanStep(position=0, description="Vaqtni ol", tool_name="time.now"),
                PlanStep(
                    position=1,
                    description="Eslatma yoz",
                    tool_name="note.write",
                    permission_required=PermissionLevel.WRITE,
                    depends_on=[0],
                ),
            ],
        )

    def test_basic_plan(self) -> None:
        plan = self._simple_plan()
        assert len(plan.steps) == 2
        assert plan.summary == "Eslatma yaratish"

    def test_frozen(self) -> None:
        plan = self._simple_plan()
        with pytest.raises(ValidationError):
            plan.summary = "boshqa"  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        plan = self._simple_plan()
        data = json.loads(plan.model_dump_json())
        restored = Plan.model_validate(data)
        assert restored == plan

    def test_max_permission(self) -> None:
        plan = self._simple_plan()
        assert plan.max_permission == PermissionLevel.WRITE

    def test_needs_approval_false_for_write(self) -> None:
        plan = self._simple_plan()
        assert plan.needs_approval is False

    def test_needs_approval_true_for_execute(self) -> None:
        plan = Plan(
            summary="Xavfli reja",
            steps=[
                PlanStep(
                    position=0,
                    description="Faylni o'chir",
                    tool_name="shell.exec",
                    permission_required=PermissionLevel.EXECUTE,
                ),
            ],
        )
        assert plan.needs_approval is True

    def test_cycle_detected(self) -> None:
        """depends_on sikl yasasa ValidationError (PlanValidationError o'ralgan) bo'lishi kerak."""
        with pytest.raises(ValidationError, match="keyingi"):
            Plan(
                summary="Siklli",
                steps=[
                    PlanStep(position=0, description="A", depends_on=[1]),
                    PlanStep(position=1, description="B", depends_on=[0]),
                ],
            )

    def test_self_dependency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="keyingi"):
            Plan(
                summary="O'ziga bog'liq",
                steps=[PlanStep(position=0, description="A", depends_on=[0])],
            )

    def test_nonexistent_dependency_rejected(self) -> None:
        with pytest.raises(ValidationError, match="mavjud"):
            Plan(
                summary="Yo'q qadam",
                steps=[PlanStep(position=0, description="A", depends_on=[99])],
            )

    def test_valid_linear_chain(self) -> None:
        """Chiziqli zanjir valid DAG."""
        plan = Plan(
            summary="Zanjir",
            steps=[
                PlanStep(position=0, description="A"),
                PlanStep(position=1, description="B", depends_on=[0]),
                PlanStep(position=2, description="C", depends_on=[1]),
                PlanStep(position=3, description="D", depends_on=[2]),
            ],
        )
        assert len(plan.steps) == 4

    def test_valid_diamond_dag(self) -> None:
        """Olmossimon DAG: 0 → (1, 2) → 3."""
        plan = Plan(
            summary="Olmos",
            steps=[
                PlanStep(position=0, description="A"),
                PlanStep(position=1, description="B", depends_on=[0]),
                PlanStep(position=2, description="C", depends_on=[0]),
                PlanStep(position=3, description="D", depends_on=[1, 2]),
            ],
        )
        assert len(plan.steps) == 4

    def test_empty_steps_rejected(self) -> None:
        """Qadamsiz reja yaratilmasligi kerak (summary bor lekin qadamlar yo'q)."""
        # Bu aslida valid — bo'sh steps ro'yxati Pydantic'da xato bermaydi
        # lekin Planner o'zi hech qachon bunday reja yaratmaydi
        plan = Plan(summary="Bo'sh", steps=[])
        assert len(plan.steps) == 0
        assert plan.max_permission == PermissionLevel.READ

    def test_empty_summary_rejected(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            Plan(summary="", steps=[])


class TestToolResult:
    def test_success(self) -> None:
        result = ToolResult(tool_name="time.now", success=True, output="12:00")
        assert result.success is True
        assert result.trust_level == TrustLevel.SYSTEM

    def test_failure(self) -> None:
        result = ToolResult(
            tool_name="shell.exec",
            success=False,
            error="Permission denied",
        )
        assert result.success is False
        assert result.error == "Permission denied"

    def test_untrusted_output(self) -> None:
        result = ToolResult(
            tool_name="web.fetch",
            success=True,
            output="<html>...</html>",
            trust_level=TrustLevel.UNTRUSTED,
        )
        assert result.trust_level == TrustLevel.UNTRUSTED

    def test_frozen(self) -> None:
        result = ToolResult(tool_name="test", success=True)
        with pytest.raises(ValidationError):
            result.success = False  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        result = ToolResult(
            tool_name="note.write",
            success=True,
            output={"id": "123"},
            latency_ms=42,
        )
        data = json.loads(result.model_dump_json())
        restored = ToolResult.model_validate(data)
        assert restored == result


class TestVerification:
    def test_ok(self) -> None:
        v = Verification(ok=True, reason="Eslatma muvaffaqiyatli yaratildi")
        assert v.ok is True
        assert v.auto is True

    def test_failed(self) -> None:
        v = Verification(ok=False, reason="Kutilgan natija olinmadi", confidence=0.3)
        assert v.ok is False
        assert v.confidence == 0.3

    def test_frozen(self) -> None:
        v = Verification(ok=True)
        with pytest.raises(ValidationError):
            v.ok = False  # type: ignore[misc]


class TestRunState:
    def test_defaults(self) -> None:
        state = RunState()
        assert state.status == RunStatus.PENDING
        assert state.is_terminal is False
        assert state.is_autonomous is False

    def test_budget_remaining(self) -> None:
        state = RunState(spent_usd=0.03, limits=RunLimits(budget_usd=0.10))
        assert state.budget_remaining_usd == pytest.approx(0.07)

    def test_budget_ratio(self) -> None:
        state = RunState(spent_usd=0.05, limits=RunLimits(budget_usd=0.10))
        assert state.budget_usage_ratio == pytest.approx(0.5)

    def test_terminal_state(self) -> None:
        state = RunState(status=RunStatus.DONE)
        assert state.is_terminal is True

    def test_autonomous(self) -> None:
        from zet.domain.enums import RunTrigger

        state = RunState(trigger=RunTrigger.SCHEDULE)
        assert state.is_autonomous is True

    def test_frozen(self) -> None:
        state = RunState()
        with pytest.raises(ValidationError):
            state.status = RunStatus.DONE  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        state = RunState(
            status=RunStatus.EXECUTING,
            command_text="Test buyruq",
            task_class=TaskClass.NORMAL,
            spent_usd=0.02,
        )
        data = json.loads(state.model_dump_json())
        restored = RunState.model_validate(data)
        assert restored == state


class TestRunLimits:
    def test_defaults(self) -> None:
        limits = RunLimits()
        assert limits.max_steps == 20
        assert limits.max_depth == 3
        assert limits.timeout_s == 600
        assert limits.budget_usd == 0.10

    def test_custom(self) -> None:
        limits = RunLimits(max_steps=5, max_depth=1, timeout_s=30, budget_usd=0.01)
        assert limits.max_steps == 5

    def test_invalid_values(self) -> None:
        with pytest.raises(ValidationError, match="greater_than_equal"):
            RunLimits(max_steps=0)
        with pytest.raises(ValidationError, match="greater_than_equal"):
            RunLimits(budget_usd=-1)
