"""Bo'lim 3 — Agent CLI testlari.

Tekshiriladi:
    - z agent list
    - z agent register
    - z agent info
    - z agent status (lifecycle o'tishlari)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from zet.agents.registry import AgentRegistry
from zet.cli import app
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus

runner = CliRunner()


@pytest.fixture()
def registry() -> AgentRegistry:
    """Har bir test uchun yangi registry."""
    return AgentRegistry()


@pytest.fixture(autouse=True)
def _patch_registry(registry: AgentRegistry) -> object:
    """get_agent_registry ni patch qilish."""
    with patch("zet.api.deps.get_agent_registry", return_value=registry) as p:
        yield p


def _register_agent(registry: AgentRegistry, name: str = "test_agent", **kwargs: object) -> None:
    """Test uchun agent ro'yxatga olish."""
    spec = AgentSpec(
        name=name,
        description=kwargs.get("description", "Test agent"),  # type: ignore[arg-type]
        system_prompt=kwargs.get("system_prompt", "Sen test agentisan."),  # type: ignore[arg-type]
        division=kwargs.get("division", "general"),  # type: ignore[arg-type]
        role=kwargs.get("role", "assistant"),  # type: ignore[arg-type]
    )
    status = kwargs.get("status", AgentStatus.DRAFT)
    registry.register(spec, status=status)  # type: ignore[arg-type]


class TestAgentList:
    def test_list_empty(self, registry: AgentRegistry) -> None:
        """Bo'sh ro'yxat."""
        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "topilmadi" in result.output

    def test_list_agents(self, registry: AgentRegistry) -> None:
        """Agentlar ro'yxati."""
        _register_agent(registry, "agent1")
        _register_agent(registry, "agent2", status=AgentStatus.ACTIVE)

        result = runner.invoke(app, ["agent", "list"])
        assert result.exit_code == 0
        assert "agent1" in result.output
        assert "agent2" in result.output

    def test_list_with_status_filter(self, registry: AgentRegistry) -> None:
        """Status filtri."""
        _register_agent(registry, "a1")
        _register_agent(registry, "a2", status=AgentStatus.ACTIVE)

        result = runner.invoke(app, ["agent", "list", "--status", "active"])
        assert result.exit_code == 0
        assert "a2" in result.output
        # a1 is draft, should not appear in filtered output
        # (table might not be shown if we filter to only active)

    def test_list_invalid_status(self, registry: AgentRegistry) -> None:
        """Noto'g'ri status → xato."""
        result = runner.invoke(app, ["agent", "list", "--status", "invalid"])
        assert result.exit_code == 1


class TestAgentRegister:
    def test_register_success(self, registry: AgentRegistry) -> None:
        """Agent ro'yxatga olish."""
        result = runner.invoke(
            app,
            [
                "agent",
                "register",
                "my_agent",
                "--desc",
                "Test agent",
                "--prompt",
                "Sen agentsan.",
            ],
        )
        assert result.exit_code == 0
        assert "ro'yxatga olindi" in result.output
        assert "my_agent" in result.output
        assert registry.has("my_agent")

    def test_register_with_options(self, registry: AgentRegistry) -> None:
        """Qo'shimcha parametrlar bilan."""
        result = runner.invoke(
            app,
            [
                "agent",
                "register",
                "ops_agent",
                "--desc",
                "Ops agent",
                "--prompt",
                "Sen ops agentsan.",
                "--division",
                "ops",
                "--role",
                "analyst",
            ],
        )
        assert result.exit_code == 0
        state = registry.get("ops_agent")
        assert state.spec.division == "ops"
        assert state.spec.role == "analyst"

    def test_register_duplicate(self, registry: AgentRegistry) -> None:
        """Duplikat → xato."""
        _register_agent(registry, "dup_agent")
        result = runner.invoke(
            app,
            [
                "agent",
                "register",
                "dup_agent",
                "--desc",
                "Dup",
                "--prompt",
                "Test.",
            ],
        )
        assert result.exit_code == 1


class TestAgentInfo:
    def test_info_success(self, registry: AgentRegistry) -> None:
        """Agent ma'lumotlari."""
        _register_agent(registry, "info_agent", description="Info test")
        result = runner.invoke(app, ["agent", "info", "info_agent"])
        assert result.exit_code == 0
        assert "info_agent" in result.output

    def test_info_not_found(self, registry: AgentRegistry) -> None:
        """Mavjud emas → xato."""
        result = runner.invoke(app, ["agent", "info", "nonexistent"])
        assert result.exit_code == 1
        assert "topilmadi" in result.output


class TestAgentStatusCLI:
    def test_start_testing(self, registry: AgentRegistry) -> None:
        """DRAFT → TESTING."""
        _register_agent(registry, "lc_agent")
        result = runner.invoke(app, ["agent", "status", "lc_agent", "start_testing"])
        assert result.exit_code == 0
        assert "testing" in result.output

    def test_full_lifecycle(self, registry: AgentRegistry) -> None:
        """DRAFT → TESTING → ACTIVE → PAUSED → ACTIVE."""
        _register_agent(registry, "lc_agent")

        result = runner.invoke(app, ["agent", "status", "lc_agent", "start_testing"])
        assert result.exit_code == 0

        result = runner.invoke(app, ["agent", "status", "lc_agent", "activate"])
        assert result.exit_code == 0
        assert "active" in result.output

        result = runner.invoke(app, ["agent", "status", "lc_agent", "pause"])
        assert result.exit_code == 0
        assert "paused" in result.output

        result = runner.invoke(app, ["agent", "status", "lc_agent", "activate"])
        assert result.exit_code == 0

    def test_invalid_transition(self, registry: AgentRegistry) -> None:
        """DRAFT → ACTIVE → xato."""
        _register_agent(registry, "lc_agent")
        result = runner.invoke(app, ["agent", "status", "lc_agent", "activate"])
        assert result.exit_code == 1
        assert "xatosi" in result.output.lower() or "Lifecycle" in result.output

    def test_invalid_action(self, registry: AgentRegistry) -> None:
        """Noto'g'ri amal."""
        _register_agent(registry, "lc_agent")
        result = runner.invoke(app, ["agent", "status", "lc_agent", "explode"])
        assert result.exit_code == 1

    def test_not_found(self, registry: AgentRegistry) -> None:
        """Mavjud emas → xato."""
        result = runner.invoke(app, ["agent", "status", "nonexistent", "activate"])
        assert result.exit_code == 1
        assert "topilmadi" in result.output
