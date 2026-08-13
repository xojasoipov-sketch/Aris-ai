"""Mission Engine — strategiya qatlami (Bo'lim 2, §2.2).

NEGA bu qatlam kerak. Mavjud Orchestrator/Run tuzilishi bitta buyruq
siklini (intent → reja → bajarish → tekshirish) boshqaradi. Lekin ega
"sayt qur" desa — bu bitta cikldan ko'proq: kontekst topilishi,
capability'lar tanlanishi, reja tuzilishi, tasdiq olinishi, bir necha
Run orqali bajarilishi va tekshirilishi kerak. Yiqilsa — Recovery Engine
(§2.5) yangi Run bilan davom etadi.

Ilgari bu qatlam yo'q edi va agentlar shu vazifalarni ketma-ket
mustaqil runlar bilan bajarardi. Retry qilingan urinishlar birga
bog'lanmasdi, "kecha qilingan sayt"ni davom ettirish uchun mos
kontekst topilmasdi va approval faqat step darajasida edi (ega uchun
"butun mission"ga bir marta tasdiq berish variantsiz).

MissionEngine mavjud Orchestrator/Executor pipeline'ini AYNI HOLICHA
qayta ishlatadi — u shunchaki YUQORIDA turadi va kompozitsiyani
boshqaradi (CapabilityRegistry, ContextDiscoveryEngine, Planner,
Orchestrator, ApprovalService, RecoveryEngine).

Bog'liq qarorlar:
    A-01 — davomli holat mashinasi
    V-32 — majburiy tasdiq (RiskLevel + WAITING_APPROVAL)
    A-07 — avtonomiya tormozlari (MAX_RETRIES + deadline)
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from pydantic import BaseModel, ConfigDict, Field

from zet.db.base import utcnow
from zet.domain.enums import (
    MissionStatus,
    PermissionLevel,
    RiskLevel,
    StepStatus,
)

if TYPE_CHECKING:
    from zet.core.mission_repository import MissionRepository
    from zet.core.orchestrator import Orchestrator, RunRecord
    from zet.core.planner import Planner
    from zet.security.approvals import ApprovalService

log = structlog.get_logger(__name__)


class MissionError(Exception):
    """Mission darajasidagi umumiy xato."""


class MissionNotFoundError(MissionError):
    """Berilgan mission_id bo'yicha Mission topilmadi (yoki boshqa egaga tegishli)."""


class IllegalMissionTransitionError(MissionError):
    """Mission holat mashinasi ruxsat bermagan o'tish urinildi."""


class MissionTask(BaseModel):
    """Mission ichidagi bitta task — DAG tuguni.

    NEGA `PlanStep` emas: `PlanStep` bitta Run rejasining qadami. Task
    Mission darajasida yashaydi va bir necha Run'lar orasida saqlanadi.
    Bitta Task bir Run tomonidan bajariladi.
    """

    model_config = ConfigDict(from_attributes=True)

    position: int = Field(ge=0)
    title: str = Field(min_length=1)
    depends_on: list[int] = Field(default_factory=list)
    tool: str | None = None
    agent: str | None = None
    status: StepStatus = StepStatus.PENDING
    run_id: uuid.UUID | None = None


