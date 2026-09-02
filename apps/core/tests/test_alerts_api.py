"""Alert API testlari (Bo'lim 10, gap-analysis #14).

Tekshiriladi:
    - POST /api/v1/alerts → yaratish + Notifier orqali yuborish
    - GET  /api/v1/alerts → ro'yxat
    - POST /api/v1/alerts/{id}/acknowledge → ko'rilgan deb belgilash
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_alert_manager, get_notifier
from zet.monitoring.alerts import AlertManager
from zet.telegram.notifier import StubNotifier


@pytest.fixture()
def notifier() -> StubNotifier:
    return StubNotifier()


@pytest.fixture()
def alert_manager() -> AlertManager:
    return AlertManager()


@pytest.fixture()
def client(alert_manager: AlertManager, notifier: StubNotifier) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_alert_manager] = lambda: alert_manager
    app.dependency_overrides[get_notifier] = lambda: notifier
    return TestClient(app, raise_server_exceptions=False)


class TestFireAlert:
    def test_fire_creates_and_sends(self, client: TestClient, notifier: StubNotifier) -> None:
        resp = client.post(
            "/api/v1/alerts",
            json={"name": "budget", "message": "90% sarflandi", "severity": "critical"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["rule_name"] == "budget"
        assert data["severity"] == "critical"
        assert data["acknowledged"] is False
        assert notifier.count == 1

    def test_fire_empty_message_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/v1/alerts", json={"name": "x", "message": ""})
        assert resp.status_code == 422


class TestListAlerts:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_fire(self, client: TestClient) -> None:
        client.post("/api/v1/alerts", json={"name": "a", "message": "b"})
        resp = client.get("/api/v1/alerts")
        assert len(resp.json()) == 1

    def test_list_unacknowledged_only(self, client: TestClient) -> None:
        fire_resp = client.post("/api/v1/alerts", json={"name": "a", "message": "b"})
        alert_id = fire_resp.json()["id"]
        client.post(f"/api/v1/alerts/{alert_id}/acknowledge")

        resp = client.get("/api/v1/alerts", params={"unacknowledged_only": True})
        assert resp.json() == []


class TestAcknowledgeAlert:
    def test_acknowledge_success(self, client: TestClient) -> None:
        fire_resp = client.post("/api/v1/alerts", json={"name": "a", "message": "b"})
        alert_id = fire_resp.json()["id"]

        resp = client.post(f"/api/v1/alerts/{alert_id}/acknowledge")
        assert resp.status_code == 200
        assert resp.json()["acknowledged"] is True

    def test_acknowledge_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/v1/alerts/does-not-exist/acknowledge")
        assert resp.status_code == 404
