"""deploy/bootstrap.py testlari — builtin agentlarni registry'ga qo'shish."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.agents.repository import AgentRepository
from zet.api.deps import get_agent_registry
from zet.deploy.bootstrap import bootstrap_agents, load_persisted_agents
from zet.domain.agent import AgentSpec, AgentState
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, TrustLevel


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


class TestLoadPersistedAgents:
    """DB'da saqlangan (Factory orqali yaratilgan) agentlarni qayta tiklash."""

    @pytest.fixture
    def factory_state(self) -> AgentState:
        spec = AgentSpec(
            name="persisted-agent",
            description="Factory orqali yaratilgan",
            system_prompt="Sen saqlangan agentisan.",
            model_policy=ModelTier.T1_FREE,
            permission_level=PermissionLevel.READ,
            trust_level=TrustLevel.SYSTEM,
        )
        return AgentState(spec=spec, status=AgentStatus.ACTIVE)

    async def test_reloads_agent_saved_in_db(
        self, session: AsyncSession, factory_state: AgentState
    ) -> None:
        await AgentRepository(session).save(factory_state)

        get_agent_registry.cache_clear()
        try:
            added = await load_persisted_agents(session)
            registry = get_agent_registry()
            assert added == 1
            assert registry.has("persisted-agent")
            assert registry.get("persisted-agent").status == AgentStatus.ACTIVE
        finally:
            get_agent_registry.cache_clear()

    async def test_skips_already_registered_agent(
        self, session: AsyncSession, factory_state: AgentState
    ) -> None:
        await AgentRepository(session).save(factory_state)

        get_agent_registry.cache_clear()
        try:
            registry = get_agent_registry()
            registry.register(factory_state.spec, status=AgentStatus.ACTIVE)

            added = await load_persisted_agents(session)
            assert added == 0
        finally:
            get_agent_registry.cache_clear()

    async def test_returns_zero_when_db_empty(self, session: AsyncSession) -> None:
        get_agent_registry.cache_clear()
        try:
            added = await load_persisted_agents(session)
            assert added == 0
        finally:
            get_agent_registry.cache_clear()

    async def test_fails_open_on_db_error(self) -> None:
        """DB sessiyasi ishlamasa ham 0 qaytaradi, xato ko'tarmaydi."""

        class _BrokenSession:
            async def execute(self, *_args: object, **_kwargs: object) -> None:
                msg = "DB ulanmagan"
                raise RuntimeError(msg)

        get_agent_registry.cache_clear()
        try:
            added = await load_persisted_agents(_BrokenSession())  # type: ignore[arg-type]
            assert added == 0
        finally:
            get_agent_registry.cache_clear()
