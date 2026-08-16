"""AgentSelector testlari (JB-4).

Audit topilmasi: "keyword-score composer tanlagan agentlar ijroga
ulanmagan o'lik metadata" — capability'ning STATIK `default_agents`
ro'yxati AgentRegistry'dagi HAQIQIY holatni (ACTIVE'mi, mavjudmi)
hech qachon tekshirmasdi. Bu testlar yangi qaror qatlamini qulflaydi:
faqat ACTIVE agent, faqat haqiqiy tool_allowlist qamrovi bo'yicha.
"""

from __future__ import annotations

from zet.core.agent_selector import AgentSelector
from zet.domain.agent import AgentSpec, AgentState
from zet.domain.enums import AgentStatus, ModelTier


def _spec(name: str, *, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,
    )


def _state(name: str, *, tools: list[str], status: AgentStatus = AgentStatus.ACTIVE) -> AgentState:
    return AgentState(spec=_spec(name, tools=tools), status=status)


class _FakeRegistry:
    def __init__(self, states: list[AgentState]) -> None:
        self._states = states

    def list_agents(self, *, status: AgentStatus | None = None) -> list[AgentState]:
        if status is None:
            return list(self._states)
        return [s for s in self._states if s.status == status]


class TestRankForTools:
    def test_only_active_agents_are_ranked(self) -> None:
        registry = _FakeRegistry(
            [
                _state("ceo", tools=["note.write"], status=AgentStatus.PAUSED),
                _state("smm", tools=["note.write"], status=AgentStatus.ACTIVE),
            ]
        )
        selector = AgentSelector(registry)

        ranking = selector.rank_for_tools(["note.write"])

        assert [m.agent_name for m in ranking] == ["smm"]

    def test_ranks_by_coverage_ratio_descending(self) -> None:
        registry = _FakeRegistry(
            [
                _state("narrow", tools=["web.search"]),
                _state("broad", tools=["web.search", "note.write"]),
            ]
        )
        selector = AgentSelector(registry)

        ranking = selector.rank_for_tools(["web.search", "note.write"])

        assert ranking[0].agent_name == "broad"
        assert ranking[0].coverage_ratio == 1.0
        assert ranking[1].agent_name == "narrow"
        assert ranking[1].coverage_ratio == 0.5

    def test_preferred_wins_tiebreak_at_equal_coverage(self) -> None:
        registry = _FakeRegistry(
            [
                _state("alpha", tools=["note.write"]),
                _state("beta", tools=["note.write"]),
            ]
        )
        selector = AgentSelector(registry)

        ranking = selector.rank_for_tools(["note.write"], preferred=["beta"])

        assert ranking[0].agent_name == "beta"

    def test_agent_with_zero_coverage_is_excluded(self) -> None:
        registry = _FakeRegistry([_state("unrelated", tools=["telegram.channel_post"])])
        selector = AgentSelector(registry)

        assert selector.rank_for_tools(["note.write"]) == []

    def test_empty_required_tools_returns_empty(self) -> None:
        registry = _FakeRegistry([_state("ceo", tools=["note.write"])])
        assert AgentSelector(registry).rank_for_tools([]) == []


class TestAssignToolAgents:
    def test_each_tool_gets_a_real_agent(self) -> None:
        registry = _FakeRegistry(
            [
                _state("research", tools=["web.search"]),
                _state("smm", tools=["note.write", "telegram.channel_post"]),
            ]
        )
        selector = AgentSelector(registry)

        result = selector.assign_tool_agents(["web.search", "note.write"])

        assert result.tool_agents == {"web.search": "research", "note.write": "smm"}
        assert result.unmatched_tools == ()

    def test_greedy_reuse_minimizes_agent_fragmentation(self) -> None:
        """Bitta agent bir nechta tool'ni qamrasa — vazifalar bo'linib ketmasin."""
        registry = _FakeRegistry(
            [
                _state("generalist", tools=["web.search", "note.write", "time.now"]),
                _state("specialist", tools=["note.write"]),
            ]
        )
        selector = AgentSelector(registry)

        result = selector.assign_tool_agents(["web.search", "note.write", "time.now"])

        # Generalist barcha uchtasini qamraydi — tanlov unga tushishi kerak,
        # 3 xil agent orasida bo'linmasligi kerak.
        assert set(result.tool_agents.values()) == {"generalist"}

    def test_honest_unmatched_tool_stays_unassigned(self) -> None:
        """Hech qanday ACTIVE agent qamrab ololmagan tool — halol holat."""
        registry = _FakeRegistry([_state("smm", tools=["note.write"])])
        selector = AgentSelector(registry)

        result = selector.assign_tool_agents(["note.write", "shell.exec"])

        assert result.tool_agents == {"note.write": "smm"}
        assert result.unmatched_tools == ("shell.exec",)

    def test_preferred_agent_that_is_paused_is_excluded_and_reported(self) -> None:
        """Statik default_agents PAUSED bo'lsa — chetlab o'tiladi, sabab loglanadi."""
        registry = _FakeRegistry(
            [
                _state("smm", tools=["note.write"], status=AgentStatus.PAUSED),
                _state("ceo", tools=["note.write"], status=AgentStatus.ACTIVE),
            ]
        )
        selector = AgentSelector(registry)

        result = selector.assign_tool_agents(["note.write"], preferred=["smm"])

        assert result.tool_agents == {"note.write": "ceo"}
        assert result.excluded_preferred == ("smm",)

    def test_no_active_agents_leaves_everything_unmatched(self) -> None:
        registry = _FakeRegistry([])
        selector = AgentSelector(registry)

        result = selector.assign_tool_agents(["note.write", "web.search"])

        assert result.tool_agents == {}
        assert set(result.unmatched_tools) == {"note.write", "web.search"}
        assert result.active_agents == ()

    def test_deterministic_across_calls(self) -> None:
        """Bir xil kirish — bir xil chiqish (barqaror, testlanadigan)."""
        registry = _FakeRegistry(
            [
                _state("a", tools=["note.write"]),
                _state("b", tools=["note.write"]),
            ]
        )
        selector = AgentSelector(registry)

        first = selector.assign_tool_agents(["note.write"])
        second = selector.assign_tool_agents(["note.write"])

        assert first.tool_agents == second.tool_agents


class TestFilterActive:
    def test_removes_inactive_and_unknown_names(self) -> None:
        registry = _FakeRegistry(
            [
                _state("ceo", tools=[], status=AgentStatus.ACTIVE),
                _state("smm", tools=[], status=AgentStatus.PAUSED),
            ]
        )
        selector = AgentSelector(registry)

        assert selector.filter_active(["ceo", "smm", "ghost"]) == ["ceo"]

    def test_preserves_order(self) -> None:
        registry = _FakeRegistry(
            [
                _state("a", tools=[]),
                _state("b", tools=[]),
            ]
        )
        selector = AgentSelector(registry)

        assert selector.filter_active(["b", "a"]) == ["b", "a"]
