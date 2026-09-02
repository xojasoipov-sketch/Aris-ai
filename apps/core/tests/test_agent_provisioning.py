"""AgentProvisioningService testlari (JB-6).

Bu testlar `CapabilityGap → AgentFactory → AgentLifecycle` zanjirini
HAQIQIY komponentlar bilan sinaydi (mock emas) — faqat `AgentRepository`
(DB) soxta (session ochmasdan) berilgan, chunki persistensiya alohida
tekshiriladi (chaqirilgan-chaqirilmaganligi).
"""

from __future__ import annotations

import asyncio
import uuid

from zet.agents.registry import AgentRegistry
from zet.core.agent_provisioning import (
    AgentProvisioningPolicy,
    AgentProvisioningService,
    ProvisioningPolicyDecision,
)
from zet.core.task_graph import CapabilityGap, GapStatus
from zet.domain.agent import AgentSpec, AgentState
from zet.domain.enums import AgentStatus, ModelTier, RiskLevel


def _gap(
    tool: str,
    *,
    risk: RiskLevel = RiskLevel.LOW,
    required_tools: list[str] | None = None,
) -> CapabilityGap:
    return CapabilityGap(
        tool=tool,
        reason="mos ACTIVE agent topilmadi",
        mission_id=str(uuid.uuid4()),
        task_position=0,
        required_tools=required_tools if required_tools is not None else [tool],
        risk_level=risk,
        suggested_role=f"{tool.split('.')[0]}_specialist",
        context={"mission_objective": "test missiya"},
    )


class _FakeRepo:
    """`AgentRepository`ning minimal fake'i — chaqiruvlarni hisoblaydi."""

    def __init__(self) -> None:
        self.saved: list[AgentState] = []

    async def save(self, state: AgentState) -> None:
        self.saved.append(state)


class TestAgentProvisioningPolicy:
    def test_low_risk_auto_creates(self) -> None:
        policy = AgentProvisioningPolicy()
        assert policy.decide(RiskLevel.LOW) == ProvisioningPolicyDecision.AUTO_CREATE

    def test_medium_risk_requires_approval(self) -> None:
        policy = AgentProvisioningPolicy()
        assert policy.decide(RiskLevel.MEDIUM) == ProvisioningPolicyDecision.REQUIRE_APPROVAL

    def test_high_risk_disabled(self) -> None:
        policy = AgentProvisioningPolicy()
        assert policy.decide(RiskLevel.HIGH) == ProvisioningPolicyDecision.DISABLED

    def test_critical_risk_disabled(self) -> None:
        policy = AgentProvisioningPolicy()
        assert policy.decide(RiskLevel.CRITICAL) == ProvisioningPolicyDecision.DISABLED

    def test_custom_ceiling(self) -> None:
        """Sozlanadigan chegara — spec §10 talabi (configurable policy)."""
        policy = AgentProvisioningPolicy(
            auto_create_max_risk=RiskLevel.MEDIUM, disabled_min_risk=RiskLevel.CRITICAL
        )
        assert policy.decide(RiskLevel.MEDIUM) == ProvisioningPolicyDecision.AUTO_CREATE
        assert policy.decide(RiskLevel.HIGH) == ProvisioningPolicyDecision.REQUIRE_APPROVAL
        assert policy.decide(RiskLevel.CRITICAL) == ProvisioningPolicyDecision.DISABLED


class TestReuseBeforeCreate:
    async def test_existing_active_agent_is_reused_no_factory_call(self) -> None:
        registry = AgentRegistry()
        registry.register(
            AgentSpec(
                name="researcher",
                description="test",
                system_prompt="test",
                tool_allowlist=["web.search"],
                model_policy=ModelTier.T1_FREE,
            ),
            status=AgentStatus.ACTIVE,
        )
        service = AgentProvisioningService(agent_registry=registry)
        before_count = registry.count

        outcome = await service.provision(_gap("web.search"))

        assert outcome.activated_agent == "researcher"
        assert outcome.reused_existing is True
        assert registry.count == before_count  # Factory HECH QANDAY yangi agent yaratmadi


class TestAutoCreate:
    async def test_low_risk_creates_and_activates_with_requested_tool(self) -> None:
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        outcome = await service.provision(_gap("web.search", risk=RiskLevel.LOW))

        assert outcome.decision == ProvisioningPolicyDecision.AUTO_CREATE
        assert outcome.activated_agent is not None
        state = registry.get(outcome.activated_agent)
        assert state.status == AgentStatus.ACTIVE
        # ENG MUHIM DALIL: yangi agent AYNAN so'ralgan toolga ega —
        # faqat rol xaritasidan taxminiy tanlanmagan (JB-6 required_tools fix).
        assert "web.search" in state.spec.tool_allowlist

    async def test_persists_to_repository_on_success(self) -> None:
        registry = AgentRegistry()
        repo = _FakeRepo()
        service = AgentProvisioningService(agent_registry=registry, agent_repository=repo)  # type: ignore[arg-type]

        outcome = await service.provision(_gap("web.search"))

        assert outcome.activated_agent is not None
        assert len(repo.saved) == 1
        assert repo.saved[0].spec.name == outcome.activated_agent


