"""Z1.14 — FastAPI testlari.

httpx AsyncClient bilan TestClient.

Tekshiriladi:
    - GET /api/v1/health → 200
    - GET /api/v1/status → tizim holati
    - POST /api/v1/run → accepted
    - POST /api/v1/run killswitch yoqilgan → 503
    - POST /api/v1/run bo'sh message → 422
    - POST /api/v1/killswitch/engage → engaged
    - POST /api/v1/killswitch/disengage → disengaged
    - POST /api/v1/killswitch/disengage allaqachon o'chirilgan → 400
    - GET /api/v1/killswitch → holat
    - TraceMiddleware: X-Trace-ID headerda qaytariladi
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_killswitch
from zet.security.killswitch import KillSwitchState


@pytest.fixture()
def killswitch() -> KillSwitchState:
    """Har bir test uchun yangi killswitch."""
    return KillSwitchState()


@pytest.fixture()
def client(killswitch: KillSwitchState) -> TestClient:
    """FastAPI test client."""
    app = create_app()
    app.dependency_overrides[get_killswitch] = lambda: killswitch
    return TestClient(app, raise_server_exceptions=False)


# ── Health ─────────────────────────────────────────────────────────


class TestHealth:
    def test_health_check(self, client: TestClient) -> None:
        """GET /health → 200."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_status(self, client: TestClient) -> None:
        """GET /status → tizim holati."""
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "killswitch" in data
        assert "budget" in data

    def test_status_with_killswitch(self, client: TestClient, killswitch: KillSwitchState) -> None:
        """GET /status killswitch yoqilgan → killswitch_engaged."""
        killswitch.engage(reason="Test")
        resp = client.get("/api/v1/status")
        assert resp.json()["status"] == "killswitch_engaged"


# ── Run ────────────────────────────────────────────────────────────


class TestRun:
    def test_create_run(self, client: TestClient) -> None:
        """POST /run → accepted."""
        resp = client.post("/api/v1/run", json={"message": "Havo qanday?"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert "trace_id" in data
        assert len(data["trace_id"]) == 32

    def test_run_with_killswitch(self, client: TestClient, killswitch: KillSwitchState) -> None:
        """POST /run killswitch yoqilgan → 503."""
        killswitch.engage(reason="Test")
        resp = client.post("/api/v1/run", json={"message": "test"})
        assert resp.status_code == 503

    def test_run_empty_message(self, client: TestClient) -> None:
        """POST /run bo'sh message → 422."""
        resp = client.post("/api/v1/run", json={"message": ""})
        assert resp.status_code == 422

    def test_run_dry_run(self, client: TestClient) -> None:
        """POST /run dry_run=true."""
        resp = client.post(
            "/api/v1/run",
            json={"message": "test", "dry_run": True},
        )
        assert resp.status_code == 200


# ── KillSwitch ────────────────────────────────────────────────────


class TestKillSwitchAPI:
    def test_engage(self, client: TestClient) -> None:
        """POST /killswitch/engage → engaged."""
        resp = client.post(
            "/api/v1/killswitch/engage",
            json={"reason": "Test engage"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "engaged"

    def test_disengage(self, client: TestClient, killswitch: KillSwitchState) -> None:
        """POST /killswitch/disengage → disengaged."""
        killswitch.engage(reason="Test")
        resp = client.post("/api/v1/killswitch/disengage")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disengaged"

    def test_disengage_already_off(self, client: TestClient) -> None:
        """POST /killswitch/disengage allaqachon o'chirilgan → 400."""
        resp = client.post("/api/v1/killswitch/disengage")
        assert resp.status_code == 400

    def test_status(self, client: TestClient) -> None:
        """GET /killswitch → holat."""
        resp = client.get("/api/v1/killswitch")
        assert resp.status_code == 200
        assert "killswitch" in resp.json()


# ── Middleware ────────────────────────────────────────────────────


class TestTraceMiddleware:
    def test_trace_id_in_response(self, client: TestClient) -> None:
        """Javob headerida X-Trace-ID bor."""
        resp = client.get("/api/v1/health")
        assert "X-Trace-ID" in resp.headers
        assert len(resp.headers["X-Trace-ID"]) == 32

    def test_trace_id_forwarded(self, client: TestClient) -> None:
        """So'rovdagi X-Trace-ID qaytariladi."""
        resp = client.get(
            "/api/v1/health",
            headers={"X-Trace-ID": "custom-trace-123"},
        )
        assert resp.headers["X-Trace-ID"] == "custom-trace-123"
