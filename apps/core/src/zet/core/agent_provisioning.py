"""Capability Gap → Agent Factory provisioning (JB-6).

NEGA bu qatlam kerak. `TaskGraphExecutor` (JB-5) allaqachon "mos ACTIVE
agent topilmadi" holatini `CapabilityGap` sifatida aniqlaydi — lekin hech
narsa uni TUZATISHGA harakat qilmasdi, gap faqat hisobotga yozilardi.
Boshqa tarafdan, `AgentFactory`/`AgentLifecycle`/`AgentRepository`
(Bo'lim 3-4, 12) — agent yaratish, sinov (Eval), lifecycle va DB
persistensiya uchun TO'LIQ, sinovdan o'tgan pipeline — allaqachon mavjud,
lekin `CapabilityGap`ga HECH QACHON ulanmagan edi (faqat
`POST /api/v1/agents/factory` orqali qo'lda chaqirilardi).

Bu modul ikkalasini BOG'LAYDI — AgentFactory/AgentLifecycle/AgentRepository
QAYTA YOZILMAYDI, faqat quyidagi siyosat va muvofiqlashtirish qatlami
qo'shiladi:

    CapabilityGap → risk siyosati → AgentFactory.create() → (ixtiyoriy
    DB persist) → AgentSelector qayta tekshiruvi → natija

Xavfsizlik (JB-6 spetsifikatsiyasi §10, §18):
    - Killswitch yoqilgan bo'lsa — provisioning DARHOL rad etiladi
      (`/api/v1/agents/factory` bilan bir xil qoida).
    - Risk darajasiga qarab siyosat: LOW → avtomatik yaratish+faollashtirish
      mumkin; MEDIUM → agent yaratiladi, lekin ACTIVE emas (inson
      `PATCH /agents/{name}/status {activate}` orqali tasdiqlashi kerak);
      HIGH/CRITICAL → provisioning UMUMAN rad etiladi (hech qanday
      siyosat/sozlama buni avtomatik chetlab o'ta olmaydi).
    - LLM (agar `AgentFactory` kelajakda LLM ishlatadigan bo'lsa) chiqishi
      HAR DOIM `EvalRunner` orqali (spec/tool/permission/prompt/brake
      validatsiyasi) o'tadi — bu allaqachon `AgentFactory.create()`
      ichida majburiy bosqich, bu yerda qayta yozilmaydi.

Reuse-before-create + race xavfsizlik (JB-6 §7, §8, §24, §25):
    Bir vaqtda bir nechta task (parallel batch) BIR XIL yo'q tool haqida
    gap xabar qilishi mumkin. Har tool nomi uchun `asyncio.Lock` bilan
    provisioning serializatsiya qilinadi; qulf ichida — avval yana bir
    marta `AgentSelector` bilan tekshiriladi (boshqa task allaqachon shu
    tool uchun agent yaratgan bo'lishi mumkin — double-checked locking),
    so'ng natija shu `AgentProvisioningService` obyekti umrida (bitta
    mission/so'rov davomida — `deps.py` har so'rov uchun yangi obyekt
    quradi) keshlanadi — ikkinchi so'rov Factory'ni QAYTA chaqirmaydi.

Bog'liq qarorlar:
    V-10 — Agent Factory oqimi (qayta ishlatilmoqda, o'zgartirilmagan)
    V-11 — lifecycle avtomati (qayta ishlatilmoqda)
    V-32 — majburiy tasdiq (yuqori risk uchun avtomatik yaratish yo'q)
    V-33 — favqulodda to'xtatish (killswitch provisioning'ni ham bloklaydi)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from zet.agents.factory import AgentFactory, FactoryRequest
from zet.agents.lifecycle import AgentLifecycle
from zet.core.agent_selector import AgentSelector
from zet.domain.enums import RiskLevel

if TYPE_CHECKING:
    from zet.agents.registry import AgentRegistry
    from zet.agents.repository import AgentRepository
    from zet.core.task_graph import CapabilityGap
    from zet.security.killswitch import KillSwitchState

log = structlog.get_logger(__name__)


class ProvisioningPolicyDecision(StrEnum):
    """`AgentProvisioningPolicy.decide()` natijasi (JB-6 spetsifikatsiyasi §10)."""

    AUTO_CREATE = "auto_create"
    """Risk yetarlicha past — agent yaratiladi VA (eval o'tsa) faollashtiriladi."""

    REQUIRE_APPROVAL = "require_approval"
    """Agent yaratiladi (eval qilinadi), lekin ACTIVE qilinmaydi — inson
    `PATCH /agents/{name}/status {activate}` orqali tasdiqlashi kerak."""

    DISABLED = "disabled"
    """Provisioning UMUMAN rad etiladi — hech qanday agent yaratilmaydi."""


@dataclass(frozen=True, slots=True)
class AgentProvisioningPolicy:
    """Risk darajasiga qarab avtomatik-yaratish/tasdiq/taqiq qarori.

    Default: LOW → avtomatik, MEDIUM → tasdiq kerak, HIGH/CRITICAL →
    taqiqlangan. Bu — JB-6 spetsifikatsiyasining §10 talabi so'zma-so'z:
    "LOW_RISK: auto-create allowed. HIGH_RISK: human approval required
    [bu yerda qattiqroq — provisioning umuman rad etiladi, faqat qo'lda
    `/agents` yoki `/agents/factory` orqali yaratish mumkin].
    SECURITY/FINANCE/DESTRUCTIVE: never auto-create without explicit
    policy."
    """

    auto_create_max_risk: RiskLevel = RiskLevel.LOW
    """Bu darajagacha (shu bilan birga) — avtomatik yaratish+faollashtirish."""

    disabled_min_risk: RiskLevel = RiskLevel.HIGH
    """Bu darajadan boshlab (shu bilan birga) — provisioning taqiqlangan."""

    def decide(self, risk: RiskLevel) -> ProvisioningPolicyDecision:
        if risk.rank >= self.disabled_min_risk.rank:
            return ProvisioningPolicyDecision.DISABLED
        if risk.rank <= self.auto_create_max_risk.rank:
            return ProvisioningPolicyDecision.AUTO_CREATE
        return ProvisioningPolicyDecision.REQUIRE_APPROVAL


@dataclass(frozen=True, slots=True)
class ProvisioningOutcome:
    """`AgentProvisioningService.provision()` natijasi."""

    activated_agent: str | None
    """Yangi (yoki reuse qilingan) ACTIVE agent nomi — faollashtirilmagan
    bo'lsa `None` (task_graph.py buni "hali hal qilinmadi" deb o'qiydi)."""

    decision: ProvisioningPolicyDecision
    reason: str
    factory_steps: list[str] = field(default_factory=list)
    """`FactoryResult.steps` — auditlik uchun to'liq pipeline izi."""

    reused_existing: bool = False
    """`True` — boshqa task allaqachon shu tool uchun agent yaratgan/
    faollashtirgan edi, Factory UMUMAN chaqirilmadi (reuse-before-create)."""


class AgentProvisioningService:
    """`CapabilityGap` → siyosat → `AgentFactory` → (DB persist) → natija."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        agent_repository: AgentRepository | None = None,
        killswitch: KillSwitchState | None = None,
        policy: AgentProvisioningPolicy | None = None,
    ) -> None:
        self._registry = agent_registry
        self._repo = agent_repository
        self._killswitch = killswitch
        self._policy = policy or AgentProvisioningPolicy()
        self._lifecycle = AgentLifecycle(agent_registry)
        self._factory = AgentFactory(agent_registry, self._lifecycle)
        # `AgentSelector`ning `_AgentRegistryLike` protokoli `list_agents`
        # parametrini `status: object | None` deb e'lon qiladi (kontravariant
        # talab) — haqiqiy `AgentRegistry.list_agents(status: AgentStatus
        # | None)` mypy nazarida "torroq" ko'rinadi, garchi runtime'da
        # to'liq mos kelsa ham (`mission_orchestrator.py`da xuddi shu
        # chaqiruv `Any` orqali yashiringan, bu yerda `AgentRegistry`
        # ataylab aniq tip sifatida saqlangan).
        self._selector = AgentSelector(agent_registry)  # type: ignore[arg-type]
        # NEGA tool nomiga qulflangan (global emas): ikkita TURLI tool
        # uchun gap bir vaqtda mustaqil provisioning qilinishi mumkin
        # (parallelism yo'qotilmasin), faqat BIR XIL tool serializatsiya
        # qilinadi (dublikat yaratishning oldini olish uchun yetarli).
        self._locks: dict[str, asyncio.Lock] = {}
        self._cache: dict[str, ProvisioningOutcome] = {}

    async def provision(self, gap: CapabilityGap) -> ProvisioningOutcome:
        """Gapni hal qilishga urinadi — reuse-before-create, keyin Factory.

        Bir `AgentProvisioningService` obyekti umri davomida (odatda bitta
        so'rov/mission — `deps.py` har safar yangisini quradi) bir xil
        tool uchun Factory FAQAT BIR MARTA chaqiriladi — keyingi
        so'rovlar keshlangan natijani oladi.
        """
        lock = self._locks.setdefault(gap.tool, asyncio.Lock())
        async with lock:
            cached = self._cache.get(gap.tool)
            if cached is not None:
                return cached

            outcome = await self._provision_locked(gap)
            self._cache[gap.tool] = outcome
            return outcome

    async def _provision_locked(self, gap: CapabilityGap) -> ProvisioningOutcome:
        # 0. Double-check — qulfni kutayotganda BOSHQA task shu tool
        # uchun agentni allaqachon yaratgan/faollashtirgan bo'lishi mumkin.
        existing = self._selector.rank_for_tools([gap.tool])
        if existing:
            log.info(
                "agent_provisioning.reused_existing",
                tool=gap.tool,
                agent=existing[0].agent_name,
            )
            return ProvisioningOutcome(
                activated_agent=existing[0].agent_name,
                decision=ProvisioningPolicyDecision.AUTO_CREATE,
                reason="allaqachon mos ACTIVE agent topildi (reuse-before-create)",
                reused_existing=True,
            )

        # 1. Killswitch — favqulodda to'xtatishda yangi agent yaratilmaydi
        # (V-33, `/api/v1/agents/factory` bilan bir xil qoida).
        if self._killswitch is not None and self._killswitch.is_engaged:
            log.warning("agent_provisioning.killswitch_engaged", tool=gap.tool)
            return ProvisioningOutcome(
                activated_agent=None,
                decision=ProvisioningPolicyDecision.DISABLED,
                reason="killswitch yoqilgan — yangi agent yaratish taqiqlangan",
            )

        # 2. Siyosat qarori — risk darajasiga qarab.
        decision = self._policy.decide(gap.risk_level)
        log.info(
            "agent_provisioning.policy_decided",
            tool=gap.tool,
            risk=gap.risk_level.value,
            decision=decision.value,
        )
        if decision == ProvisioningPolicyDecision.DISABLED:
            return ProvisioningOutcome(
                activated_agent=None,
                decision=decision,
                reason=(
                    f"siyosat: {gap.risk_level.value} risk uchun avtomatik "
                    "agent yaratish TAQIQLANGAN (faqat qo'lda /agents/factory orqali)"
                ),
            )

        # 3. Factory — mavjud, sinovdan o'tgan pipeline (o'zgartirilmagan).
        objective = gap.context.get("mission_objective", "") if gap.context else ""
        description = (
            f"{gap.suggested_role or gap.tool}: {gap.tool} toolidan foydalana oladigan agent. "
            f"Sabab: {gap.reason}. Missiya konteksti: {objective}"[:2000]
        )
        factory_request = FactoryRequest(
            description=description,
            auto_activate=(decision == ProvisioningPolicyDecision.AUTO_CREATE),
            required_tools=list(gap.required_tools or [gap.tool]),
        )
        result = self._factory.create(factory_request)

        if result.agent_state is not None and self._repo is not None:
            try:
                await self._repo.save(result.agent_state)
            except Exception:
                # Fail-open (JB-1/JB-4 bilan bir xil naqsh): persistensiya
                # ixtiyoriy qulaylik — DB yetib bo'lmasa ham registry'dagi
                # agent ishlashda davom etadi, faqat restart'da yo'qoladi.
                log.warning("agent_provisioning.persist_failed", tool=gap.tool, agent=gap.tool)

        if not result.success or result.agent_state is None:
            log.warning(
                "agent_provisioning.factory_failed",
                tool=gap.tool,
                error=result.error,
                steps=result.steps,
            )
            return ProvisioningOutcome(
                activated_agent=None,
                decision=decision,
                reason=result.error or "factory muvaffaqiyatsiz",
                factory_steps=list(result.steps),
            )

        activated = (
            result.agent_state.spec.name if result.agent_state.status.is_active else None
        )
        log.info(
            "agent_provisioning.completed",
            tool=gap.tool,
            agent=result.agent_state.spec.name,
            status=result.agent_state.status.value,
            activated=activated is not None,
        )
        return ProvisioningOutcome(
            activated_agent=activated,
            decision=decision,
            reason=(
                "agent yaratildi va faollashtirildi"
                if activated
                else (
                    f"agent '{result.agent_state.spec.name}' yaratildi, lekin "
                    f"{result.agent_state.status.value} holatda — inson tasdig'ini "
                    "kutmoqda (avtomatik faollashtirilmadi)"
                )
            ),
            factory_steps=list(result.steps),
        )


__all__ = [
    "AgentProvisioningPolicy",
    "AgentProvisioningService",
    "ProvisioningOutcome",
    "ProvisioningPolicyDecision",
]
