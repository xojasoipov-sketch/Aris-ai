"""Agent navbati (handoff) testlari — agentning 4-xususiyati.

Asosiy xavf — cheksiz zanjir. Testlarning yarmi aynan tormozlarni
(chuqurlik, tsikl, kill-switch) tekshiradi.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from zet.agents.registry import AgentRegistry
from zet.automation.engine import AutomationEngine
from zet.automation.handoff import (
    HANDOFF_EVENT_TYPE,
    MAX_OUTPUT_IN_EVENT,
    HandoffDispatcher,
    completion_event,
)
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType
from zet.domain.agent import AgentRunResult, AgentSpec
from zet.domain.enums import AgentStatus
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


def _spec(name: str) -> AgentSpec:
    return AgentSpec(name=name, description=f"{name} agenti", system_prompt="Sen ishchisan.")


def _result(agent: str, *, success: bool = True, output: str = "bajarildi") -> AgentRunResult:
    return AgentRunResult(agent_name=agent, success=success, output=output)


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    for name in ("research", "ceo", "ops"):
        reg.register(_spec(name), status=AgentStatus.ACTIVE)
    return reg


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


def _handoff_trigger(*, to_agent: str, after: str, only_success: bool = True) -> EventTrigger:
    """`after` agenti tugagach `to_agent`ni uyg'otadigan trigger."""
    conditions = [TriggerCondition(field="agent", operator="eq", value=after)]
    if only_success:
        conditions.append(TriggerCondition(field="success", operator="eq", value="true"))
    return EventTrigger(
        name=f"{after} → {to_agent}",
        trigger_type=TriggerType.AGENT_HANDOFF,
        agent_name=to_agent,
        conditions=conditions,
        command_template="Oldingi natija: {output}",
    )


def _dispatcher(
    engine: AutomationEngine,
    agent_registry: AgentRegistry,
    tool_registry: ToolRegistry,
    *,
    killswitch: KillSwitchState | None = None,
    max_depth: int = 5,
) -> HandoffDispatcher:
    return HandoffDispatcher(
        engine=engine,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        permission_policy=PermissionPolicy(),
        killswitch=killswitch,
        max_depth=max_depth,
    )


class TestCompletionEvent:
    """`agent.completed` hodisasining shakli."""

    def test_event_type_and_fields(self) -> None:
        event = completion_event("research", _result("research", output="hisobot"))
        assert event.event_type == HANDOFF_EVENT_TYPE
        assert event.data["agent"] == "research"
        assert event.data["success"] == "true"
        assert event.data["output"] == "hisobot"

    def test_failure_is_marked(self) -> None:
        result = AgentRunResult(agent_name="research", success=False, error="xato")
        event = completion_event("research", result)
        assert event.data["success"] == "false"
        assert event.data["error"] == "xato"

    def test_long_output_is_truncated(self) -> None:
        """Katta natija hodisani shishirmasin."""
        result = _result("research", output="x" * (MAX_OUTPUT_IN_EVENT + 500))
        event = completion_event("research", result)
        assert len(event.data["output"]) <= MAX_OUTPUT_IN_EVENT + 1


class TestDispatch:
    """Navbatning haqiqiy ishlashi."""

    async def test_next_agent_runs(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        engine = AutomationEngine()
        engine.add_trigger(_handoff_trigger(to_agent="ceo", after="research"))

        started = await _dispatcher(engine, agent_registry, tool_registry).dispatch(
            "research", _result("research")
        )

        assert started == ["ceo"]

    async def test_chain_of_three(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """research → ceo → ops, zanjirni qayta yozmasdan."""
        engine = AutomationEngine()
        engine.add_trigger(_handoff_trigger(to_agent="ceo", after="research"))
        engine.add_trigger(_handoff_trigger(to_agent="ops", after="ceo"))

        started = await _dispatcher(engine, agent_registry, tool_registry).dispatch(
            "research", _result("research")
        )

        assert started == ["ceo", "ops"]

    async def test_no_trigger_means_no_handoff(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        engine = AutomationEngine()
        started = await _dispatcher(engine, agent_registry, tool_registry).dispatch(
            "research", _result("research")
        )
        assert started == []

    async def test_failure_does_not_trigger_success_only_handoff(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        engine = AutomationEngine()
        engine.add_trigger(_handoff_trigger(to_agent="ceo", after="research"))

        failed = AgentRunResult(agent_name="research", success=False, error="yiqildi")
        started = await _dispatcher(engine, agent_registry, tool_registry).dispatch(
            "research", failed
        )

        assert started == []

    async def test_unavailable_next_agent_is_skipped(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """Keyingi agent yo'q — zanjir jim to'xtaydi, xato ko'tarilmaydi."""
        engine = AutomationEngine()
        engine.add_trigger(_handoff_trigger(to_agent="yoq-agent", after="research"))

        started = await _dispatcher(engine, agent_registry, tool_registry).dispatch(
            "research", _result("research")
        )

        assert started == []


class TestBrakes:
    """A-07 tormozlari — cheksiz zanjir bo'lmasligi kerak."""

    async def test_cycle_is_blocked(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """research → ceo → research: ikkinchi 'research' ishga TUSHMAYDI."""
        engine = AutomationEngine()
        engine.add_trigger(_handoff_trigger(to_agent="ceo", after="research"))
        engine.add_trigger(_handoff_trigger(to_agent="research", after="ceo"))

        started = await _dispatcher(engine, agent_registry, tool_registry).dispatch(
            "research", _result("research")
        )

        assert started == ["ceo"]
        assert started.count("research") == 0

    async def test_depth_limit_stops_long_chain(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """Har bir agent keyingisini chaqiradi — chuqurlik chegarasi ushlaydi."""
        reg = AgentRegistry()
        names = [f"a{i}" for i in range(8)]
        for name in names:
            reg.register(_spec(name), status=AgentStatus.ACTIVE)

        engine = AutomationEngine()
        for current, following in itertools.pairwise(names):
            engine.add_trigger(_handoff_trigger(to_agent=following, after=current))

        started = await _dispatcher(engine, reg, tool_registry, max_depth=3).dispatch(
            "a0", _result("a0")
        )

        assert len(started) == 3

    async def test_killswitch_stops_dispatch(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        engine = AutomationEngine()
        engine.add_trigger(_handoff_trigger(to_agent="ceo", after="research"))
        ks = KillSwitchState()
        ks.engage(reason="test", by="owner")

        started = await _dispatcher(engine, agent_registry, tool_registry, killswitch=ks).dispatch(
            "research", _result("research")
        )

        assert started == []