class Mission(BaseModel):
    """Mission — strategiya (nima qilish, qanday tekshirish, nimani eslash).

    Pydantic model — repository ORM qatorlaridan `Mission.model_validate(row)`
    orqali toza konvertatsiya qilinadi (`from_attributes=True`).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    owner_id: uuid.UUID
    objective: str
    outcome_criteria: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    tasks: list[MissionTask] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    permissions_required: list[PermissionLevel] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    approval_requirements: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    verification_rules: list[str] = Field(default_factory=list)
    memory_updates: list[str] = Field(default_factory=list)
    status: MissionStatus = MissionStatus.RECEIVED
    priority: int = Field(default=5, ge=0, le=10)
    run_ids: list[uuid.UUID] = Field(default_factory=list)
    pending_approval_id: uuid.UUID | None = None
    retry_count: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── MissionEngine kompozitsiyasi uchun protokollar ──────────────────
#
# NEGA Protocol: MissionEngine to'g'ridan-to'g'ri boshqa modullardan
# import qilmaydi (aylanma import xavfi + testda soxta implementatsiyani
# oson berish). Har bir bog'liq komponent to'liq realizatsiyasi
# `zet.capabilities`, `zet.core.context`, `zet.core.recovery` da yashaydi.


class CapabilityBundleLike(Protocol):
    """CapabilityRegistry.compose() qaytaradigan bundle shakli."""

    capabilities: list[str]
    agents: list[str]
    tools: list[str]
    permissions_required: list[PermissionLevel]
    risk_level: RiskLevel


class CapabilityRegistryLike(Protocol):
    """Capability tanlash uchun minimal interfeys."""

    def compose(
        self, objective: str, context: dict[str, Any]
    ) -> CapabilityBundleLike:  # pragma: no cover — protocol
        ...


class RelevantContextLike(Protocol):
    """ContextDiscoveryEngine chiqishi."""

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover — protocol
        ...


class ContextDiscoveryEngineLike(Protocol):
    """Kontekst topish uchun minimal interfeys."""

    async def discover(
        self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
    ) -> RelevantContextLike:  # pragma: no cover — protocol
        ...


class RecoveryEngineLike(Protocol):
    """RecoveryEngine (§2.5) — LLM'dan patch so'raydi."""

    async def diagnose_and_patch(
        self, mission: Mission, last_failure: str
    ) -> Mission:  # pragma: no cover — protocol
        ...


class LLMJudgeProviderLike(Protocol):
    """Yengil LLM adapter — `api/deps.py::_VerifierJudgeProvider` bilan
    bir xil shakl (`.complete(messages=, system=, max_tokens=)`)."""

    async def complete(
        self, *, messages: Any, system: str | None = None, max_tokens: int = 300, **_: Any
    ) -> Any:  # pragma: no cover — protocol
        ...


class MissionRecoveryAdapter:
    """`RecoveryEngineLike` implementatsiyasi — HIGH #3 audit fix
    (KONSOLIDATSIYA v2): Task-Graph mission darajasida HAQIQIY LLM
    diagnos, D4'dagi bilan bir xil T1_FREE tier yondashuv.

    NEGA `core.recovery.RecoveryEngine`ning O'ZI EMAS: uning
    `attempt(plan, ctx, failed_verifications, ...)` PlanStep/
    ExecutionContext darajasida ishlaydi (bitta Run'ning bitta
    qadamlari). `MissionEngine.recover()` esa Mission/matn darajasida
    (`diagnose_and_patch(mission, last_failure: str)`) — Mission bir
    nechta Run'dan iborat bo'lishi mumkin, alohida qadam/ExecutionContext
    yo'q. Shu sabab bu — ALOHIDA, YENGIL adapter: T1_FREE LLM'dan
    mission-darajali diagnos so'raydi va natijani `mission.constraints`ga
    "recovery hint" sifatida qo'shadi — keyingi urinishda Planner buni
    ko'radi (`_build_user_prompt` `intent.constraints`ni allaqachon
    o'qiydi, B3 audit fix bilan `history` ham qo'shildi).

    Ilgari (KONSOLIDATSIYA v2'gacha): `deps.py` har doim `recovery=None`
    berardi — `recover()`ning o'zi fail-open ("shunchaki qayta
    urinamiz", diagnossiz) edi. Bu — "dumb retry" — LLM nima xato
    bo'lganini HECH QACHON ko'rmasdi.
    """

    def __init__(self, *, llm_provider: LLMJudgeProviderLike, repository: MissionRepository) -> None:
        self._llm = llm_provider
        self._repo = repository

    async def diagnose_and_patch(self, mission: Mission, last_failure: str) -> Mission:
        """T1_FREE LLM'dan bir gaplik diagnos so'raydi va `mission.
        constraints`ga qo'shadi (DB'ga yozadi — `_transition()` faqat
        `status`ni yangilaydi, boshqa maydonlarni EMAS).

        Fail-open: LLM xato bersa yoki bo'sh javob qaytarsa — mission
        O'ZGARTIRILMAY qaytariladi (`recover()`ning o'zi "shunchaki
        qayta urin" bilan davom etadi — MissionEngine invariantiga mos).
        """
        system = (
            "Sen — mission-darajali recovery diagnostikasi. Bir Mission "
            "(ko'p qadamli maqsad) muvaffaqiyatsiz tugadi. Bir GAPDA nima "
            "xato bo'lganini va keyingi urinishda nimaga e'tibor berish "
            "kerakligini yoz. Faqat matn qaytar, JSON emas."
        )
        no_constraints_label = "(yo'q)"
        user = (
            f"MAQSAD: {mission.objective}\n"
            f"XATO: {last_failure[:1000]}\n"
            f"OLDINGI CHEKLOVLAR: {', '.join(mission.constraints) or no_constraints_label}\n"
            f"URINISH: {mission.retry_count + 1}"
        )
        try:
            from zet.llm.base import ChatMessage

            response = await self._llm.complete(
                messages=[ChatMessage(role="user", content=user)],
                system=system,
                max_tokens=300,
            )
        except Exception as exc:
            log.warning("mission_recovery.llm_error", mission_id=str(mission.id), error=str(exc)[:200])
            return mission

        hint = (getattr(response, "text", "") or "").strip()
        if not hint:
            log.warning("mission_recovery.empty_diagnosis", mission_id=str(mission.id))
            return mission

        log.info(
            "mission_recovery.diagnosed",
            mission_id=str(mission.id),
            attempt=mission.retry_count + 1,
            hint=hint[:200],
        )
        new_constraints = [*mission.constraints, f"[recovery] {hint}"]
        return await self._repo.update(mission.id, constraints=new_constraints)


class MemoryStoreLike(Protocol):
    """PgMemoryStore uchun minimal `remember` interfeysi."""

    async def remember(
        self,
        owner_id: uuid.UUID,
        content: str,
        *,
        layer: str,
        source: str,
    ) -> None:  # pragma: no cover — protocol
        ...


class MissionEngine:
    """Mission fazalari bo'yicha driver — Orchestrator'ni yuqoridan boshqaradi.

    Har bir faza method'i (understand/discover/plan/execute/verify/recover)
    holatni bitta bosqichga siljitadi va yozadi. `run_to_completion()`
    ularni tugunga yoki WAITING_APPROVAL'ga yetguncha aylantiradi.

    Guard'lar:
        MAX_RETRIES — verify + recover sikllari cheklangan (§2.5)
        risk_level == HIGH — har doim WAITING_APPROVAL
        deadline — o'tgan bo'lsa avtomatik CANCELLED
    """

    def __init__(
        self,
        *,
        repository: MissionRepository,
        capability_registry: CapabilityRegistryLike,
        context_engine: ContextDiscoveryEngineLike,
        planner: Planner,
        orchestrator: Orchestrator,
        approvals: ApprovalService,
        recovery: RecoveryEngineLike | None = None,
        memory_store: MemoryStoreLike | None = None,
        risk_classifier: Callable[[Mission], RiskLevel] | None = None,
        understand_fn: Callable[[Mission], Awaitable[Mission]] | None = None,
        max_retries: int = 2,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repo = repository
        self._capabilities = capability_registry
        self._context_engine = context_engine
        self._planner = planner
        self._orchestrator = orchestrator
        self._approvals = approvals
        self._recovery = recovery
        self._memory = memory_store
        self._risk_classifier = risk_classifier
        self._understand_fn = understand_fn
        self._max_retries = max_retries
        self._clock = clock

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def repository(self) -> MissionRepository:
        """MissionRepository — MissionOrchestrator kabi tashqi qatlamlar
        Mission yozuvlarini o'qish/yozish uchun ishlatadi.

        NEGA: MissionOrchestrator preflight (kill-switch, bo'sh capability
        bundle) hollarda `set_status(..., FAILED/CANCELLED)` chaqirishi
        kerak. Har birida yangi repository yaratmasdan, engine bilan bir
        xil sessiyani qayta ishlatish uchun oshkor qilingan.
        """
        return self._repo

    # ── Faza method'lari ─────────────────────────────────────────

    async def submit(
        self,
        *,
        owner_id: uuid.UUID,
        objective: str,
        outcome_criteria: str = "",
        constraints: list[str] | None = None,
        deadline: datetime | None = None,
        priority: int = 5,
    ) -> Mission:
        """Yangi Mission yaratadi (RECEIVED)."""
        mission = Mission(
            owner_id=owner_id,
            objective=objective,
            outcome_criteria=outcome_criteria,
            constraints=list(constraints or []),
            deadline=deadline,
            priority=priority,
        )
        stored = await self._repo.create(mission)
        log.info(
            "mission.submitted",
            mission_id=str(stored.id),
            owner_id=str(owner_id),
            priority=priority,
        )
        return stored

    async def understand(self, mission: Mission) -> Mission:
        """RECEIVED → UNDERSTANDING → DISCOVERING.

        Agar `understand_fn` berilmagan bo'lsa — outcome_criteria va
        constraints allaqachon berilgan holda faqat holatni siljitadi
        (fail-open: LLM chaqiruvi majburiy emas).
        """
        mission = await self._transition(mission, MissionStatus.UNDERSTANDING)
        if self._understand_fn is not None:
            mission = await self._understand_fn(mission)
        return await self._transition(mission, MissionStatus.DISCOVERING)

    async def discover(self, mission: Mission) -> Mission:
        """DISCOVERING → PLANNING.

        ContextDiscoveryEngine (§2.3) tegishli kontekstni topadi va
        Mission.context'ga yozadi. Fail-open — kontekst topilmasa
        planning davom etadi.
        """
        try:
            ctx = await self._context_engine.discover(
                mission.objective,
                owner_id=mission.owner_id,
                constraints=mission.constraints,
            )
            context_dict = ctx.to_dict()
        except Exception as exc:
            log.warning("mission.discover_failed", mission_id=str(mission.id), error=str(exc))
            context_dict = {}
        mission = await self._repo.update(mission.id, context=context_dict)
        return await self._transition(mission, MissionStatus.PLANNING)

    async def plan(self, mission: Mission) -> Mission:
        """PLANNING → WAITING_APPROVAL yoki EXECUTING.

        Kompozitsiya (Master Spec §2): CapabilityRegistry.compose()
        objective + context asosida capability'lar, agentlar,
        toollarni tanlaydi. Keyin Planner shu toollar bilan reja tuzadi.
        Reja qadamlari MissionTask[] ga aylantiriladi.
        """
        bundle = self._capabilities.compose(mission.objective, mission.context)

        # Reja tuzish — Planner faqat mission uchun tanlangan toollarni
        # ko'rishi kerak (aks holda LLM begona toollarni chaqirib
        # yubordi). Hozircha tool_specs sifatida faqat nomlarni beramiz
        # — kelajakda CapabilityRegistry to'liq imzolarni ham qaytaradi.
        # Fail-open: planning yiqilsa Mission FAILED holatiga tushadi.
        try:
            plan_tasks = _bundle_to_tasks(bundle)
        except Exception as exc:
            failed = await self._repo.update(mission.id, error=f"planning failed: {exc}")
            return await self._transition(failed, MissionStatus.FAILED, error=str(exc))

        # Risk baholash — mission-level classifier bo'lsa u aytadi;
        # bo'lmasa bundle'dan olinadi.
        risk = (
            self._risk_classifier(mission)
            if self._risk_classifier is not None
            else bundle.risk_level
        )

        mission = await self._repo.update(
            mission.id,
            capabilities=list(bundle.capabilities),
            agents=list(bundle.agents),
            tools=list(bundle.tools),
            permissions_required=[p.value for p in bundle.permissions_required],
            tasks=[t.model_dump(mode="json") for t in plan_tasks],
            risk_level=risk,
        )

        if risk.requires_approval:
            return await self.request_approval(mission)
        return await self._transition(mission, MissionStatus.EXECUTING)

    async def request_approval(self, mission: Mission) -> Mission:
        """PLANNING → WAITING_APPROVAL (yoki EXECUTING → WAITING_APPROVAL)."""
        max_perm = _max_permission(mission.permissions_required)
        reason = "Mission risk level requires owner approval"
        req = self._approvals.request_approval(
            run_id=mission.id,  # mission-level so'rov: run_id yo'q, mission.id ni index sifatida
            mission_id=mission.id,
            reason=reason,
            requested_permission=max_perm,
            preview={"objective": mission.objective, "tools": mission.tools},
        )
        mission = await self._repo.update(mission.id, pending_approval_id=req.id)
        return await self._transition(mission, MissionStatus.WAITING_APPROVAL)

    async def approve(self, mission_id: uuid.UUID, approval_id: uuid.UUID) -> Mission:
        """WAITING_APPROVAL → EXECUTING.

        Tozalash: `pending_approval_id`ni CLEAR sentinel bilan bekor
        qilamiz (adversarial verify topgan bug: `None` "o'zgartirma"
        deb talqin qilinardi, natijada tugagan mission'da eski
        approval_id ko'rinardi va "hali kutayotgan" deb qaraldi)."""
        self._approvals.approve(approval_id)
        mission = await self._repo.get(mission_id)
        if mission.pending_approval_id != approval_id:
            raise MissionError("Approval ID mission bilan mos kelmadi")
        mission = await self._repo.update(mission_id, pending_approval_id=self._repo.CLEAR)
        return await self._transition(mission, MissionStatus.EXECUTING)

    async def execute(self, mission: Mission) -> tuple[Mission, RunRecord | None]:
        """EXECUTING → VERIFYING (yoki WAITING_APPROVAL / FAILED).

        Command tuziladi va Orchestrator.start() chaqiriladi. RunRecord
        Mission bilan `MissionRunLink` orqali bog'lanadi. Kill switch
        yoqilgan bo'lsa `KillSwitchEngagedError` propagate qilinadi va
        Mission FAILED bo'ladi.
        """
        from zet.core.orchestrator import Orchestrator  # noqa: F401 — TYPE_CHECKING
        from zet.domain.command import Command
        from zet.domain.enums import RunStatus, TrustLevel
        from zet.security.killswitch import KillSwitchEngagedError

        command = Command(text=mission.objective, trust_level=TrustLevel.OWNER)
        attempt = mission.retry_count + 1

        try:
            record = await self._orchestrator.start(command)
        except KillSwitchEngagedError as exc:
            reason = f"kill switch engaged: {exc}"
            failed = await self._transition(mission, MissionStatus.FAILED, error=reason)
            return failed, None

        await self._repo.attach_run(mission.id, record.run_id, attempt=attempt)
        mission = await self._repo.get(mission.id)

        if record.status == RunStatus.AWAITING_APPROVAL:
            mission = await self._repo.update(
                mission.id, pending_approval_id=record.pending_approval_id
            )
            mission = await self._transition(mission, MissionStatus.WAITING_APPROVAL)
            return mission, record

        if record.status == RunStatus.FAILED:
            # FAILED run — recovery ga topshiriladi (verifier deb hisoblab).
            mission = await self._transition(mission, MissionStatus.VERIFYING)
            return mission, record

        # DONE — verify fazasiga
        mission = await self._transition(mission, MissionStatus.VERIFYING)
        return mission, record

    async def verify(self, mission: Mission, run_record: RunRecord) -> Mission:
        """VERIFYING → COMPLETED yoki RECOVERING.

        Orchestrator Verifier'i allaqachon ishlagan (run_record.verified_ok).
        Mission darajasidagi qo'shimcha verification_rules bo'sh bo'lsa
        shu belgi yetarli.
        """
        ok = bool(run_record.verified_ok)
        if ok:
            mission = await self._transition(mission, MissionStatus.COMPLETED)
            await self._write_memory_updates(mission)
            log.info("mission.completed", mission_id=str(mission.id), runs=len(mission.run_ids))
            return mission
        error_msg = run_record.error or "verification failed"
        return await self._transition(mission, MissionStatus.RECOVERING, error=error_msg)

    async def recover(self, mission: Mission, last_failure: str) -> Mission:
        """RECOVERING → EXECUTING (yoki FAILED, max_retries oshsa).

        RecoveryEngine (§2.5) tashxis qo'yadi va reja patch'ini
        qaytaradi. Berilmagan bo'lsa — fail-open: shunchaki qayta
        urinamiz. EXECUTING'ga qayta o'tganda `error`ni tozalaymiz —
        aks holda muvaffaqiyatli tugagan mission "Sabab: first attempt
        failed" bilan ko'rinardi (adversarial verify topgan bug #2).
        """
        new_count = mission.retry_count + 1
        mission = await self._repo.update(mission.id, retry_count=new_count)
        if new_count > self._max_retries:
            return await self._transition(
                mission,
                MissionStatus.FAILED,
                error=f"max retries exceeded ({self._max_retries}): {last_failure}",
            )
        if self._recovery is not None:
            try:
                mission = await self._recovery.diagnose_and_patch(mission, last_failure)
            except Exception as exc:
                log.warning("mission.recovery_failed", mission_id=str(mission.id), error=str(exc))
        # Recovery muvaffaqiyatli — xatoni tozalaymiz.
        return await self._transition(mission, MissionStatus.EXECUTING, clear_error=True)

    async def cancel(self, mission_id: uuid.UUID, reason: str) -> Mission:
        """Har qanday non-terminal holatdan → CANCELLED.

        NEGA `_transition` chetlab o'tildi: emergency cancel har doim
        ruxsat etilishi kerak (V-33 bilan bir xil siyosat). Faqat
        terminal holatdan chiqib bo'lmaydi.
        """
        mission = await self._repo.get(mission_id)
        if mission.status.is_terminal:
            raise IllegalMissionTransitionError(
                f"Mission {mission.status.value} — bekor qilib bo'lmaydi"
            )
        return await self._repo.set_status(
            mission_id, MissionStatus.CANCELLED, error=reason, force=True
        )

    async def run_to_completion(self, mission_id: uuid.UUID) -> Mission:
        """Fazalarni terminal yoki WAITING_APPROVAL'ga yetguncha aylantiradi.

        Deadline tekshiruvi har bosqichda: o'tgan bo'lsa mission
        avtomatik CANCELLED bo'ladi.
        """
        mission = await self._repo.get(mission_id)

        while not mission.status.is_terminal and mission.status != MissionStatus.WAITING_APPROVAL:
            if _deadline_expired(mission, self._clock()):
                return await self.cancel(mission.id, "deadline exceeded")

            if mission.status == MissionStatus.RECEIVED:
                mission = await self.understand(mission)
            elif mission.status == MissionStatus.DISCOVERING:
                mission = await self.discover(mission)
            elif mission.status == MissionStatus.PLANNING:
                mission = await self.plan(mission)
            elif mission.status == MissionStatus.EXECUTING:
                mission, record = await self.execute(mission)
                if record is not None and mission.status == MissionStatus.VERIFYING:
                    mission = await self.verify(mission, record)
            elif mission.status == MissionStatus.RECOVERING:
                mission = await self.recover(mission, mission.error or "unknown failure")
            else:  # UNDERSTANDING boshqa oraliq
                break
        return mission

    # ── Ichki yordamchi'lar ──────────────────────────────────────

    async def _transition(
        self,
        mission: Mission,
        target: MissionStatus,
        *,
        error: str | None = None,
        clear_error: bool = False,
    ) -> Mission:
        """Guarded o'tish — MISSION_TRANSITIONS ga tayangan holda.

        `clear_error=True` — recovery muvaffaqiyatli tugab EXECUTING'ga
        qaytganda ishlatiladi (aks holda eski xato "Sabab" da qolib
        ketardi).

        Repository set_status IllegalMissionTransitionError otadi;
        MissionEngine faqat propagate qiladi (qisman yozuvsiz).
        """
        return await self._repo.set_status(mission.id, target, error=error, clear_error=clear_error)

    async def _write_memory_updates(self, mission: Mission) -> None:
        """Yakuniy memory updates'ni PgMemoryStore ga yozadi."""
        if self._memory is None or not mission.memory_updates:
            return
        for content in mission.memory_updates:
            try:
                await self._memory.remember(
                    mission.owner_id,
                    content,
                    layer="project",
                    source=f"mission:{mission.id}",
                )
            except Exception as exc:
                log.warning(
                    "mission.memory_write_failed",
                    mission_id=str(mission.id),
                    error=str(exc),
                )


def _max_permission(levels: list[PermissionLevel] | list[str]) -> PermissionLevel:
    """Ro'yxatdan eng yuqori PermissionLevel'ni tanlaydi (bo'sh — READ)."""
    if not levels:
        return PermissionLevel.READ
    parsed = [PermissionLevel(p) if isinstance(p, str) else p for p in levels]
    return max(parsed, key=lambda p: p.rank)


def _bundle_to_tasks(bundle: CapabilityBundleLike) -> list[MissionTask]:
    """CapabilityBundle → MissionTask[] (bir tool = bir task, tartibli DAG)."""
    tasks: list[MissionTask] = []
    for i, tool_name in enumerate(bundle.tools):
        tasks.append(
            MissionTask(
                position=i,
                title=tool_name,
                tool=tool_name,
                depends_on=[i - 1] if i > 0 else [],
            )
        )
    return tasks


def _deadline_expired(mission: Mission, now: datetime) -> bool:
    return mission.deadline is not None and mission.deadline <= now


__all__ = [
    "CapabilityBundleLike",
    "CapabilityRegistryLike",
    "ContextDiscoveryEngineLike",
    "IllegalMissionTransitionError",
    "MemoryStoreLike",
    "Mission",
    "MissionEngine",
    "MissionError",
    "MissionNotFoundError",
    "MissionTask",
    "RecoveryEngineLike",
    "RelevantContextLike",
]
