"""AgentRepository testlari — agentlarni DB'da saqlash (gap-analysis #1).

`conftest.py`dagi `session` fixture'i orqali real (in-memory sqlite) DB'ga
yozadi/o'qiydi — Agent Factory orqali yaratilgan agentlar restart'dan
keyin ham tiklanishini tekshiradi.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.agents.repository import AgentRepository
from zet.domain.agent import AgentSpec, AgentState
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, TrustLevel


def _make_state(name: str = "test-agent", status: AgentStatus = AgentStatus.DRAFT) -> AgentState:
    spec = AgentSpec(
        name=name,
        description="Test agent",
        system_prompt="Sen test agentisan.",
        division="ops",
        role="tester",
        goal="Testlarni o'tkazish",
        tool_allowlist=["web.search"],
        model_policy=ModelTier.T1_FREE,
        permission_level=PermissionLevel.READ,
        trust_level=TrustLevel.SYSTEM,
        max_steps=5,
        max_tool_calls=10,
        timeout_s=60,
    )
    return AgentState(spec=spec, status=status, total_runs=3, successful_runs=2, failed_runs=1)


@pytest.fixture
def repo(session: AsyncSession) -> AgentRepository:
    return AgentRepository(session)


class TestSave:
    async def test_save_creates_new_row(self, repo: AgentRepository) -> None:
        state = _make_state()
        await repo.save(state)

        loaded = await repo.get("test-agent")
        assert loaded is not None
        assert loaded.spec.name == "test-agent"
        assert loaded.spec.description == "Test agent"
        assert loaded.status == AgentStatus.DRAFT
        assert loaded.total_runs == 3
        assert loaded.successful_runs == 2
        assert loaded.failed_runs == 1

    async def test_save_preserves_tool_allowlist(self, repo: AgentRepository) -> None:
        state = _make_state()
        await repo.save(state)

        loaded = await repo.get("test-agent")
        assert loaded is not None
        assert loaded.spec.tool_allowlist == ["web.search"]

    async def test_save_updates_existing_row(self, repo: AgentRepository) -> None:
        state = _make_state(status=AgentStatus.DRAFT)
        await repo.save(state)

        updated = _make_state(status=AgentStatus.ACTIVE)
        updated = updated.model_copy(update={"total_runs": 7})
        await repo.save(updated)

        loaded = await repo.get("test-agent")
        assert loaded is not None
        assert loaded.status == AgentStatus.ACTIVE
        assert loaded.total_runs == 7

    async def test_save_assigns_db_id(self, repo: AgentRepository) -> None:
        state = _make_state()
        await repo.save(state)

        loaded = await repo.get("test-agent")
        assert loaded is not None
        assert loaded.id != ""


class TestGet:
    async def test_get_missing_returns_none(self, repo: AgentRepository) -> None:
        assert await repo.get("no-such-agent") is None


class TestLoadAll:
    async def test_load_all_returns_saved_agents(self, repo: AgentRepository) -> None:
        await repo.save(_make_state(name="agent-a"))
        await repo.save(_make_state(name="agent-b"))

        loaded = await repo.load_all()
        names = {state.spec.name for state in loaded}
        assert names == {"agent-a", "agent-b"}

    async def test_load_all_empty_when_nothing_saved(self, repo: AgentRepository) -> None:
        assert await repo.load_all() == []
