"""Executor — rejani DAG tartibida bajaradi (Z1.11).

Kirish: `Plan` (Z1.8 chiqishi)
Chiqish: barcha qadamlar bajarilgan yoki xato

Ishlash tartibi (har bir qadam uchun):
    1. KillSwitch tekshiruvi
    2. Budget tekshiruvi (A-07)
    3. Permission tekshiruvi (V-31) → kerak bo'lsa approval
    4. Tool bajarish (ToolRegistry orqali)
    5. Natijani saqlash
    6. Xatolikda: retry (idempotent toollar uchun) yoki FAILED

Bog'liq qarorlar:
    A-01 — run holat mashinasi
    A-07 — avtomatlashtirish tormozlari
    V-31 — ruxsat darajalari
    V-32 — majburiy tasdiq
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from zet.domain.enums import PermissionLevel, StepStatus, TrustLevel
from zet.domain.plan import Plan, PlanStep
from zet.domain.tool import ToolResult
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionDecision, PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

_MAX_RETRIES = 2
"""Xatoli qadam uchun maksimal qayta urinish (faqat idempotent toollar)."""


class ExecutorError(Exception):
    """Executor bajarilishida xato."""


class BudgetExhaustedError(ExecutorError):
    """Budjet tugadi (A-07)."""


class ApprovalRequiredError(ExecutorError):
    """Qadam uchun tasdiq kerak, lekin berilmagan."""

    def __init__(self, step: PlanStep, decision: PermissionDecision) -> None:
        self.step = step
        self.decision = decision
        super().__init__(f"Qadam {step.position}: {decision.reason}")


class StepResult:
    """Bitta qadamning natijasi."""

    def __init__(
        self,
        step: PlanStep,
        *,
        status: StepStatus = StepStatus.PENDING,
        tool_result: ToolResult | None = None,
        error: str | None = None,
        retries: int = 0,
    ) -> None:
        self.step = step
        self.status = status
        self.tool_result = tool_result
        self.error = error
        self.retries = retries


class ExecutionContext:
    """Bajarilish konteksti — barcha natijalar va holat."""

    def __init__(self, plan: Plan) -> None:
        self.plan = plan
        self.results: dict[int, StepResult] = {}
        self.approved_steps: set[int] = set()
        """Tasdiq olingan qadamlar (approval gate'dan o'tgan)."""

    def is_step_ready(self, step: PlanStep) -> bool:
        """Qadam bajarilishga tayyormi (barcha dependency'lar bajarilgan)."""
        return all(
            dep in self.results and self.results[dep].status == StepStatus.DONE
            for dep in step.depends_on
        )

    def record(self, position: int, result: StepResult) -> None:
        """Qadam natijasini saqlash."""
        self.results[position] = result


class Executor:
    """Rejani qadam-qadam bajaradi.

    KillSwitch + Budget + Permission + ToolRegistry integratsiyasi.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PermissionPolicy,
        killswitch: KillSwitchState,
        budget_usd: float = 0.10,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._killswitch = killswitch
        self._budget_usd = budget_usd
        self._spent_usd: float = 0.0

    @property
    def spent_usd(self) -> float:
        """Sarflangan budjet."""
        return self._spent_usd

    @property
    def budget_remaining_usd(self) -> float:
        """Qolgan budjet."""
        return max(0.0, self._budget_usd - self._spent_usd)

    async def execute_plan(
        self,
        plan: Plan,
        *,
        approved_steps: set[int] | None = None,
        trust: TrustLevel = TrustLevel.OWNER,
        dry_run: bool = False,
    ) -> ExecutionContext:
        """Rejani to'liq bajaradi.

        Args:
            plan: bajarilishi kerak bo'lgan reja
            approved_steps: oldindan tasdiqlangan qadamlar
            trust: kontekst ishonch darajasi
            dry_run: haqiqiy ish bajarmaslik

        Returns:
            ExecutionContext — barcha natijalar bilan

        Raises:
            KillSwitchEngagedError: emergency stop yoqilgan
            BudgetExhaustedError: budjet tugagan
            ApprovalRequiredError: tasdiq kerak
        """
        ctx = ExecutionContext(plan)
        if approved_steps:
            ctx.approved_steps = approved_steps

        # Topologik tartiblash — DAG bo'yicha bajarish
        ordered = self._topological_sort(plan.steps)

        for step in ordered:
            # KillSwitch tekshiruvi
            self._killswitch.check()

            # Budget tekshiruvi
            if self.budget_remaining_usd <= 0:
                log.warning(
                    "executor.budget_exhausted",
                    spent=self._spent_usd,
                    budget=self._budget_usd,
                )
                ctx.record(
                    step.position,
                    StepResult(step, status=StepStatus.FAILED, error="Budjet tugadi"),
                )
                raise BudgetExhaustedError(
                    f"Budjet tugadi: {self._spent_usd:.4f}/{self._budget_usd:.4f} USD"
                )

            # Dependency tekshiruvi
            if not ctx.is_step_ready(step):
                log.warning(
                    "executor.dependency_not_ready",
                    step=step.position,
                    depends_on=step.depends_on,
                )
                ctx.record(
                    step.position,
                    StepResult(step, status=StepStatus.SKIPPED, error="Dependency bajarilmagan"),
                )
                continue

            # Qadamni bajarish
            result = await self._execute_step(step, ctx, trust=trust, dry_run=dry_run)
            ctx.record(step.position, result)

            # FAILED bo'lsa — qolgan dependency'li qadamlar skip bo'ladi
            if result.status == StepStatus.FAILED:
                log.error(
                    "executor.step_failed",
                    step=step.position,
                    error=result.error,
                )

        return ctx

    async def _execute_step(
        self,
        step: PlanStep,
        ctx: ExecutionContext,
        *,
        trust: TrustLevel,
        dry_run: bool,
    ) -> StepResult:
        """Bitta qadamni bajaradi — permission + tool + retry."""
        # Permission tekshiruvi
        decision = self._policy.check(
            step.permission_required,
            trust,
            tool_name=step.tool_name,
        )

        if decision.needs_approval and step.position not in ctx.approved_steps:
            log.info(
                "executor.approval_required",
                step=step.position,
                permission=step.permission_required.value,
                tool=step.tool_name,
            )
            raise ApprovalRequiredError(step, decision)

        # Tool bo'lmasa — faqat fikrlash qadami
        if step.tool_name is None:
            log.info("executor.thinking_step", step=step.position)
            return StepResult(step, status=StepStatus.DONE)

        # Tool mavjudligi
        if not self._registry.has(step.tool_name):
            return StepResult(
                step,
                status=StepStatus.FAILED,
                error=f"Tool '{step.tool_name}' registry'da topilmadi",
            )

        # Tool bajarish (retry bilan)
        tool = self._registry.get(step.tool_name)
        caller_perm = self._effective_permission(step, ctx)

        for attempt in range(_MAX_RETRIES + 1):
            tool_result = await self._registry.execute(
                step.tool_name,
                step.tool_params,
                caller_permission=caller_perm,
                dry_run=dry_run,
            )

            if tool_result.success:
                return StepResult(
                    step,
                    status=StepStatus.DONE,
                    tool_result=tool_result,
                    retries=attempt,
                )

            # Idempotent bo'lmasa — retry qilmaslik
            if not tool.idempotent:
                log.warning(
                    "executor.no_retry_not_idempotent",
                    step=step.position,
                    tool=step.tool_name,
                )
                return StepResult(
                    step,
                    status=StepStatus.FAILED,
                    tool_result=tool_result,
                    error=tool_result.error,
                    retries=attempt,
                )

            if attempt < _MAX_RETRIES:
                log.warning(
                    "executor.retry",
                    step=step.position,
                    attempt=attempt,
                    error=tool_result.error,
                )

        # Barcha urinishlar muvaffaqiyatsiz
        return StepResult(
            step,
            status=StepStatus.FAILED,
            tool_result=tool_result,
            error=f"Barcha urinishlar muvaffaqiyatsiz ({_MAX_RETRIES + 1} urinish)",
            retries=_MAX_RETRIES,
        )

    def _effective_permission(
        self,
        step: PlanStep,
        ctx: ExecutionContext,
    ) -> PermissionLevel:
        """Qadam uchun samarali ruxsat darajasi.

        Agar qadam tasdiqlangan bo'lsa — talab qilingan ruxsatni beradi.
        """
        if step.position in ctx.approved_steps:
            return step.permission_required
        return step.permission_required

    def _topological_sort(self, steps: Sequence[PlanStep]) -> list[PlanStep]:
        """DAG bo'yicha topologik tartiblash.

        Plan.steps allaqachon validatsiya qilingan (sikl yo'q),
        shuning uchun bu yerda oddiy tartiblash yetarli.
        """
        return sorted(steps, key=lambda s: s.position)
