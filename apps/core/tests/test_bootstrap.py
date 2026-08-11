"""deploy/bootstrap.py testlari — builtin agentlarni registry'ga qo'shish."""

from __future__ import annotations

from zet.api.deps import get_agent_registry
from zet.deploy.bootstrap import bootstrap_agents
from zet.domain.enums import AgentStatus


class TestBootstrapAgents:
    def test_registers_all_builtin_agents(self) -> None:
        get_agent_registry.cache_clear()
        try:
            count = bootstrap_agents()
            registry = get_agent_registry()
            assert count == 12
            assert len(registry.list_agents()) >= 12
        finally:
            get_agent_registry.cache_clear()

    def test_registered_as_active(self) -> None:
        get_agent_registry.cache_clear()
        try:
            bootstrap_agents()
            registry = get_agent_registry()
            state = registry.get("ceo")
            assert state.status == AgentStatus.ACTIVE
        finally:
            get_agent_registry.cache_clear()

    def test_idempotent(self) -> None:
        """Ikkinchi chaqiruv xato bermaydi (mavjud agentlarni qayta ro'yxatga olmaydi)."""
        get_agent_registry.cache_clear()
        try:
            bootstrap_agents()
            bootstrap_agents()  # xato bermasligi kerak
            registry = get_agent_registry()
            assert len(registry.list_agents()) == 12
        finally:
            get_agent_registry.cache_clear()
