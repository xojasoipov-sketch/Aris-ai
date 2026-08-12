"""Orchestrator — Intent → Plan → Execute → Verify oqimini boshqaradi (Z1.14+).

Ilgari bu bog'lovchi qatlam yo'q edi: `IntentRecognizer`, `Planner`, `Executor`,
`ApprovalService` va `Verifier` har biri alohida-alohida, mustaqil test qilingan
edi, lekin ularni birlashtirib ishga tushiruvchi kod yo'q edi (`/api/v1/run`
faqat "accepted" deb qaytarardi). API va CLI endi shu modul orqali ishlaydi —
ikkalasi ham alohida-alohida pipeline yozmaydi.

Oqim:
    1. `start()` — buyruqni Intent → Plan → Executor orqali oxirigacha bajaradi
    2. Agar qadam tasdiq talab qilsa (V-32) — `ApprovalService`ga so'rov
       yaratiladi, run `AWAITING_APPROVAL` holatida to'xtaydi
    3. Ega `approve()`/`reject()` chaqirganda — `resume()` bajarishni davom
       ettiradi (tasdiqlangan qadamlar `approved_steps`ga qo'shilgan holda)
    4. Yakunda `Verifier` natijani tekshiradi

Bog'liq qarorlar:
    A-01 — run holat mashinasi
    V-32 — majburiy tasdiq
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog

from zet.core.executor import (
    ApprovalRequiredError,
    BudgetExhaustedError,
    ExecutionContext,
    Executor,
    RecallFn,
)
from zet.core.intent import AmbiguousCommandError, IntentError, IntentRecognizer
from zet.core.planner import Planner, PlannerError
from zet.core.verifier import Verifier
from zet.domain.command import Command
from zet.domain.enums import RunStatus, StepStatus, TrustLevel
from zet.domain.plan import Plan
from zet.llm.base import LLMError
from zet.llm.router import ModelRouter
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


def _build_answer(ctx: ExecutionContext, *, plan_summary: str) -> str:
    """Bajarilgan qadamlardan EGA UCHUN javob yig'adi.

    Ilgari bu yerda jarayon hisoboti turardi:

        f"{plan.summary} — {steps_done}/{steps_total} qadam bajarildi"

    Ega "Nimalar qilolasan?" deb so'raganda ko'rgan yagona narsa
    "...rejasi — 1/1 qadam bajarildi" edi. Reja bor, "bajarildi" belgisi
    bor — javob yo'q. V-01 aynan buning aksini talab qiladi: natija,
    jarayon emas.

    Endi javob — bajarilgan qadamlarning matnli chiqishi. Odatda bu
    oxirgi fikrlash qadami; tool zanjirida esa barcha mazmunli
    chiqishlar birlashtiriladi.

    Hech bir qadam matn bermasa (masalan hammasi jim WRITE tool'lar) —
    o'shanda reja xulosasi qaytadi, chunki ega baribir nimadir
    bajarilganini bilishi kerak.
    """
    texts = [
        ctx.results[pos].text.strip()
        for pos in sorted(ctx.results)
        if ctx.results[pos].status == StepStatus.DONE and ctx.results[pos].text.strip()
    ]
    if not texts:
        return plan_summary
    # Oxirgi fikrlash qadami odatda oldingilarni allaqachon umumlashtiradi,
    # shuning uchun takrorlamaymiz — faqat noyob matnlar.
    unique = list(dict.fromkeys(texts))
    return unique[-1] if len(unique) == 1 else "\n\n".join(unique)


class OrchestratorError(Exception):
    """Orchestrator darajasidagi umumiy xato."""


class RunNotFoundError(OrchestratorError):
    """Berilgan run_id bo'yicha run topilmadi."""


@dataclass
class RunRecord:
    """Bitta run uchun saqlanadigan holat — approval resume uchun.

    `RunState` (domain/run.py) — bu run'ning DB'ga yoziladigan, frozen
    snapshot'i; `RunRecord` esa Orchestrator run davomida yozadigan,
    mutable ish holati (xotirada — boshqa in-memory do'konlar kabi:
    `MemoryStore`, `AgentRegistry`; produksiyada DB-backed versiyaga
    almashtiriladi).
    """

    run_id: uuid.UUID
    command: Command
    plan: Plan | None = None
    approved_steps: set[int] = field(default_factory=set)
    status: RunStatus = RunStatus.PENDING
    result_summary: str | None = None
    verified_ok: bool | None = None
    spent_usd: float = 0.0
    error: str | None = None
    pending_approval_id: uuid.UUID | None = None
    steps_total: int = 0
    steps_done: int = 0


class RunStore:
    """Run holatlarini xotirada saqlaydi (approval resume uchun).

    Produksiyada DB-backed versiyaga almashtiriladi — hozircha boshqa
    in-memory do'konlar bilan bir xil naqsh.
    """

    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, RunRecord] = {}

    def create(self, command: Command) -> RunRecord:
        """Yangi run yozuvi yaratadi."""
        record = RunRecord(run_id=uuid.uuid4(), command=command)
        self._runs[record.run_id] = record
        return record

    def get(self, run_id: uuid.UUID) -> RunRecord:
        """Run yozuvini topadi.

        Raises:
            RunNotFoundError: topilmadi
        """
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFoundError(f"Run '{run_id}' topilmadi") from exc


