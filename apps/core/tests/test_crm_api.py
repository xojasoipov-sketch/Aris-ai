"""CRM API testlari (Bo'lim 6, C-03).

`get_db_session`ni real (in-memory sqlite) sessiyaga almashtirib —
`TestMemoryAPIPersistence` bilan bir xil naqsh (session→owner→PgCRM
zanjiri, `get_crm`ning o'zini override qilmasdan).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.app import create_app
from zet.api.deps import get_db_session


@pytest.fixture()
def client(session: AsyncSession) -> TestClient:
    app = create_app()

    async def _session_override():
        yield session

    app.dependency_overrides[get_db_session] = _session_override
    return TestClient(app, raise_server_exceptions=False)


def _create_contact(client: TestClient, **overrides: object) -> dict:
    payload = {"name": "Ali Valiyev"}
    payload.update(overrides)
    return client.post("/api/v1/crm/contacts", json=payload).json()


class TestContacts:
    def test_create_contact(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/crm/contacts",
            json={"name": "Ali Valiyev", "company": "Acme", "email": "ali@acme.uz"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Ali Valiyev"
        assert data["company"] == "Acme"

    def test_list_contacts(self, client: TestClient) -> None:
        _create_contact(client, name="A")
        _create_contact(client, name="B")
        resp = client.get("/api/v1/crm/contacts")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_search_contacts(self, client: TestClient) -> None:
        _create_contact(client, name="Ali Valiyev")
        _create_contact(client, name="Boris Ivanov")
        resp = client.get("/api/v1/crm/contacts", params={"query": "ali"})
        assert len(resp.json()) == 1

    def test_get_contact(self, client: TestClient) -> None:
        created = _create_contact(client)
        resp = client.get(f"/api/v1/crm/contacts/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Ali Valiyev"

    def test_get_contact_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/crm/contacts/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestLeads:
    def test_create_lead(self, client: TestClient) -> None:
        contact = _create_contact(client)
        resp = client.post(
            "/api/v1/crm/leads",
            json={"contact_id": contact["id"], "source": "telegram", "score": 10},
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "new"

    def test_create_lead_missing_contact(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/crm/leads",
            json={"contact_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404

    def test_list_leads_filter_by_status(self, client: TestClient) -> None:
        contact = _create_contact(client)
        lead = client.post("/api/v1/crm/leads", json={"contact_id": contact["id"]}).json()
        client.post(f"/api/v1/crm/leads/{lead['id']}/qualify", json={"score": 80})
        client.post("/api/v1/crm/leads", json={"contact_id": contact["id"]})

        resp = client.get("/api/v1/crm/leads", params={"status": "qualified"})
        assert len(resp.json()) == 1

    def test_get_lead_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/crm/leads/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_qualify_lead(self, client: TestClient) -> None:
        contact = _create_contact(client)
        lead = client.post("/api/v1/crm/leads", json={"contact_id": contact["id"]}).json()
        resp = client.post(f"/api/v1/crm/leads/{lead['id']}/qualify", json={"score": 90})
        assert resp.status_code == 200
        assert resp.json()["status"] == "qualified"

    def test_qualify_lead_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/crm/leads/00000000-0000-0000-0000-000000000000/qualify",
            json={"score": 90},
        )
        assert resp.status_code == 404


class TestDeals:
    def _create_lead(self, client: TestClient) -> dict:
        contact = _create_contact(client)
        return client.post("/api/v1/crm/leads", json={"contact_id": contact["id"]}).json()

    def test_create_deal(self, client: TestClient) -> None:
        lead = self._create_lead(client)
        resp = client.post(
            "/api/v1/crm/deals",
            json={"lead_id": lead["id"], "title": "Kurs sotuvi", "amount": 500.0},
        )
        assert resp.status_code == 201
        assert resp.json()["stage"] == "proposal"

    def test_create_deal_missing_lead(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/crm/deals",
            json={"lead_id": "00000000-0000-0000-0000-000000000000", "title": "X"},
        )
        assert resp.status_code == 404

    def test_list_deals_filter_by_stage(self, client: TestClient) -> None:
        lead = self._create_lead(client)
        deal = client.post(
            "/api/v1/crm/deals", json={"lead_id": lead["id"], "title": "A", "amount": 100.0}
        ).json()
        client.post(f"/api/v1/crm/deals/{deal['id']}/stage", json={"stage": "won"})
        client.post("/api/v1/crm/deals", json={"lead_id": lead["id"], "title": "B"})

        resp = client.get("/api/v1/crm/deals", params={"stage": "won"})
        assert len(resp.json()) == 1

    def test_update_deal_stage(self, client: TestClient) -> None:
        lead = self._create_lead(client)
        deal = client.post(
            "/api/v1/crm/deals", json={"lead_id": lead["id"], "title": "A", "amount": 100.0}
        ).json()
        resp = client.post(f"/api/v1/crm/deals/{deal['id']}/stage", json={"stage": "negotiation"})
        assert resp.status_code == 200
        assert resp.json()["stage"] == "negotiation"

    def test_update_deal_stage_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/crm/deals/00000000-0000-0000-0000-000000000000/stage",
            json={"stage": "won"},
        )
        assert resp.status_code == 404


class TestStats:
    def test_stats_reflects_pipeline(self, client: TestClient) -> None:
        contact = _create_contact(client)
        lead = client.post("/api/v1/crm/leads", json={"contact_id": contact["id"]}).json()
        deal = client.post(
            "/api/v1/crm/deals", json={"lead_id": lead["id"], "title": "A", "amount": 250.0}
        ).json()
        client.post(f"/api/v1/crm/deals/{deal['id']}/stage", json={"stage": "won"})

        resp = client.get("/api/v1/crm/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contacts"] == 1
        assert data["deals"] == 1
        assert data["won_value"] == 250.0
