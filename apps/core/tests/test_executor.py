"""Z1.11 — Executor testlari.

FakeProvider'siz, to'g'ridan-to'g'ri ToolRegistry + PermissionPolicy bilan.

Tekshiriladi:
    - Happy path: 2 qadamli reja muvaffaqiyatli bajariladi
    - EXECUTE qadami tasdiqsiz → ApprovalRequiredError
    - Tasdiqlangan qadam → bajariladi
    - KillSwitch yoqilgan → KillSwitchEngagedError
    - Budjet tugagan → BudgetExhaustedError
    - Tool topilmadi → FAILED
    - dry_run → haqiqiy ish bajarilmaydi
    - Dependency bajarilmagan → SKIPPED
    - Fikrlash qadami (tool_name=None) → DONE
"""

from __future__ import annotations

from typing import Any

import pytest

from zet.core.executor import (
    ApprovalRequiredError,
    BudgetExhaustedError,
    Executor,
)
from zet.domain.enums import PermissionLevel, StepStatus, TrustLevel
from zet.domain.plan import Plan, PlanStep
from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry

# ── Test tool'lari ──────────────────────────────────────────────────


class _ReadTool(Tool):
    """READ tool — har doim muvaffaqiyatli."""

    @property
    def name(self) -> str:
        return "test.read"

    @property
    def description(self) -> str:
        return "O'qish"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> str:
        return "o'qildi"


class _WriteTool(Tool):
    """WRITE tool."""

    @property
    def name(self) -> str:
        return "test.write"

    @property
    def description(self) -> str:
        return "Yozish"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    async def _execute(self, params: dict[str, Any]) -> str:
        return "yozildi"


class _ExecTool(Tool):
    """EXECUTE tool."""

    @property
    def name(self) -> str:
        return "test.exec"

    @property
    def description(self) -> str:
        return "Bajarish"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    async def _execute(self, params: dict[str, Any]) -> str:
        return "bajarildi"


# ── Yordamchilar ────────────────────────────────────────────────────