class Orchestrator:
    """Butun pipeline'ni boshqaradi: intent → reja → bajarish → tekshirish.

    `ApprovalService` va `RunStore` — chaqiruvchi tomonidan berilgan
    singleton'lar bo'lishi kerak (run holati so'rovlar orasida saqlanishi
    uchun); `ModelRouter` esa har bir so'rov uchun yangi (DB sessiyasi
    so'rov chegaralangan bo'lgani uchun).
    """

    def __init__(
        self,
        *,
        router: ModelRouter,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy,
        approval_service: ApprovalService,
        killswitch: KillSwitchState,
        run_store: RunStore,
        budget_usd: float = 0.10,
        max_steps: int = 20,
        recall: RecallFn | None = None,
    ) -> None:
        self._router = router
        # Uzoq muddatli xotira — ega profili va oldingi bilimlar javobga
        # kirishi uchun. Berilmasa pipeline faqat joriy suhbatni ko'radi.
        self._recall = recall
        self._intent = IntentRecognizer(router)
        self._planner = Planner(router, max_steps=max_steps)
        self._verifier = Verifier()
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._approvals = approval_service
        self._killswitch = killswitch
        self._run_store = run_store
        self._budget_usd = budget_usd

    @property
    def approvals(self) -> ApprovalService:
        """Tasdiq xizmati (approval API endpoint'lari uchun)."""
        return self._approvals

    @property
    def run_store(self) -> RunStore:
        """Run holatlari do'koni (status endpoint'lari uchun)."""
        return self._run_store

    async def start(self, command: Command, *, dry_run: bool = False) -> RunRecord:
        """Yangi buyruqni boshidan oxirigacha bajaradi (yoki tasdiq kutadi).

        Raises:
            KillSwitchEngagedError: emergency stop yoqilgan — hech narsa
                boshlanmaydi (fail-closed)
        """
        self._killswitch.check()

        record = self._run_store.create(command)
        record.status = RunStatus.PLANNING

        try:
            intent = await self._intent.recognize(
                command, available_tools=self._tool_registry.tool_names()
            )
        except AmbiguousCommandError as exc:
            record.status = RunStatus.FAILED
            record.error = exc.question
            return record
        except (IntentError, LLMError) as exc:
            record.status = RunStatus.FAILED
            record.error = f"Intent aniqlab bo'lmadi: {exc}"
            return record

        try:
            # Nomlar emas, IMZOLAR: model qaysi parametr majburiyligini
            # ko'rmasa uni tushirib qoldiradi (`video.learn` `url`siz).
            plan = await self._planner.plan(
                intent, tool_specs=self._tool_registry.tool_signatures()
            )
        except (PlannerError, LLMError) as exc:
            record.status = RunStatus.FAILED
            record.error = f"Reja tuzib bo'lmadi: {exc}"
            return record

        record.plan = plan
        record.steps_total = len(plan.steps)
        return await self._run_plan(record, trust=command.trust_level, dry_run=dry_run)

    async def resume(self, run_id: uuid.UUID, *, dry_run: bool = False) -> RunRecord:
        """Tasdiqlangandan keyin bajarishni davom ettiradi.

        Raises:
            RunNotFoundError: run topilmadi
            OrchestratorError: rejasiz run davom ettirilmoqchi
        """
        record = self._run_store.get(run_id)
        if record.plan is None:
            raise OrchestratorError("Reja mavjud emas — davom ettirib bo'lmaydi")
        return await self._run_plan(record, trust=record.command.trust_level, dry_run=dry_run)

    async def _run_plan(
        self,
        record: RunRecord,
        *,
        trust: TrustLevel,
        dry_run: bool,
    ) -> RunRecord:
        assert record.plan is not None  # noqa: S101 — yuqorida tekshirilgan
        executor = Executor(
            registry=self._tool_registry,
            policy=self._permission_policy,
            killswitch=self._killswitch,
            budget_usd=self._budget_usd,
            # Router fikrlash qadamiga HAQIQIY javob yozish uchun kerak —
            # usiz ega jarayon hisobotini ko'radi, javobni emas.
            router=self._router,
            command_text=record.command.text,
            history=record.command.history,
            recall=self._recall,
        )
        record.status = RunStatus.EXECUTING
        record.pending_approval_id = None

        try:
            ctx = await executor.execute_plan(
                record.plan,
                approved_steps=record.approved_steps,
                trust=trust,
                dry_run=dry_run,
            )
        except ApprovalRequiredError as exc:
            approval = self._approvals.request_approval(
                run_id=record.run_id,
                step_position=exc.step.position,
                reason=exc.decision.reason,
                requested_permission=exc.step.permission_required,
                tool_name=exc.step.tool_name,
                preview={"description": exc.step.description},
            )
            record.status = RunStatus.AWAITING_APPROVAL
            record.pending_approval_id = approval.id
            log.info(
                "orchestrator.awaiting_approval",
                run_id=str(record.run_id),
                approval_id=str(approval.id),
                step=exc.step.position,
            )
            return record
        except BudgetExhaustedError as exc:
            record.status = RunStatus.FAILED
            record.error = str(exc)
            return record

        record.spent_usd += executor.spent_usd
        record.steps_done = sum(1 for res in ctx.results.values() if res.status == StepStatus.DONE)

        verifications = [
            self._verifier.verify_step(res.step, res.tool_result) for res in ctx.results.values()
        ]
        overall = self._verifier.verify_run(verifications)
        record.verified_ok = overall.ok
        record.status = RunStatus.DONE if overall.ok else RunStatus.FAILED
        if not overall.ok:
            record.error = overall.reason
        record.result_summary = _build_answer(ctx, plan_summary=record.plan.summary)
        log.info(
            "orchestrator.run_finished",
            run_id=str(record.run_id),
            status=record.status.value,
            steps_done=record.steps_done,
            spent_usd=record.spent_usd,
        )
        return record

    def approve(self, approval_id: uuid.UUID, *, note: str | None = None) -> RunRecord:
        """Tasdiqni qabul qiladi va tegishli qadamni `approved_steps`ga qo'shadi.

        Bajarilishni davom ettirmaydi — buni chaqiruvchi `resume()` bilan
        alohida qiladi (masalan HTTP javobini tez qaytarish uchun).

        Raises:
            KeyError: tasdiq topilmadi
            ApprovalExpiredError / ApprovalError: `ApprovalService.approve` dagidek
        """
        approval = self._approvals.approve(approval_id, note=note)
        record = self._run_store.get(approval.run_id)
        if approval.step_position is not None:
            record.approved_steps.add(approval.step_position)
        return record

    def reject(self, approval_id: uuid.UUID, *, note: str | None = None) -> RunRecord:
        """Tasdiqni rad etadi va run'ni bekor qiladi.

        Raises:
            KeyError: tasdiq topilmadi
            ApprovalExpiredError / ApprovalError: `ApprovalService.reject` dagidek
        """
        approval = self._approvals.reject(approval_id, note=note)
        record = self._run_store.get(approval.run_id)
        record.status = RunStatus.CANCELLED
        record.error = note or "Ega tomonidan rad etildi"
        return record


__all__ = ["Orchestrator", "OrchestratorError", "RunNotFoundError", "RunRecord", "RunStore"]
