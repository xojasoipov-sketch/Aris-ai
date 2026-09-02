"""Automation API testlari (Bo'lim 9).

Tekshiriladi:
    - POST/GET/pause/resume/DELETE /api/v1/automation/schedules
    - POST/GET/DELETE /api/v1/automation/triggers
    - POST/GET /api/v1/automation/workflows + POST .../run
    - POST /api/v1/automation/events — haqiqiy bajarish
    - GET /api/v1/automation/stats
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.agents.registry import AgentRegistry
from zet.api.app import create_app
from zet.api.deps import (
    get_agent_registry,
    get_automation_engine,
    get_db_session,
    get_llm_providers,
    get_tool_registry,
)
from zet.automation.engine import AutomationEngine
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, ModelTier
from zet.llm.fake import FakeProvider
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


@pytest.fixture()
def automation_engine() -> AutomationEngine:
    return AutomationEngine()


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(
        AgentSpec(name="worker", description="Test ishchisi", system_prompt="Sen ishchisan."),
        status=AgentStatus.ACTIVE,
    )
    return reg


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


@pytest.fixture()
def client(
    automation_engine: AutomationEngine,
    agent_registry: AgentRegistry,
    tool_registry: ToolRegistry,
    session: AsyncSession,
) -> TestClient:
    """`get_db_session`/`get_llm_providers` ham almashtiriladi — workflow/event
    endpointlari endi real `ModelRouter` orqali ishlaydi (haqiqiy tarmoqqa
    chiqmaydigan `FakeProvider`, katalogdagi "google" nomi ostida)."""
    app = create_app()

    async def _session_override():
        yield session

    app.dependency_overrides[get_automation_engine] = lambda: automation_engine
    app.dependency_overrides[get_agent_registry] = lambda: agent_registry
    app.dependency_overrides[get_tool_registry] = lambda: tool_registry
    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_llm_providers] = lambda: {
        "google": FakeProvider(name="google", tier=ModelTier.T1_FREE)
    }
    return TestClient(app, raise_server_exceptions=False)


class TestSchedules:
    def test_create_schedule(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/automation/schedules",
            json={"name": "Kunlik", "agent_name": "worker", "cron_expr": "0 9 * * *"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Kunlik"
        assert data["status"] == "active"

    def test_create_invalid_cron_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/automation/schedules",
            json={"name": "Yomon", "agent_name": "worker", "cron_expr": "not-a-cron"},
        )
        assert resp.status_code == 422

    def test_list_schedules(self, client: TestClient) -> None:
        client.post(
            "/api/v1/automation/schedules",
            json={"name": "A", "agent_name": "worker", "cron_expr": "@daily"},
        )
        resp = client.get("/api/v1/automation/schedules")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_pause_and_resume(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/automation/schedules",
            json={"name": "A", "agent_name": "worker", "cron_expr": "@daily"},
        ).json()
        schedule_id = created["id"]

        paused = client.post(f"/api/v1/automation/schedules/{schedule_id}/pause")
        assert paused.json()["status"] == "paused"

        resumed = client.post(f"/api/v1/automation/schedules/{schedule_id}/resume")
        assert resumed.json()["status"] == "active"

    def test_pause_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/v1/automation/schedules/no-such-id/pause")
        assert resp.status_code == 404

    def test_delete_schedule(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/automation/schedules",
            json={"name": "A", "agent_name": "worker", "cron_expr": "@daily"},
        ).json()
        resp = client.delete(f"/api/v1/automation/schedules/{created['id']}")
        assert resp.status_code == 204
        assert client.get("/api/v1/automation/schedules").json() == []

    def test_delete_not_found(self, client: TestClient) -> None:
        resp = client.delete("/api/v1/automation/schedules/no-such-id")
        assert resp.status_code == 404


class TestTriggers:
    def test_create_trigger(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/automation/triggers",
            json={
                "name": "Harakat aniqlandi",
                "trigger_type": "device",
                "agent_name": "worker",
                "conditions": [{"field": "event_type", "operator": "eq", "value": "motion"}],
                "command_template": "Kamera {camera_id} harakat aniqladi",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Harakat aniqlandi"

    def test_list_triggers(self, client: TestClient) -> None:
        client.post(
            "/api/v1/automation/triggers",
            json={"name": "A", "trigger_type": "system", "agent_name": "worker"},
        )
        resp = client.get("/api/v1/automation/triggers")
        assert len(resp.json()) == 1

    def test_delete_trigger(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/automation/triggers",
            json={"name": "A", "trigger_type": "system", "agent_name": "worker"},
        ).json()
        resp = client.delete(f"/api/v1/automation/triggers/{created['id']}")
        assert resp.status_code == 204

    def test_delete_not_found(self, client: TestClient) -> None:
        resp = client.delete("/api/v1/automation/triggers/no-such-id")
        assert resp.status_code == 404


class TestWorkflows:
    def test_create_workflow(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/automation/workflows",
            json={
                "name": "Zanjir",
                "steps": [{"agent_name": "worker", "command_template": "Ishla"}],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert len(data["steps"]) == 1

    def test_create_empty_workflow_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/automation/workflows",
            json={"name": "Bo'sh", "steps": []},
        )
        assert resp.status_code == 422

    def test_get_workflow(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/automation/workflows",
            json={
                "name": "Zanjir",
                "steps": [{"agent_name": "worker", "command_template": "Ishla"}],
            },
        ).json()
        resp = client.get(f"/api/v1/automation/workflows/{created['id']}")
        assert resp.status_code == 200

    def test_get_workflow_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/automation/workflows/no-such-id")
        assert resp.status_code == 404

    def test_run_workflow_completes(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/automation/workflows",
            json={
                "name": "Zanjir",
                "steps": [{"agent_name": "worker", "command_template": "Ishla"}],
            },
        ).json()
        resp = client.post(f"/api/v1/automation/workflows/{created['id']}/run")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_run_workflow_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/v1/automation/workflows/no-such-id/run")
        assert resp.status_code == 404


class TestEvents:
    def test_event_with_no_matching_trigger(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/automation/events",
            json={"event_type": "motion_detected", "source": "cam1"},
        )
        assert resp.status_code == 200
        assert resp.json()["actions"] == []

    def test_event_executes_matching_trigger(self, client: TestClient) -> None:
        client.post(
            "/api/v1/automation/triggers",
            json={
                "name": "Harakat",
                "trigger_type": "device",
                "agent_name": "worker",
                "conditions": [{"field": "event_type", "operator": "eq", "value": "motion"}],
                "command_template": "Harakat aniqlandi",
            },
        )
        resp = client.post(
            "/api/v1/automation/events",
            json={"event_type": "motion", "source": "cam1"},
        )
        assert resp.status_code == 200
        actions = resp.json()["actions"]
        assert len(actions) == 1
        assert actions[0]["agent_name"] == "worker"
        assert actions[0]["success"] is True

    def test_event_unavailable_agent_reports_failure(self, client: TestClient) -> None:
        client.post(
            "/api/v1/automation/triggers",
            json={"name": "X", "trigger_type": "system", "agent_name": "ghost"},
        )
        resp = client.post("/api/v1/automation/events", json={"event_type": "any"})
        actions = resp.json()["actions"]
        assert len(actions) == 1
        assert actions[0]["success"] is False


class TestStats:
    def test_stats_reflects_created_objects(self, client: TestClient) -> None:
        client.post(
            "/api/v1/automation/schedules",
            json={"name": "A", "agent_name": "worker", "cron_expr": "@daily"},
        )
        resp = client.get("/api/v1/automation/stats")
        assert resp.status_code == 200
        assert resp.json()["schedules"]["total"] == 1
