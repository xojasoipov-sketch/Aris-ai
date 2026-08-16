"""Capability → real AgentRegistry → Mission Task Graph zanjiri (JB-4).

Audit topilmasi: `CapabilityRegistry.resolve()` capability'ning STATIK
`default_agents`ini hech qanday tekshiruvsiz qaytarardi (hujjatning o'zi
"AgentRegistry'da TEKSHIRILADIGAN" deb yozgan bo'lsa-da — tekshiruv hech
qachon yozilmagan edi). `MissionTask.agent` esa HECH QACHON to'ldirilmasdi.

Bu testlar REAL `CapabilityRegistry` + REAL `AgentRegistry` bilan butun
zanjirni sinaydi: capability qidiruvidan Task Graph'gacha.
"""

from __future__ import annotations

from zet.agents.registry import AgentRegistry
from zet.core.capability import Capability, CapabilityRegistry
from zet.core.mission import _bundle_to_tasks
from zet.core.mission_orchestrator import CapabilityRegistryComposer
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, RiskLevel


def _agent_spec(name: str, *, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,
    )


def _capability_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(
        Capability(
            name="business_briefing",
            description="Kunlik biznes holatini yig'ib beradi",
            supported_outcomes=["daily_briefing"],
            actions=["research", "summarize"],
            default_agents=["operations"],
            default_tools=["task.list", "weather.now"],
            tags=["biznes", "hisobot"],
        )
    )
    reg.register(
        Capability(
            name="social_post",
            description="Ijtimoiy tarmoq posti tayyorlaydi",
            supported_outcomes=["publish_post"],
            actions=["draft", "publish"],
            default_agents=["smm"],
            default_tools=["note.write", "telegram.channel_post"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.HIGH,
            tags=["marketing"],
        )
    )
    return reg


class TestComposerWithRealAgentRegistry:
    def test_active_agent_is_assigned_per_tool(self) -> None:
        agents = AgentRegistry()
        agents.register(
            _agent_spec("operations", tools=["task.list", "weather.now"]),
            status=AgentStatus.ACTIVE,
        )
        composer = CapabilityRegistryComposer(_capability_registry(), agent_registry=agents)

        bundle = composer.compose("biznes hisobot bugun", {})

        assert bundle.tool_agents == {
            "task.list": "operations",
            "weather.now": "operations",
        }
        assert bundle.agents == ["operations"]

    def test_paused_default_agent_is_excluded_and_fallback_used(self) -> None:
        """Statik `default_agents` PAUSED bo'lsa — boshqa mos ACTIVE agent tanlanadi."""
        agents = AgentRegistry()
        agents.register(
            _agent_spec("smm", tools=["note.write", "telegram.channel_post"]),
            status=AgentStatus.PAUSED,
        )
        agents.register(
            _agent_spec("ceo", tools=["note.write", "telegram.channel_post"]),
            status=AgentStatus.ACTIVE,
        )
        composer = CapabilityRegistryComposer(_capability_registry(), agent_registry=agents)

        bundle = composer.compose("ijtimoiy tarmoq post marketing", {})

        # `smm` (default) PAUSED — u endi Mission.agents'da "tanlangan"
        # bo'lib KO'RINMAYDI (ilgari ko'rinardi — statik copy-through edi).
        assert "smm" not in bundle.agents
        assert bundle.tool_agents.get("note.write") == "ceo"

    def test_no_active_agent_leaves_task_honestly_unassigned(self) -> None:
        """Hech qanday ACTIVE agent yo'q — `MissionTask.agent` o'ylab topilmaydi."""
        agents = AgentRegistry()  # bo'sh — hech kim ro'yxatda yo'q
        composer = CapabilityRegistryComposer(_capability_registry(), agent_registry=agents)

        bundle = composer.compose("biznes hisobot bugun", {})

        assert bundle.tool_agents == {}
        tasks = _bundle_to_tasks(bundle)
        assert all(t.agent is None for t in tasks)

    def test_without_agent_registry_behaves_like_before(self) -> None:
        """Backward-compat: `agent_registry` berilmasa — eski xatti-harakat."""
        composer = CapabilityRegistryComposer(_capability_registry())

        bundle = composer.compose("biznes hisobot bugun", {})

        assert bundle.tool_agents == {}
        assert bundle.agents == ["operations"]  # statik copy-through, o'zgarmagan


class TestBundleToTasksAgentAssignment:
    def test_task_agent_reflects_real_selection(self) -> None:
        agents = AgentRegistry()
        agents.register(
            _agent_spec("smm", tools=["note.write", "telegram.channel_post"]),
            status=AgentStatus.ACTIVE,
        )
        composer = CapabilityRegistryComposer(_capability_registry(), agent_registry=agents)

        bundle = composer.compose("ijtimoiy tarmoq post marketing", {})
        tasks = _bundle_to_tasks(bundle)

        by_tool = {t.tool: t.agent for t in tasks}
        assert by_tool["note.write"] == "smm"
        assert by_tool["telegram.channel_post"] == "smm"