def _make_registry(*tools: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _make_executor(
    registry: ToolRegistry | None = None,
    policy: PermissionPolicy | None = None,
    killswitch: KillSwitchState | None = None,
    budget_usd: float = 0.10,
) -> Executor:
    return Executor(
        registry=registry or _make_registry(_ReadTool(), _WriteTool(), _ExecTool()),
        policy=policy or PermissionPolicy(),
        killswitch=killswitch or KillSwitchState(),
        budget_usd=budget_usd,
    )


def _simple_plan(steps: list[PlanStep] | None = None) -> Plan:
    if steps is None:
        steps = [
            PlanStep(
                position=0,
                description="O'qish",
                tool_name="test.read",
                permission_required=PermissionLevel.READ,
            ),
            PlanStep(
                position=1,
                description="Yozish",
                tool_name="test.write",
                permission_required=PermissionLevel.WRITE,
                depends_on=[0],
            ),
        ]
    return Plan(summary="Test reja", steps=steps)


# ── Testlar ─────────────────────────────────────────────────────────


class TestExecutor:
    async def test_happy_path(self) -> None:
        """2 qadamli reja muvaffaqiyatli bajariladi."""
        executor = _make_executor()
        ctx = await executor.execute_plan(_simple_plan())

        assert len(ctx.results) == 2
        assert ctx.results[0].status == StepStatus.DONE
        assert ctx.results[1].status == StepStatus.DONE

    async def test_execute_needs_approval(self) -> None:
        """EXECUTE qadami tasdiqsiz → ApprovalRequiredError."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="Bajarish",
                    tool_name="test.exec",
                    permission_required=PermissionLevel.EXECUTE,
                ),
            ]
        )
        executor = _make_executor()

        with pytest.raises(ApprovalRequiredError, match="tasdiq"):
            await executor.execute_plan(plan)

    async def test_approved_step_executes(self) -> None:
        """Tasdiqlangan EXECUTE qadami → bajariladi."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="Bajarish",
                    tool_name="test.exec",
                    permission_required=PermissionLevel.EXECUTE,
                ),
            ]
        )
        executor = _make_executor()
        ctx = await executor.execute_plan(plan, approved_steps={0})

        assert ctx.results[0].status == StepStatus.DONE

    async def test_killswitch_engaged(self) -> None:
        """KillSwitch yoqilgan → KillSwitchEngagedError."""
        ks = KillSwitchState()
        ks.engage(reason="Test")

        executor = _make_executor(killswitch=ks)

        with pytest.raises(KillSwitchEngagedError):
            await executor.execute_plan(_simple_plan())

    async def test_budget_exhausted(self) -> None:
        """Budjet 0 → BudgetExhaustedError."""
        executor = _make_executor(budget_usd=0.0)

        with pytest.raises(BudgetExhaustedError, match="Budjet"):
            await executor.execute_plan(_simple_plan())

    async def test_tool_not_found(self) -> None:
        """Mavjud bo'lmagan tool → FAILED."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="Mavjud emas",
                    tool_name="nonexistent.tool",
                    permission_required=PermissionLevel.READ,
                ),
            ]
        )
        executor = _make_executor()
        ctx = await executor.execute_plan(plan)

        assert ctx.results[0].status == StepStatus.FAILED
        assert "topilmadi" in (ctx.results[0].error or "")

    async def test_dry_run(self) -> None:
        """dry_run → haqiqiy ish bajarilmaydi."""
        executor = _make_executor()
        ctx = await executor.execute_plan(_simple_plan(), dry_run=True)

        assert len(ctx.results) == 2
        assert ctx.results[0].status == StepStatus.DONE
        assert ctx.results[0].tool_result is not None
        assert ctx.results[0].tool_result.output["dry_run"] is True

    async def test_thinking_step(self) -> None:
        """tool_name=None → DONE (fikrlash qadami)."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="Fikrla",
                    tool_name=None,
                    permission_required=PermissionLevel.READ,
                ),
            ]
        )
        executor = _make_executor()
        ctx = await executor.execute_plan(plan)

        assert ctx.results[0].status == StepStatus.DONE
        assert ctx.results[0].tool_result is None

    async def test_dependency_failed_skips_dependent(self) -> None:
        """Birinchi qadam FAILED → ikkinchi SKIPPED."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="Mavjud emas",
                    tool_name="nonexistent.tool",
                    permission_required=PermissionLevel.READ,
                ),
                PlanStep(
                    position=1,
                    description="Yozish",
                    tool_name="test.write",
                    permission_required=PermissionLevel.WRITE,
                    depends_on=[0],
                ),
            ]
        )
        executor = _make_executor()
        ctx = await executor.execute_plan(plan)

        assert ctx.results[0].status == StepStatus.FAILED
        assert ctx.results[1].status == StepStatus.SKIPPED

    async def test_budget_property(self) -> None:
        """Budget qiymatlari to'g'ri."""
        executor = _make_executor(budget_usd=1.0)
        assert executor.budget_remaining_usd == 1.0
        assert executor.spent_usd == 0.0

    async def test_untrusted_write_needs_approval(self) -> None:
        """UNTRUSTED kontekst + WRITE → tasdiq kerak."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="Yozish",
                    tool_name="test.write",
                    permission_required=PermissionLevel.WRITE,
                ),
            ]
        )
        executor = _make_executor()

        with pytest.raises(ApprovalRequiredError):
            await executor.execute_plan(plan, trust=TrustLevel.UNTRUSTED)

    async def test_three_step_chain(self) -> None:
        """3 qadamli zanjir: 0→1→2."""
        plan = _simple_plan(
            [
                PlanStep(
                    position=0,
                    description="O'qi",
                    tool_name="test.read",
                    permission_required=PermissionLevel.READ,
                ),
                PlanStep(
                    position=1,
                    description="O'qi 2",
                    tool_name="test.read",
                    permission_required=PermissionLevel.READ,
                    depends_on=[0],
                ),
                PlanStep(
                    position=2,
                    description="Yoz",
                    tool_name="test.write",
                    permission_required=PermissionLevel.WRITE,
                    depends_on=[1],
                ),
            ]
        )
        executor = _make_executor()
        ctx = await executor.execute_plan(plan)

        assert all(ctx.results[i].status == StepStatus.DONE for i in range(3))
