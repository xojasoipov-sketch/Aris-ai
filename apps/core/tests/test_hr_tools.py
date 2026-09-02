"""HR workforce management tool testlari (yangi asosiy talab).

HR agent — ZET ekotizimidagi BOSHQA AI agentlarni boshqaradi:
pause/resume/disable + metrika + ro'yxat. Yangi agent yaratish
BU YERDA YO'Q — AgentFactory alohida.
"""

from __future__ import annotations

import pytest

from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.registry import AgentRegistry
from zet.domain.enums import AgentStatus
from zet.tools.builtin.hr_tools import (
    AgentDisableTool,
    AgentListTool,
    AgentPauseTool,
    AgentResumeTool,
    AgentStatsTool,
)


@pytest.fixture()
def registry_with_ceo() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(CEO_AGENT_SPEC, status=AgentStatus.ACTIVE)
    return reg


async def test_list_returns_all_agents(registry_with_ceo: AgentRegistry) -> None:
    result = await AgentListTool(registry=registry_with_ceo).execute({})
    assert result.success
    names = [a["name"] for a in result.output["agents"]]
    assert "ceo" in names


async def test_list_filters_by_status(registry_with_ceo: AgentRegistry) -> None:
    result = await AgentListTool(registry=registry_with_ceo).execute({"status": "active"})
    assert result.success
    assert all(a["status"] == "active" for a in result.output["agents"])


async def test_pause_then_resume(registry_with_ceo: AgentRegistry) -> None:
    pause = await AgentPauseTool(registry=registry_with_ceo).execute({"name": "ceo"})
    assert pause.success
    assert registry_with_ceo.get("ceo").status is AgentStatus.PAUSED

    resume = await AgentResumeTool(registry=registry_with_ceo).execute({"name": "ceo"})
    assert resume.success
    assert registry_with_ceo.get("ceo").status is AgentStatus.ACTIVE


async def test_disable_stops_agent(registry_with_ceo: AgentRegistry) -> None:
    result = await AgentDisableTool(registry=registry_with_ceo).execute({"name": "ceo"})
    assert result.success
    assert registry_with_ceo.get("ceo").status is AgentStatus.DISABLED


async def test_illegal_transition_returns_clear_error(registry_with_ceo: AgentRegistry) -> None:
    """DISABLED agent'ni to'g'ridan-to'g'ri ACTIVE'ga qaytarish mumkin emas."""
    await AgentDisableTool(registry=registry_with_ceo).execute({"name": "ceo"})
    result = await AgentResumeTool(registry=registry_with_ceo).execute({"name": "ceo"})
    assert result.success is False
    assert "ruxsat" in (result.error or "").lower() or "o'tish" in (result.error or "").lower()


async def test_stats_returns_metrics(registry_with_ceo: AgentRegistry) -> None:
    registry_with_ceo.record_run("ceo", success=True)
    registry_with_ceo.record_run("ceo", success=True)
    registry_with_ceo.record_run("ceo", success=False)

    result = await AgentStatsTool(registry=registry_with_ceo).execute({"name": "ceo"})
    assert result.success
    assert result.output["total_runs"] == 3
    assert result.output["successful_runs"] == 2
    assert abs(result.output["success_rate"] - 2 / 3) < 1e-6


async def test_no_registry_returns_clear_error() -> None:
    tool = AgentListTool(registry=None)
    assert tool.connected is False
    result = await tool.execute({})
    assert result.success is False
    assert "ulanmagan" in (result.error or "").lower()


async def test_registered_in_default_registry(tmp_path) -> None:
    from zet.tools.builtin import build_default_registry

    registry = build_default_registry(notes_dir=tmp_path)
    names = set(registry.tool_names())
    assert "agent.list" in names
    assert "agent.pause" in names
    assert "agent.resume" in names
    assert "agent.disable" in names
    assert "agent.stats" in names


def test_hr_spec_uses_workforce_tools() -> None:
    """HR agent spec workforce management tool'lariga o'tgan."""
    from zet.agents.builtin.hr import HR_AGENT_SPEC

    assert "agent.list" in HR_AGENT_SPEC.tool_allowlist
    assert "agent.pause" in HR_AGENT_SPEC.tool_allowlist
    assert "agent.stats" in HR_AGENT_SPEC.tool_allowlist
    # Eski inson-HR tool'lari o'chirilgan
    assert "web.search" not in HR_AGENT_SPEC.tool_allowlist


def test_hr_eval_passes() -> None:
    """Yangilangan HR spec eval'dan o'tadi."""
    from zet.agents.builtin.hr import HR_AGENT_SPEC
    from zet.agents.eval import EvalRunner

    result = EvalRunner().run_eval(HR_AGENT_SPEC)
    assert result.success, result.cases
