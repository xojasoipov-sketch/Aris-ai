"""Bo'lim 3 — Agent API testlari.

Tekshiriladi:
    - POST /api/v1/agents — agent yaratish
    - GET /api/v1/agents — ro'yxat
    - GET /api/v1/agents/{name} — ma'lumot olish
    - PATCH /api/v1/agents/{name}/status — lifecycle o'tishlari
    - POST /api/v1/agents/{name}/run — agentni ishga tushirish
    - Xato holatlar (404, 409, 422)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.agents.registry import AgentRegistry
from zet.api.app import create_app
from zet.api.deps import get_agent_registry, get_db_session, get_killswitch, get_llm_providers
from zet.domain.enums import ModelTier
from zet.llm.fake import FakeProvider
from zet.security.killswitch import KillSwitchState


@pytest.fixture()
def registry() -> AgentRegistry:
    """Har bir test uchun yangi registry."""
    return AgentRegistry()


@pytest.fixture()
def client(registry: AgentRegistry) -> TestClient:
    """FastAPI test client agent registry bilan."""
    app = create_app()
    app.dependency_overrides[get_agent_registry] = lambda: registry
    app.dependency_overrides[get_killswitch] = KillSwitchState
    return TestClient(app, raise_server_exceptions=False)


def _agent_payload(**overrides: object) -> dict:
    """Standart agent yaratish payload'i."""
    data: dict = {
        "name": "test_agent",
        "description": "Test uchun agent",
        "system_prompt": "Sen test agentisan.",
    }
    data.update(overrides)
    return data