class TestRequireApproval:
    async def test_medium_risk_creates_but_does_not_activate(self) -> None:
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        outcome = await service.provision(_gap("web.search", risk=RiskLevel.MEDIUM))

        assert outcome.decision == ProvisioningPolicyDecision.REQUIRE_APPROVAL
        assert outcome.activated_agent is None
        # Agent HAQIQATAN yaratildi (TESTING'da) — faqat faollashtirilmadi.
        assert registry.count == 1
        (state,) = registry.list_agents()
        assert state.status != AgentStatus.ACTIVE


class TestDisabledPolicy:
    async def test_high_risk_never_creates_agent(self) -> None:
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        outcome = await service.provision(_gap("shell.exec", risk=RiskLevel.HIGH))

        assert outcome.decision == ProvisioningPolicyDecision.DISABLED
        assert outcome.activated_agent is None
        assert registry.count == 0  # Hech qanday agent yaratilmadi

    async def test_killswitch_engaged_blocks_provisioning(self) -> None:
        class _FakeKillswitch:
            is_engaged = True

        registry = AgentRegistry()
        service = AgentProvisioningService(
            agent_registry=registry, killswitch=_FakeKillswitch()  # type: ignore[arg-type]
        )

        outcome = await service.provision(_gap("web.search", risk=RiskLevel.LOW))

        assert outcome.activated_agent is None
        assert outcome.decision == ProvisioningPolicyDecision.DISABLED
        assert registry.count == 0


class TestFactoryFailure:
    async def test_eval_failure_reported_honestly_not_silently_activated(self) -> None:
        """Noma'lum tool — Eval `tools_valid` rad etadi, agent ACTIVE bo'lmaydi."""
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        outcome = await service.provision(_gap("totally.unknown.tool_xyz", risk=RiskLevel.LOW))

        assert outcome.activated_agent is None
        assert outcome.decision == ProvisioningPolicyDecision.AUTO_CREATE
        assert outcome.factory_steps  # pipeline izi mavjud (auditlik)


class TestDuplicatePreventionAndConcurrency:
    async def test_second_call_same_tool_does_not_recreate(self) -> None:
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        first = await service.provision(_gap("web.search"))
        count_after_first = registry.count
        second = await service.provision(_gap("web.search"))

        assert second.activated_agent == first.activated_agent
        assert registry.count == count_after_first  # ikkinchi marta YARATILMADI

    async def test_concurrent_gaps_same_tool_create_only_one_agent(self) -> None:
        """Race-condition himoyasi: ikkita parallel task BIR XIL tool uchun
        bir vaqtda gap xabar qilsa — faqat BITTA agent yaratiladi."""
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        outcomes = await asyncio.gather(
            service.provision(_gap("web.search")),
            service.provision(_gap("web.search")),
            service.provision(_gap("web.search")),
        )

        activated_names = {o.activated_agent for o in outcomes}
        assert len(activated_names) == 1  # barchasi BIR XIL agentga keldi
        assert registry.count == 1  # faqat bitta agent yaratildi

    async def test_different_tools_provision_independently(self) -> None:
        """Turli tool'lar uchun gap'lar bir-birini bloklamaydi (faqat bir
        xil tool serializatsiya qilinadi, mustaqil tool'lar parallel).

        Ikkalasi ham READ-permission tool (`web.search`, `weather.now`) —
        `note.write` (WRITE) ataylab ishlatilmadi: "general" bo'limning
        default permission'i READ, `_design()` esa hozircha
        `required_tools`ning o'z kerakli permission darajasini avtomatik
        ko'tarmaydi (hujjatlashtirilgan cheklov, yakuniy hisobotga
        qarang) — WRITE tool bilan bu test eval'ning
        `permissions_valid` bosqichida (to'g'ri) rad etilardi."""
        registry = AgentRegistry()
        service = AgentProvisioningService(agent_registry=registry)

        outcomes = await asyncio.gather(
            service.provision(_gap("web.search")),
            service.provision(_gap("weather.now")),
        )

        assert all(o.activated_agent is not None for o in outcomes)
        assert registry.count == 2
        assert outcomes[0].activated_agent != outcomes[1].activated_agent


class TestGapStatusLifecycle:
    def test_default_status_is_detected(self) -> None:
        gap = _gap("web.search")
        assert gap.status == GapStatus.DETECTED

    def test_gap_is_mutable_for_status_tracking(self) -> None:
        gap = _gap("web.search")
        gap.status = GapStatus.ANALYZING
        assert gap.status == GapStatus.ANALYZING
