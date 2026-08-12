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

from collections.abc import Awaitable, Callable, Sequence

import structlog

from zet.domain.command import ConversationTurn
from zet.domain.enums import (
    MessageRole,
    PermissionLevel,
    StepStatus,
    TaskClass,
    TrustLevel,
)
from zet.domain.plan import Plan, PlanStep
from zet.domain.tool import ToolResult
from zet.llm.base import ChatMessage, LLMError
from zet.llm.router import ModelRouter
from zet.prompts.answer import ANSWER_SYSTEM, build_answer_prompt
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionDecision, PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

RecallFn = Callable[[str], Awaitable[list[str]]]
"""Uzoq muddatli xotiradan tegishli yozuvlarni topuvchi.

Aniq tip (`PgMemoryStore`) emas, funksiya: `Executor` xotira
implementatsiyasini bilishi shart emas va testda oddiy lambda bilan
almashtiriladi."""

_MAX_RETRIES = 2
"""Xatoli qadam uchun maksimal qayta urinish (faqat idempotent toollar)."""


def _history_to_messages(history: Sequence[ConversationTurn]) -> list[ChatMessage]:
    """Domen tarixini LLM xabarlariga o'giradi.

    Konvertatsiya AYNAN shu yerda: `domain` qatlami `llm` ga bog'lanmasligi
    kerak (aylanma import), `core` esa ikkalasini ham biladi.
    """
    return [
        ChatMessage(
            role="user" if turn.role == MessageRole.USER else "assistant",
            content=turn.content,
        )
        for turn in history
    ]


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
        output: str = "",
    ) -> None:
        self.step = step
        self.status = status
        self.tool_result = tool_result
        self.error = error
        self.retries = retries
        self.output = output

    @property
    def text(self) -> str:
        """Qadamning matnli natijasi — fikrlash chiqishi yoki tool javobi."""
        if self.output:
            return self.output
        if self.tool_result is not None and self.tool_result.success:
            return str(self.tool_result.output)
        return ""


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
        router: ModelRouter | None = None,
        command_text: str = "",
        history: Sequence[ConversationTurn] = (),
        recall: RecallFn | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._killswitch = killswitch
        self._budget_usd = budget_usd
        self._spent_usd: float = 0.0
        # `router` berilmasa fikrlash qadami matn yozmaydi (eski
        # xatti-harakat). Produksiyada Orchestrator uni doim uzatadi.
        self._router = router
        self._command_text = command_text
        self._history = list(history)
        # Uzoq muddatli xotira. Berilmasa fikrlash qadami faqat joriy
        # suhbatni ko'radi — ega haqidagi profil, oldingi qarorlar va
        # bilim yozuvlari javobga KIRMAYDI.
        self._recall = recall

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

    async def _think(self, step: PlanStep, ctx: ExecutionContext) -> str:
        """Fikrlash qadami — LLM egaga javob yozadi.

        Oldingi qadamlar natijasi (tool chiqishlari ham) kontekstga
        qo'shiladi, ya'ni "qidir → javob ber" zanjiri ishlaydi: javob
        qidiruv natijasiga asoslanadi, LLM xotirasiga emas.

        Router berilmagan bo'lsa (eski chaqiruvchilar, ba'zi testlar) —
        bo'sh matn qaytadi va qadam avvalgidek DONE bo'ladi.
        """
        if self._router is None:
            return ""

        prior = [ctx.results[pos].text for pos in sorted(ctx.results) if pos in ctx.results]

        recalled: list[str] = []
        if self._recall is not None and self._command_text:
            try:
                recalled = await self._recall(self._command_text)
            except Exception:
                # Xotira ishlamasa javob baribir yoziladi — fail-open.
                log.warning("executor.recall_failed", step=step.position)
        messages = [
            *_history_to_messages(self._history),
            ChatMessage(
                role="user",
                content=build_answer_prompt(
                    self._command_text or step.description,
                    step_description=step.description,
                    prior_outputs=prior,
                    recalled=recalled,
                ),
            ),
        ]

        try:
            result = await self._router.complete(
                task_class=TaskClass.NORMAL,
                messages=messages,
                system=ANSWER_SYSTEM,
                max_tokens=1024,
                run_budget_usd=self.budget_remaining_usd,
                run_spent_usd=self._spent_usd,
            )
        except LLMError as exc:
            # Fikrlash qadami butun run'ni yiqitmaydi — javob bo'sh
            # qoladi va Orchestrator buni ochiq ko'rsatadi.
            log.warning("executor.think_failed", step=step.position, error=str(exc))
            return ""

        self._spent_usd += result.cost_usd
        return result.response.text.strip()

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

        # Tool bo'lmasa — FIKRLASH qadami: LLM haqiqiy javob yozadi.
        #
        # Ilgari bu yerda faqat `StepResult(step, status=DONE)` qaytardi —
        # ya'ni "Nimalar qilolasan?" kabi savolga javob UMUMAN
        # generatsiya qilinmasdi va ega jarayon hisobotini ko'rardi.
        if step.tool_name is None:
            output = await self._think(step, ctx)
            log.info("executor.thinking_step", step=step.position, chars=len(output))
            return StepResult(step, status=StepStatus.DONE, output=output)

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
