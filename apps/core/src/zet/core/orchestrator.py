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

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from zet.telegram.notifier import Notifier

from zet.core.executor import (
    ApprovalRequiredError,
    AuditFn,
    BudgetExhaustedError,
    ExecutionContext,
    Executor,
    RecallFn,
    StepResult,
)
from zet.core.intent import AmbiguousCommandError, IntentError, IntentRecognizer
from zet.core.planner import Planner, PlannerError
from zet.core.recovery import RecoveryApprovalRequiredError, RecoveryEngine
from zet.core.verifier import Verifier
from zet.domain.command import Command, Intent
from zet.domain.enums import RunStatus, StepStatus, TrustLevel
from zet.domain.plan import Plan
from zet.llm.base import LLMError
from zet.llm.router import ModelRouter
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

WorldStateProvider = Callable[[], Awaitable[str]]
"""Muhit holatini prompt bloki sifatida qaytaruvchi (JB-3).

Aniq tip (`WorldStateBuilder`) emas, funksiya: `Orchestrator` holat
qanday yig'ilishini bilishi shart emas va testda oddiy lambda bilan
almashtiriladi (`recall` bilan bir xil naqsh)."""


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

    AR-01 (BLOCK-4): agar `session_factory` berilgan bo'lsa, `persist()`
    orqali DB'ga write-through yoziladi. Fail-open — DB yiqilsa xotirada
    davom etadi. Startup'da `load_pending_runs()` (zet.core.run_checkpoint)
    orqali AWAITING_APPROVAL run'lar tiklanadi.
    """

    def __init__(
        self,
        *,
        session_factory: "async_sessionmaker[AsyncSession] | None" = None,
        owner_external_id: str = "owner",
    ) -> None:
        self._runs: dict[uuid.UUID, RunRecord] = {}
        # None bo'lsa persist() no-op; testlar shu holatda ishlaydi.
        self._session_factory = session_factory
        self._owner_external_id = owner_external_id

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

    async def persist(self, record: RunRecord) -> None:
        """Runni DB'ga yozib qo'yadi — fail-open, session_factory bo'lsa.

        AWAITING_APPROVAL holatida chaqirilsa, restart'da tiklash
        mumkin bo'ladi. Terminal holat (DONE/FAILED) yozilsa audit
        maqsadida saqlanadi lekin tiklash uchun ishlatilmaydi.
        """
        if self._session_factory is None:
            return
        from zet.core.run_checkpoint import persist_run

        await persist_run(
            self._session_factory,
            record,
            owner_external_id=self._owner_external_id,
        )

    async def load_completed_steps(self, run_id: uuid.UUID, plan: Plan) -> dict[int, StepResult]:
        """HIGH #2 audit fix (KONSOLIDATSIYA v2) — avval DONE bo'lgan
        qadamlarni tiklaydi, `session_factory` bo'lsa (fail-open, bo'sh
        dict qaytaradi aks holda — test/lean, eski xatti-harakat: hech
        narsa checkpoint qilinmaydi, har chaqiruv boshidan bajaradi)."""
        if self._session_factory is None:
            return {}
        from zet.core.run_checkpoint import load_completed_steps

        return await load_completed_steps(self._session_factory, run_id, plan)

    async def persist_step(self, run_id: uuid.UUID, position: int, result: StepResult) -> None:
        """HIGH #2 audit fix — bitta DONE qadam natijasini checkpoint qiladi
        (fail-open, `session_factory` bo'lmasa no-op)."""
        if self._session_factory is None:
            return
        from zet.core.run_checkpoint import persist_step_result

        await persist_step_result(self._session_factory, run_id, position, result)


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
        audit_fn: AuditFn | None = None,
        mark_verified_fn: Callable[[uuid.UUID, bool], Awaitable[None]] | None = None,
        run_timeout_s: int | None = None,
        concurrency_semaphore: asyncio.Semaphore | None = None,
        verifier_judge_provider: object | None = None,
        recovery_engine: RecoveryEngine | None = None,
        notifier: Notifier | None = None,
        world_state_provider: WorldStateProvider | None = None,
    ) -> None:
        self._router = router
        # Uzoq muddatli xotira — ega profili va oldingi bilimlar javobga
        # kirishi uchun. Berilmasa pipeline faqat joriy suhbatni ko'radi.
        self._recall = recall
        self._intent = IntentRecognizer(router)
        self._planner = Planner(router, max_steps=max_steps)
        # LLM-judge verifier tier (V-01, ilgari "Bo'lim 1 uchun faqat
        # deterministic" edi). Provider berilsa uzun jonli-tildagi
        # expected_outcome haqiqiy tekshiruvdan o'tadi; berilmasa eski
        # xatti-harakat (fail-open) qoladi.
        self._verifier = Verifier(llm_judge_provider=verifier_judge_provider)  # type: ignore[arg-type]
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._approvals = approval_service
        self._killswitch = killswitch
        self._run_store = run_store
        self._budget_usd = budget_usd
        # Executor'ga uzatiladigan audit yozuvchi (SR-02). Berilmasa
        # audit yozuvi qilinmaydi (test/lean).
        self._audit_fn = audit_fn
        # A-04 feedback loop: run yakunida CostLedger.verified_ok'ni
        # yangilash. Berilmasa (test/lean) — verified_ok NULL bo'lib qoladi.
        self._mark_verified_fn = mark_verified_fn
        # A-07 tormozlar (GAP_ANALYSIS #6): run wall-clock timeout va
        # global concurrency chegarasi. Berilmasa cheklov yo'q.
        self._run_timeout_s = run_timeout_s
        self._concurrency_semaphore = concurrency_semaphore
        # PART 6 recovery: verify_run FAIL bo'lganda tuzatishga urinish.
        # Berilmasa — eski xatti-harakat (darhol FAILED).
        self._recovery_engine = recovery_engine
        # F1 (BLOCK-3 audit): AWAITING_APPROVAL'ga o'tganda egaga Telegram
        # inline tugmali xabar yuborish. Berilmasa (test/lean) — eski
        # xatti-harakat: run pauza holatida qoladi, lekin hech kim
        # bilmaydi. Inbound tomon (`_approval_runner`, `deps.py`) allaqachon
        # run_id bo'yicha ishlaydi — bu shu zanjirning YETISHMAYOTGAN
        # outbound yarmi.
        self._notifier = notifier
        # JB-3: muhitning joriy holatini yig'uvchi. Run BOSHIDA bir
        # marta chaqiriladi va natija Planner + javob qadamiga uzatiladi.
        # NEGA bir marta: holat run davomida deyarli o'zgarmaydi, har
        # qadamda qayta o'qish esa bir necha ortiqcha DB so'rovi bo'lardi.
        # Berilmasa — eski xatti-harakat (kontekst bloki yo'q).
        self._world_state_provider = world_state_provider
        self._world_state_text = ""

    async def _collect_world_state(self) -> str:
        """Muhit holati bloki — to'liq fail-open (JB-3).

        Provider yiqilsa BO'SH matn qaytadi: kontekst yo'qligi javobni
        kambag'alroq qiladi, lekin run'ni to'xtatmasligi kerak.
        """
        if self._world_state_provider is None:
            return ""
        try:
            return await self._world_state_provider()
        except Exception:
            log.warning("orchestrator.world_state_failed")
            return ""

    @property
    def approvals(self) -> ApprovalService:
        """Tasdiq xizmati (approval API endpoint'lari uchun)."""
        return self._approvals

    @property
    def run_store(self) -> RunStore:
        """Run holatlari do'koni (status endpoint'lari uchun)."""
        return self._run_store

    @property
    def intent_recognizer(self) -> IntentRecognizer:
        """Intent tanuvchi — `Brain` triaj uchun AYNAN shu nusxani ishlatadi.

        NEGA ochiq (public): Brain o'ziga alohida Recognizer qursa, u
        boshqa `ModelRouter`ga (boshqa sessiya, boshqa budjet hisobi,
        testlarda boshqa provayder) bog'lanib qolardi. Bitta run
        doirasidagi barcha LLM chaqiruvlari bir xil router'dan o'tishi
        kerak."""
        return self._intent

    async def start(
        self,
        command: Command,
        *,
        dry_run: bool = False,
        intent: Intent | None = None,
    ) -> RunRecord:
        """Yangi buyruqni boshidan oxirigacha bajaradi (yoki tasdiq kutadi).

        Args:
            command: bajariladigan buyruq
            dry_run: haqiqiy yon effektsiz sinov
            intent: OLDINDAN hisoblangan intent (JB-2). `Brain` so'rovni
                chat/command/goal deb ajratish uchun IntentRecognizer'ni
                allaqachon chaqirgan bo'ladi — uni bu yerga uzatish
                AYNAN BIR XIL LLM chaqiruvining ikki marta ketishini
                oldini oladi. `None` bo'lsa — eski xatti-harakat, intent
                shu yerda hisoblanadi.

        Raises:
            KillSwitchEngagedError: emergency stop yoqilgan — hech narsa
                boshlanmaydi (fail-closed)
            asyncio.TimeoutError: run `run_timeout_s`dan uzun ishladi
        """
        self._killswitch.check()

        # A-07 concurrency brake: agar semafora berilgan bo'lsa,
        # bir vaqtda ishlayotgan run'lar chegaralanadi. Bo'lmasa cheksiz.
        if self._concurrency_semaphore is not None:
            async with self._concurrency_semaphore:
                return await self._start_with_timeout(command, dry_run=dry_run, intent=intent)
        return await self._start_with_timeout(command, dry_run=dry_run, intent=intent)

    async def _start_with_timeout(
        self, command: Command, *, dry_run: bool, intent: Intent | None = None
    ) -> RunRecord:
        """Wall-clock timeout — `run_timeout_s` sozlangan bo'lsa (A-07)."""
        if self._run_timeout_s is None:
            return await self._start_impl(command, dry_run=dry_run, intent=intent)
        try:
            return await asyncio.wait_for(
                self._start_impl(command, dry_run=dry_run, intent=intent),
                timeout=self._run_timeout_s,
            )
        except TimeoutError:
            # Timeout — run yarmida to'xtatildi. RunStore ichida partial
            # yozuv bo'ladi, lekin uni bu yerdan yangilab bo'lmaydi (task
            # cancel qilingan). Chaqiruvchi TimeoutError ni ushlaydi.
            log.warning("orchestrator.timeout", timeout_s=self._run_timeout_s)
            raise

    async def _start_impl(
        self, command: Command, *, dry_run: bool = False, intent: Intent | None = None
    ) -> RunRecord:
        """Asosiy start mantiqi (avvalgi `start`)."""

        record = self._run_store.create(command)
        record.status = RunStatus.PLANNING

        # JB-3: muhit holatini run boshida bir marta o'qiymiz. To'liq
        # fail-open — bu qo'shimcha kontekst, majburiy bosqich emas:
        # o'qib bo'lmasa blok bo'sh qoladi va run odatdagidek davom etadi.
        self._world_state_text = await self._collect_world_state()

        # JB-2: `Brain` triaj uchun intent'ni allaqachon hisoblagan
        # bo'lishi mumkin — uni qayta hisoblash bir xil LLM chaqiruvini
        # ikki marta to'lash demakdir.
        if intent is not None:
            return await self._plan_and_run(record, command, intent, dry_run=dry_run)

        try:
            intent = await self._intent.recognize(
                command,
                available_tools=self._tool_registry.tool_names(),
                run_id=record.run_id,
            )
        except AmbiguousCommandError as exc:
            record.status = RunStatus.FAILED
            record.error = exc.question
            await self._run_store.persist(record)  # AR-01 audit trail
            return record
        except (IntentError, LLMError) as exc:
            record.status = RunStatus.FAILED
            record.error = f"Intent aniqlab bo'lmadi: {exc}"
            await self._run_store.persist(record)  # AR-01 audit trail
            return record

        return await self._plan_and_run(record, command, intent, dry_run=dry_run)

    async def _plan_and_run(
        self,
        record: RunRecord,
        command: Command,
        intent: Intent,
        *,
        dry_run: bool,
    ) -> RunRecord:
        """Intent tayyor bo'lgach: reja tuzish va bajarish.

        `_start_impl`dan ajratildi (JB-2) — oldindan hisoblangan intent
        bilan kelgan yo'l ham AYNAN shu zanjirdan o'tsin, nusxa mantiq
        paydo bo'lmasin.
        """
        try:
            # Nomlar emas, IMZOLAR: model qaysi parametr majburiyligini
            # ko'rmasa uni tushirib qoldiradi (`video.learn` `url`siz).
            plan = await self._planner.plan(
                intent,
                tool_specs=self._tool_registry.tool_signatures(),
                run_id=record.run_id,
                # B3 audit fix (KONSOLIDATSIYA v2): Planner ham suhbat
                # tarixini ko'rishi kerak — aks holda "shunga qo'shimcha
                # qadam qo'sh" kabi ergash buyruqlar uchun Intent allaqachon
                # context'siz bo'lgani, reja ham noaniq chiqadi.
                history=command.history,
                # JB-3: reja tuzayotganda ZET "dunyoni ko'rsin" — qanday
                # loyiha/vazifa bor, nima tasdiq kutmoqda, budjet holati.
                world_state=self._world_state_text,
            )
        except (PlannerError, LLMError) as exc:
            record.status = RunStatus.FAILED
            record.error = f"Reja tuzib bo'lmadi: {exc}"
            await self._run_store.persist(record)  # AR-01 audit trail
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
            audit_fn=self._audit_fn,
            # A-04: Router.complete() → CostLedger.run_id yozilsin
            run_id=record.run_id,
            # JB-3: muhitning joriy holati — javob yozish qadamiga.
            world_state=self._world_state_text,
        )
        record.status = RunStatus.EXECUTING
        record.pending_approval_id = None

        # KRITIK TARTIB (A1 audit naqshining davomi): `run` qatori DB'ga
        # bajarish BOSHLANISHIDAN OLDIN yozilishi SHART — pastdagi
        # `step_done_fn` execute_plan() ICHIDA (birinchi qadam
        # tugashi bilanoq) chaqiriladi va `persist_step()` FK orqali
        # `run` qatoriga bog'lanadi. Agar bu yerda persist qilinmasa,
        # `persist_step_result()` "run topilmadi" deb JIMGINA o'tkazib
        # yuboradi (fail-open) — natijada checkpoint HECH QACHON
        # yozilmaydi va HIGH #2 fix amalda ISHLAMAYDI (aynan shu bug
        # test yozish paytida real ravishda topildi va tuzatildi).
        await self._run_store.persist(record)

        # HIGH #2 audit fix (KONSOLIDATSIYA v2): avval DONE bo'lgan
        # qadamlarni tiklaymiz — bu `resume()` (masalan approval'dan
        # keyin) rejaning BOSHIDAN qayta boshlamasligi uchun SHART.
        # Ilgari har chaqiruv yangi bo'sh `ExecutionContext` yaratardi —
        # idempotent bo'lmagan WRITE/EXECUTE qadam (masalan xabar
        # yuborish) resume'da IKKINCHI marta bajarilib qolardi.
        completed_steps = await self._run_store.load_completed_steps(record.run_id, record.plan)

        async def _persist_step_checkpoint(position: int, result: StepResult) -> None:
            # dry_run — simulyatsiya, HAQIQIY bajarilish emas; buni
            # "DONE" deb checkpoint qilib qo'ysak, keyingi HAQIQIY
            # (dry_run=False) urinish yolg'ondan "allaqachon bajarilgan"
            # deb hisoblab tool'ni umuman chaqirmay qo'yardi.
            if dry_run:
                return
            await self._run_store.persist_step(record.run_id, position, result)

        try:
            ctx = await executor.execute_plan(
                record.plan,
                approved_steps=record.approved_steps,
                trust=trust,
                dry_run=dry_run,
                completed_steps=completed_steps,
                step_done_fn=_persist_step_checkpoint,
            )
        except ApprovalRequiredError as exc:
            return await self._handle_approval_required(record, exc)
        except BudgetExhaustedError as exc:
            record.status = RunStatus.FAILED
            record.error = str(exc)
            await self._run_store.persist(record)  # AR-01 audit trail
            return record

        record.spent_usd += executor.spent_usd
        record.steps_done = sum(1 for res in ctx.results.values() if res.status == StepStatus.DONE)

        # verify_step endi async (LLM-judge tier qo'shildi). Barchasini
        # ketma-ket tekshirish — tartib deterministik va LLM-judge chaqirish
        # kam holatda ishlaydi, parallelism kerak emas.
        record.status = RunStatus.VERIFYING
        step_verifications = [
            (res.step, await self._verifier.verify_step(res.step, res.tool_result))
            for res in ctx.results.values()
        ]
        verifications = [v for _, v in step_verifications]
        overall = self._verifier.verify_run(verifications)

        # PART 6 recovery: verify FAIL bo'lgan bo'lsa va recovery_engine
        # ulangan bo'lsa — FAIL→DIAGNOSE→FIX→RETRY→VERIFY sikliga
        # o'tamiz. Ilgari bu yerda darhol FAILED bo'lardi va ega
        # tuzatish urinishini umuman ko'rmasdi (AUTONOMY_AUDIT §2.5).
        if not overall.ok and self._recovery_engine is not None:
            failed_pairs = [(step, ver) for step, ver in step_verifications if not ver.ok]
            record.status = RunStatus.RECOVERING
            log.info(
                "orchestrator.recovering",
                run_id=str(record.run_id),
                failed_steps=[step.position for step, _ in failed_pairs],
            )
            try:
                outcome = await self._recovery_engine.attempt(
                    plan=record.plan,
                    ctx=ctx,
                    failed_verifications=failed_pairs,
                    trust=trust,
                    approved_steps=record.approved_steps,
                )
            except ApprovalRequiredError as exc:
                # D1 (KONSOLIDATSIYA v2, MAJBURIY talab): Recovery Engine'ning
                # HIGH-risk fix qadami HECH QACHON o'zining "men tuzataman"
                # holatidan foydalanib Approval Engine'ni chetlab o'tolmaydi.
                # AYNAN oddiy reja qadami kabi — bir umumiy `_handle_approval_
                # required()` orqali — AWAITING_APPROVAL'ga o'tadi (`exc` bu
                # yerda oddiy `ApprovalRequiredError` yoki uning `extended_
                # plan` olib yuruvchi `RecoveryApprovalRequiredError`
                # kichik turi bo'lishi mumkin — handler ikkalasini ham biladi).
                return await self._handle_approval_required(record, exc)
            if outcome.recovered:
                record.plan = outcome.extended_plan
                record.verified_ok = True
                record.status = RunStatus.DONE
                record.error = None
            else:
                record.verified_ok = False
                record.status = RunStatus.FAILED
                # Halol yiqilish: sabab — oxirgi diagnos yoki verify sababi
                # (PART 8 "never fake autonomy").
                if outcome.diagnoses:
                    record.error = outcome.diagnoses[-1].root_cause
                else:
                    record.error = outcome.final_verification.reason
        else:
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
        # A-04 feedback: shu run'ning barcha LLM chaqiruvlarini
        # "verified" deb belgilash — kelajakda ModelRouter shu ma'lumot
        # asosida success_rate hisoblab, marshrutlashni sozlashi mumkin.
        if self._mark_verified_fn is not None:
            try:
                await self._mark_verified_fn(record.run_id, record.verified_ok)
            except Exception:
                log.warning("orchestrator.mark_verified_failed", run_id=str(record.run_id))
        # AR-01: terminal holat yozib qo'yiladi (DONE yoki FAILED).
        # DONE run tiklashga qarab bermaydi (kutmayapti) lekin audit
        # uchun ko'zga tashlab qo'yilishi zarur.
        await self._run_store.persist(record)
        return record

    async def _handle_approval_required(
        self, record: RunRecord, exc: ApprovalRequiredError
    ) -> RunRecord:
        """`ApprovalRequiredError`ni AWAITING_APPROVAL holatiga aylantiradi.

        NEGA umumlashtirildi (D1 audit, KONSOLIDATSIYA v2): ilgari bu
        mantiq faqat `_run_plan`ning ASOSIY `executor.execute_plan()`
        chaqiruvi atrofida bor edi. Recovery Engine'ning HIGH-risk fix
        qadami ham AYNAN shu yo'ldan o'tishi SHART — ikkita alohida/
        yengillashtirilgan yo'l qolsa, ular orasidagi kelajakdagi farq
        o'zi bitta yashirin approval-bypass yo'liga aylanib qolishi
        mumkin edi. Endi ikkalasi — oddiy mission-qadam VA recovery
        fix-qadam — BITTA kodni chaqiradi.

        `exc` `RecoveryApprovalRequiredError` bo'lsa (`core/recovery.py`),
        `extended_plan`ni olib yuradi — tasdiqdan keyingi `resume()` ASL
        emas, fix qadamlari qo'shilgan TUZATILGAN rejani bajarishi kerak,
        aks holda ega tasdiqlagan qadam rejada umuman topilmay qoladi.
        """
        record.status = RunStatus.AWAITING_APPROVAL
        if isinstance(exc, RecoveryApprovalRequiredError):
            record.plan = exc.extended_plan
            record.steps_total = len(exc.extended_plan.steps)

        # KRITIK TARTIB (A1 audit, real Postgres'da topilgan race'ni
        # yopadi): `run` qatori DB'ga AVVAL yozilishi SHART, chunki
        # `approval` jadvali `run_id`ga FK bilan bog'langan
        # (`fk_approval_run_id_run`). Bu run uchun BIRINCHI DB yozuvi —
        # PLANNING bosqichida persist chaqirilmaydi. Agar tartib
        # teskari bo'lsa (avval request_approval, keyin run persist),
        # ApprovalService._persist() fon vazifasi (create_task,
        # kutilmaydi) run qatori hali committed bo'lmasdan ishga
        # tushishi mumkin — natija: `ForeignKeyViolationError:
        # insert or update on table "approval" violates foreign key
        # constraint`. SQLite'da bu HECH QACHON ko'rinmaydi (FK
        # cheklovi default o'chirilgan), faqat real Postgres bilan
        # sinaganda topildi — aynan shuning uchun A1 (real Postgres
        # tekshiruvi) unit testlardan ko'proq narsani ochib berdi.
        await self._run_store.persist(record)

        approval = self._approvals.request_approval(
            run_id=record.run_id,
            step_position=exc.step.position,
            reason=exc.decision.reason,
            requested_permission=exc.step.permission_required,
            tool_name=exc.step.tool_name,
            preview={"description": exc.step.description},
        )
        record.pending_approval_id = approval.id
        log.info(
            "orchestrator.awaiting_approval",
            run_id=str(record.run_id),
            approval_id=str(approval.id),
            step=exc.step.position,
            via_recovery=isinstance(exc, RecoveryApprovalRequiredError),
        )
        # A1 audit fix: `request_approval()` o'zi ham fire-and-forget
        # background yozuvni rejalashtiradi (`ApprovalService._persist`),
        # lekin bu yerda DETERMINISTIK kutamiz — `run` qatori endigina
        # yozilgan (yuqorida), approval FK shu qatorga bog'lanadi, race
        # bo'lmasligi kafolatlanishi kerak. Fail-open (persist_pending
        # ichida xato yutiladi).
        await self._approvals.persist_pending(approval)
        # Eslatma: `pending_approval_id` DB'da alohida ustun sifatida
        # saqlanmaydi (`run` jadvalida bunday maydon yo'q) — restart'dan
        # keyin `load_pending_approvals()` uni `approval.run_id` orqali
        # mustaqil topadi (run_checkpoint.py), shuning uchun bu yerda
        # qayta persist() shart emas.
        # F1: egaga Telegram inline tugmali xabar — fail-open (xato
        # bo'lsa run pauza holatida qoladi, lekin run oqimi buzilmaydi).
        await self._notify_awaiting_approval(record, exc)
        return record

    async def _notify_awaiting_approval(
        self, record: RunRecord, exc: ApprovalRequiredError
    ) -> None:
        """Egaga Telegram inline tugmali xabar yuboradi (F1, BLOCK-3 audit).

        NEGA. `_approval_runner` (`api/deps.py`) allaqachon `run_id` bo'yicha
        kutilayotgan tasdiqni topib `approve`/`resume` qila oladi — bu
        zanjirning INBOUND yarmi ilgari ham ishlagan. Lekin hech qanday
        production kod yo'li `Notifier.send_approval()`ni chaqirmasdi,
        ya'ni ega HIGH_RISK qadam to'xtaganini Telegram'da UMUMAN ko'rmasdi
        — faqat API javobidagi `pending_approval_id` orqali (agar u yerni
        kim tekshirib tursa). Endi shu OUTBOUND yarmi yopiladi.

        Fail-open: `self._notifier` berilmagan bo'lsa (test/lean wiring)
        yoki yuborish xato bersa — run holati buzilmaydi, faqat log yozib
        qo'yiladi (xuddi `_mark_verified_fn` bilan bir xil naqsh).
        """
        if self._notifier is None:
            return
        try:
            from zet.telegram.keyboards import ApprovalKeyboard

            run_id_str = str(record.run_id)
            risk_line = (
                f"\nRuxsat darajasi: {exc.step.permission_required.value}"
                if exc.step.permission_required is not None
                else ""
            )
            text = (
                f"Qadam: {exc.step.description}\n"
                f"Sabab: {exc.decision.reason}{risk_line}"
            )
            keyboard = ApprovalKeyboard.for_run(run_id_str)
            await self._notifier.send_approval(text, keyboard, run_id=run_id_str)
        except Exception:
            log.warning(
                "orchestrator.notify_awaiting_approval_failed",
                run_id=str(record.run_id),
            )

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