class TestCreateAgent:
    def test_create_success(self, client: TestClient) -> None:
        """POST /agents → 201."""
        resp = client.post("/api/v1/agents", json=_agent_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test_agent"
        assert data["status"] == "draft"
        assert data["division"] == "general"
        assert data["role"] == "assistant"

    def test_create_with_all_fields(self, client: TestClient) -> None:
        """Barcha maydonlar bilan yaratish."""
        resp = client.post(
            "/api/v1/agents",
            json=_agent_payload(
                division="ops",
                role="researcher",
                goal="Qidirish",
                tool_allowlist=["web.search"],
                max_steps=5,
                max_tool_calls=10,
                timeout_s=60,
            ),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["division"] == "ops"
        assert data["role"] == "researcher"
        assert data["tool_allowlist"] == ["web.search"]
        assert data["max_steps"] == 5

    def test_create_duplicate(self, client: TestClient) -> None:
        """Duplikat nom → 409."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.post("/api/v1/agents", json=_agent_payload())
        assert resp.status_code == 409

    def test_create_empty_name(self, client: TestClient) -> None:
        """Bo'sh nom → 422."""
        resp = client.post("/api/v1/agents", json=_agent_payload(name=""))
        assert resp.status_code == 422

    def test_create_no_prompt(self, client: TestClient) -> None:
        """System prompt yo'q → 422."""
        payload = _agent_payload()
        del payload["system_prompt"]
        resp = client.post("/api/v1/agents", json=payload)
        assert resp.status_code == 422


class TestListAgents:
    def test_list_empty(self, client: TestClient) -> None:
        """Bo'sh ro'yxat → []."""
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_all(self, client: TestClient) -> None:
        """Bir nechta agent."""
        client.post("/api/v1/agents", json=_agent_payload(name="a1"))
        client.post("/api/v1/agents", json=_agent_payload(name="a2"))
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_with_status_filter(self, client: TestClient, registry: AgentRegistry) -> None:
        """Status filtri bilan."""
        from zet.domain.agent import AgentSpec
        from zet.domain.enums import AgentStatus

        registry.register(
            AgentSpec(name="a1", description="t", system_prompt="t"),
        )
        registry.register(
            AgentSpec(name="a2", description="t", system_prompt="t"),
            status=AgentStatus.ACTIVE,
        )

        resp = client.get("/api/v1/agents?status=active")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "a2"


class TestGetAgent:
    def test_get_existing(self, client: TestClient) -> None:
        """GET /agents/{name} → 200."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.get("/api/v1/agents/test_agent")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test_agent"

    def test_get_not_found(self, client: TestClient) -> None:
        """GET /agents/{name} mavjud emas → 404."""
        resp = client.get("/api/v1/agents/nonexistent")
        assert resp.status_code == 404

    def test_get_includes_metrics(self, client: TestClient, registry: AgentRegistry) -> None:
        """Metrikalar javobda bor."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.get("/api/v1/agents/test_agent")
        data = resp.json()
        assert data["total_runs"] == 0
        assert data["success_rate"] == 0.0
        assert data["total_tool_calls"] == 0


class TestAgentStatus:
    def test_start_testing(self, client: TestClient) -> None:
        """DRAFT → TESTING."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "start_testing"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "testing"

    def test_full_lifecycle(self, client: TestClient) -> None:
        """DRAFT → TESTING → ACTIVE → PAUSED → ACTIVE → ARCHIVED."""
        client.post("/api/v1/agents", json=_agent_payload())

        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "start_testing"},
        )
        assert resp.json()["status"] == "testing"

        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "activate"},
        )
        assert resp.json()["status"] == "active"

        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "pause"},
        )
        assert resp.json()["status"] == "paused"

        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "activate"},
        )
        assert resp.json()["status"] == "active"

        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "archive"},
        )
        assert resp.json()["status"] == "archived"

    def test_invalid_transition(self, client: TestClient) -> None:
        """DRAFT → ACTIVE to'g'ridan-to'g'ri → 409."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "activate"},
        )
        assert resp.status_code == 409

    def test_disable_with_reason(self, client: TestClient) -> None:
        """Disable sabab bilan."""
        client.post("/api/v1/agents", json=_agent_payload())
        client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "start_testing"},
        )
        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "disable", "reason": "Xato topildi"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disabled"

    def test_unknown_action(self, client: TestClient) -> None:
        """Noto'g'ri amal → 400."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "explode"},
        )
        assert resp.status_code == 400

    def test_not_found(self, client: TestClient) -> None:
        """Mavjud emas → 404."""
        resp = client.patch(
            "/api/v1/agents/nonexistent/status",
            json={"action": "activate"},
        )
        assert resp.status_code == 404


class TestAgentRun:
    """`run_agent` endi real `ModelRouter` orqali ishlaydi (RoutedLLMProvider).

    Shuning uchun bu klassning `client` fixture'i `get_db_session`ni
    (real in-memory sqlite `session` bilan) va `get_llm_providers`ni
    (haqiqiy tarmoqqa chiqmaydigan `FakeProvider` bilan, katalogdagi
    "google" nomi ostida — TaskClass.NORMAL'ning birinchi nomzodi)
    almashtiradi.
    """

    @pytest.fixture()
    def client(self, registry: AgentRegistry, session: AsyncSession) -> TestClient:
        app = create_app()

        async def _session_override():
            yield session

        app.dependency_overrides[get_agent_registry] = lambda: registry
        app.dependency_overrides[get_killswitch] = KillSwitchState
        app.dependency_overrides[get_db_session] = _session_override
        app.dependency_overrides[get_llm_providers] = lambda: {
            "google": FakeProvider(name="google", tier=ModelTier.T1_FREE)
        }
        return TestClient(app, raise_server_exceptions=False)

    def _create_active_agent(self, client: TestClient) -> None:
        """ACTIVE agent yaratish yordamchisi."""
        client.post("/api/v1/agents", json=_agent_payload())
        client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "start_testing"},
        )
        client.patch(
            "/api/v1/agents/test_agent/status",
            json={"action": "activate"},
        )

    def test_run_success(self, client: TestClient) -> None:
        """ACTIVE agent run → 200."""
        self._create_active_agent(client)
        resp = client.post(
            "/api/v1/agents/test_agent/run",
            json={"task": "Test vazifa"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "test_agent"
        assert data["success"]

    def test_run_not_active(self, client: TestClient) -> None:
        """DRAFT agent run → 409."""
        client.post("/api/v1/agents", json=_agent_payload())
        resp = client.post(
            "/api/v1/agents/test_agent/run",
            json={"task": "Test"},
        )
        assert resp.status_code == 409

    def test_run_not_found(self, client: TestClient) -> None:
        """Mavjud emas → 404."""
        resp = client.post(
            "/api/v1/agents/nonexistent/run",
            json={"task": "Test"},
        )
        assert resp.status_code == 404

    def test_run_updates_metrics(self, client: TestClient) -> None:
        """Run metrikalarni yangilaydi."""
        self._create_active_agent(client)
        client.post(
            "/api/v1/agents/test_agent/run",
            json={"task": "Birinchi vazifa"},
        )
        resp = client.get("/api/v1/agents/test_agent")
        data = resp.json()
        assert data["total_runs"] == 1
        assert data["successful_runs"] == 1

    def test_run_empty_task(self, client: TestClient) -> None:
        """Bo'sh task → 422."""
        self._create_active_agent(client)
        resp = client.post(
            "/api/v1/agents/test_agent/run",
            json={"task": ""},
        )
        assert resp.status_code == 422


class TestAgentAPIPersistence:
    """`_persist()` write-through — agentlar real DB'ga ham yoziladi (gap-analysis #1).

    `AgentRegistry` (in-memory) test uchun yangi, `get_db_session` esa real
    (in-memory sqlite) sessiyaga almashtiriladi — yozuv DB'da ham paydo
    bo'lishini `AgentRepository` orqali tekshiramiz.
    """

    @pytest.fixture()
    def registry(self) -> AgentRegistry:
        return AgentRegistry()

    @pytest.fixture()
    def pg_client(self, registry: AgentRegistry, session: AsyncSession) -> TestClient:
        app = create_app()

        async def _session_override():
            yield session

        app.dependency_overrides[get_agent_registry] = lambda: registry
        app.dependency_overrides[get_db_session] = _session_override
        app.dependency_overrides[get_killswitch] = KillSwitchState
        return TestClient(app, raise_server_exceptions=False)

    async def test_create_agent_persists_to_db(
        self, pg_client: TestClient, session: AsyncSession
    ) -> None:
        from zet.agents.repository import AgentRepository

        resp = pg_client.post("/api/v1/agents", json=_agent_payload())
        assert resp.status_code == 201

        loaded = await AgentRepository(session).get("test_agent")
        assert loaded is not None
        assert loaded.spec.description == "Test uchun agent"

    async def test_status_update_persists_to_db(
        self, pg_client: TestClient, session: AsyncSession
    ) -> None:
        from zet.agents.repository import AgentRepository

        pg_client.post("/api/v1/agents", json=_agent_payload())
        pg_client.patch("/api/v1/agents/test_agent/status", json={"action": "start_testing"})
        pg_client.patch("/api/v1/agents/test_agent/status", json={"action": "activate"})

        loaded = await AgentRepository(session).get("test_agent")
        assert loaded is not None
        assert loaded.status.value == "active"

    async def test_run_persists_metrics_to_db(
        self, pg_client: TestClient, session: AsyncSession
    ) -> None:
        from zet.agents.repository import AgentRepository

        pg_client.post("/api/v1/agents", json=_agent_payload())
        pg_client.patch("/api/v1/agents/test_agent/status", json={"action": "start_testing"})
        pg_client.patch("/api/v1/agents/test_agent/status", json={"action": "activate"})
        pg_client.post("/api/v1/agents/test_agent/run", json={"task": "Test vazifa"})

        loaded = await AgentRepository(session).get("test_agent")
        assert loaded is not None
        assert loaded.total_runs == 1
        assert loaded.successful_runs == 1
