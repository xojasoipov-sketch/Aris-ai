"""Qurilma API va DeviceDBRepository testlari (Bo'lim 8, A-06).

`test_crm_api.py` bilan bir xil naqsh: `get_db_session`ni real
in-memory sqlite sessiyaga almashtirib, HTTP orqali `DeviceDBRepository`
zanjirini uchidan-uchgacha tekshiradi. Token xesh saqlanishi (xom emas)
va fail-open xatti-harakat alohida sinaladi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.app import create_app
from zet.api.deps import get_db_session
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.device import CapabilityToken as CapabilityTokenRow
from zet.devices.registry import DeviceType
from zet.devices.repository import DeviceDBRepository, _hash_token


@pytest.fixture()
def client(session: AsyncSession) -> TestClient:
    """HTTP klient — bitta in-memory sessiya barcha so'rovlar uchun."""
    app = create_app()

    async def _session_override():
        yield session

    app.dependency_overrides[get_db_session] = _session_override
    return TestClient(app, raise_server_exceptions=False)


def _register(client: TestClient, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": "iPhone 15",
        "device_type": "phone",
        "platform": "ios",
        "capabilities": ["notify"],
    }
    payload.update(overrides)
    resp = client.post("/api/v1/devices", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── HTTP CRUD ─────────────────────────────────────────────────────


class TestDeviceHttpCrud:
    def test_create_returns_raw_token_once(self, client: TestClient) -> None:
        """Xom token faqat yaratish javobida — keyingi so'rovlarda YO'Q."""
        created = _register(client, capabilities=["camera.snapshot", "notify"])
        assert created["device"]["name"] == "iPhone 15"
        assert created["device"]["device_type"] == "phone"
        assert isinstance(created["token"], str)
        assert len(created["token"]) >= 20

        device_id = created["device"]["id"]
        fetched = client.get(f"/api/v1/devices/{device_id}").json()
        # Yagona qurilma javobida "token" maydoni bo'lmasligi kerak — xesh
        # DB'da, xom qiymat esa hech qayerda saqlanmaydi.
        assert "token" not in fetched

    def test_list_devices(self, client: TestClient) -> None:
        _register(client, name="Phone A", device_type="phone")
        _register(client, name="Desktop B", device_type="desktop")
        resp = client.get("/api/v1/devices")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_devices_by_type(self, client: TestClient) -> None:
        _register(client, name="P1", device_type="phone")
        _register(client, name="P2", device_type="phone")
        _register(client, name="D1", device_type="desktop")
        resp = client.get("/api/v1/devices", params={"device_type": "phone"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(d["device_type"] == "phone" for d in data)

    def test_get_device_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/v1/devices/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_update_status_sets_last_seen(self, client: TestClient) -> None:
        created = _register(client)
        device_id = created["device"]["id"]
        assert created["device"]["online"] is False
        assert created["device"]["last_seen"] is None

        resp = client.post(f"/api/v1/devices/{device_id}/status", json={"online": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["online"] is True
        assert data["last_seen"] is not None

    def test_delete_device_revokes_tokens(self, client: TestClient) -> None:
        created = _register(client, capabilities=["notify"])
        device_id = created["device"]["id"]

        resp = client.delete(f"/api/v1/devices/{device_id}")
        assert resp.status_code == 204

        resp = client.get(f"/api/v1/devices/{device_id}")
        assert resp.status_code == 404


# ── Token validatsiyasi ───────────────────────────────────────────


@pytest.fixture()
async def repo(session: AsyncSession) -> DeviceDBRepository:
    """DeviceDBRepository fixture — o'z egasi bilan."""
    owner = await get_or_create_owner(session, external_id="test-devices")
    return DeviceDBRepository(session, owner_id=owner.id)


class TestTokenValidation:
    async def test_validate_token_happy_path(self, repo: DeviceDBRepository) -> None:
        _, raw = await repo.register(
            name="Camera 1",
            device_type=DeviceType.CAMERA,
            capabilities=["camera.snapshot", "notify"],
        )
        assert await repo.validate_token(raw, "camera.snapshot") is True
        assert await repo.validate_token(raw, "notify") is True

    async def test_validate_wrong_token_rejected(self, repo: DeviceDBRepository) -> None:
        await repo.register(
            name="Phone",
            device_type=DeviceType.PHONE,
            capabilities=["notify"],
        )
        assert await repo.validate_token("not-a-real-token", "notify") is False
        assert await repo.validate_token("", "notify") is False

    async def test_validate_missing_capability(self, repo: DeviceDBRepository) -> None:
        _, raw = await repo.register(
            name="Camera",
            device_type=DeviceType.CAMERA,
            capabilities=["camera.snapshot"],
        )
        assert await repo.validate_token(raw, "admin") is False
        assert await repo.validate_token(raw, "notify") is False

    async def test_expired_token_rejected(
        self, repo: DeviceDBRepository, session: AsyncSession
    ) -> None:
        _, raw = await repo.register(
            name="Camera",
            device_type=DeviceType.CAMERA,
            capabilities=["camera.snapshot"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        # Boshlanish: hali muddati o'tmagan.
        assert await repo.validate_token(raw, "camera.snapshot") is True

        # Xesh orqali topib, `expires_at`ni o'tmishga suramiz — sun'iy
        # eskirish (real vaqtni kutmaslik uchun).
        from sqlalchemy import select

        row = (
            await session.execute(
                select(CapabilityTokenRow).where(CapabilityTokenRow.token_hash == _hash_token(raw))
            )
        ).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()

        assert await repo.validate_token(raw, "camera.snapshot") is False

    async def test_revoked_token_rejected(self, repo: DeviceDBRepository) -> None:
        _, raw = await repo.register(
            name="Phone",
            device_type=DeviceType.PHONE,
            capabilities=["notify"],
        )
        assert await repo.validate_token(raw, "notify") is True
        assert await repo.revoke_token(raw) is True
        assert await repo.validate_token(raw, "notify") is False

    async def test_revoke_unknown_token(self, repo: DeviceDBRepository) -> None:
        assert await repo.revoke_token("bogus") is False

    async def test_token_stored_as_hash_not_raw(
        self, repo: DeviceDBRepository, session: AsyncSession
    ) -> None:
        """Xom token DB'da yo'q — faqat SHA-256 xeshi."""
        _, raw = await repo.register(
            name="Camera",
            device_type=DeviceType.CAMERA,
            capabilities=["camera.snapshot"],
        )
        from sqlalchemy import select

        rows = (await session.execute(select(CapabilityTokenRow))).scalars().all()
        assert len(rows) == 1
        stored = rows[0]
        # Xom qiymat DB'da bo'lmasligi kerak.
        assert stored.token_hash != raw
        # Xesh SHA-256 hex — 64 belgi.
        assert len(stored.token_hash) == 64
        # Va u haqiqatan ham xomning xeshi.
        assert stored.token_hash == _hash_token(raw)

    async def test_delete_device_marks_tokens_revoked(self, repo: DeviceDBRepository) -> None:
        """`delete()` tokenlarni oldin revoke qiladi — audit izi qolsin."""
        device, raw = await repo.register(
            name="Phone",
            device_type=DeviceType.PHONE,
            capabilities=["notify"],
        )
        assert await repo.validate_token(raw, "notify") is True

        deleted = await repo.delete(device.id)
        assert deleted is True

        # Qurilma o'chdi — token ham CASCADE bilan yo'qolgan, validate False.
        assert await repo.validate_token(raw, "notify") is False
