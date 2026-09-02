"""Bo'lim 3 — Agent Registry va Lifecycle testlari.

Tekshiriladi:
    - AgentRegistry: ro'yxatga olish, topish, yangilash
    - AgentLifecycle: V-11 holat o'tishlari
    - Metrics: run qayd qilish
"""

from __future__ import annotations

import pytest

from zet.agents.lifecycle import AgentLifecycle, AgentLifecycleError
from zet.agents.registry import AgentNotActiveError, AgentNotFoundError, AgentRegistry
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus


def _make_spec(name: str = "test_agent") -> AgentSpec:
    return AgentSpec(
        name=name,
        description="Test uchun agent",
        system_prompt="Sen test agentisan.",
        tool_allowlist=["time.now"],
    )


class TestAgentRegistry:
    def test_register(self) -> None:
        reg = AgentRegistry()
        state = reg.register(_make_spec())
        assert state.status == AgentStatus.DRAFT
        assert reg.count == 1

    def test_register_duplicate(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        with pytest.raises(ValueError, match="allaqachon"):
            reg.register(_make_spec())

    def test_get(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec("my_agent"))
        state = reg.get("my_agent")
        assert state.spec.name == "my_agent"

    def test_get_not_found(self) -> None:
        reg = AgentRegistry()
        with pytest.raises(AgentNotFoundError):
            reg.get("nonexistent")

    def test_get_active_not_active(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        with pytest.raises(AgentNotActiveError):
            reg.get_active("test_agent")

    def test_get_active_success(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        state = reg.get_active("test_agent")
        assert state.status == AgentStatus.ACTIVE

    def test_has(self) -> None:
        reg = AgentRegistry()
        assert not reg.has("test_agent")
        reg.register(_make_spec())
        assert reg.has("test_agent")

    def test_list_agents(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec("a1"))
        reg.register(_make_spec("a2"), status=AgentStatus.ACTIVE)
        reg.register(_make_spec("a3"))

        all_agents = reg.list_agents()
        assert len(all_agents) == 3

        active_agents = reg.list_agents(status=AgentStatus.ACTIVE)
        assert len(active_agents) == 1
        assert active_agents[0].spec.name == "a2"

    def test_update_status(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        updated = reg.update_status("test_agent", AgentStatus.TESTING)
        assert updated.status == AgentStatus.TESTING

    def test_update_status_invalid(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        with pytest.raises(ValueError, match="mumkin emas"):
            reg.update_status("test_agent", AgentStatus.ACTIVE)

    def test_record_run_success(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        reg.record_run("test_agent", success=True, tool_calls=3)
        state = reg.get("test_agent")
        assert state.total_runs == 1
        assert state.successful_runs == 1
        assert state.failed_runs == 0
        assert state.total_tool_calls == 3

    def test_record_run_failure(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        reg.record_run("test_agent", success=False, tool_calls=1)
        state = reg.get("test_agent")
        assert state.total_runs == 1
        assert state.failed_runs == 1
        assert state.successful_runs == 0

    def test_record_multiple_runs(self) -> None:
        reg = AgentRegistry()
        reg.register(_make_spec())
        reg.record_run("test_agent", success=True, tool_calls=2)
        reg.record_run("test_agent", success=True, tool_calls=3)
        reg.record_run("test_agent", success=False, tool_calls=1)
        state = reg.get("test_agent")
        assert state.total_runs == 3
        assert state.successful_runs == 2
        assert state.failed_runs == 1
        assert state.total_tool_calls == 6


class TestAgentLifecycle:
    @pytest.fixture()
    def setup(self) -> tuple[AgentRegistry, AgentLifecycle]:
        reg = AgentRegistry()
        lc = AgentLifecycle(reg)
        return reg, lc

    def test_start_testing(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec())
        state = lc.start_testing("test_agent")
        assert state.status == AgentStatus.TESTING

    def test_start_testing_not_draft(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        with pytest.raises(AgentLifecycleError, match="TESTING"):
            lc.start_testing("test_agent")

    def test_activate_from_testing(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec())
        lc.start_testing("test_agent")
        state = lc.activate("test_agent")
        assert state.status == AgentStatus.ACTIVE

    def test_activate_from_paused(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        lc.pause("test_agent")
        state = lc.activate("test_agent")
        assert state.status == AgentStatus.ACTIVE

    def test_activate_from_draft_blocked(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec())
        with pytest.raises(AgentLifecycleError):
            lc.activate("test_agent")

    def test_pause(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        state = lc.pause("test_agent")
        assert state.status == AgentStatus.PAUSED

    def test_pause_not_active(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec())
        with pytest.raises(AgentLifecycleError):
            lc.pause("test_agent")

    def test_disable(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        state = lc.disable("test_agent", reason="xato topildi")
        assert state.status == AgentStatus.DISABLED

    def test_disable_from_draft_blocked(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec())
        with pytest.raises(AgentLifecycleError):
            lc.disable("test_agent")

    def test_archive(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        state = lc.archive("test_agent")
        assert state.status == AgentStatus.ARCHIVED

    def test_archive_already_archived(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        lc.archive("test_agent")
        with pytest.raises(AgentLifecycleError, match="allaqachon"):
            lc.archive("test_agent")

    def test_reset_to_draft(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        lc.disable("test_agent")
        state = lc.reset_to_draft("test_agent")
        assert state.status == AgentStatus.DRAFT

    def test_reset_not_disabled(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        reg, lc = setup
        reg.register(_make_spec(), status=AgentStatus.ACTIVE)
        with pytest.raises(AgentLifecycleError):
            lc.reset_to_draft("test_agent")

    def test_full_lifecycle(self, setup: tuple[AgentRegistry, AgentLifecycle]) -> None:
        """To'liq hayot sikli: DRAFT → TESTING → ACTIVE → PAUSED → ACTIVE → ARCHIVED."""
        reg, lc = setup
        reg.register(_make_spec())

        state = lc.start_testing("test_agent")
        assert state.status == AgentStatus.TESTING

        state = lc.activate("test_agent")
        assert state.status == AgentStatus.ACTIVE

        state = lc.pause("test_agent")
        assert state.status == AgentStatus.PAUSED

        state = lc.activate("test_agent")
        assert state.status == AgentStatus.ACTIVE

        state = lc.archive("test_agent")
        assert state.status == AgentStatus.ARCHIVED
