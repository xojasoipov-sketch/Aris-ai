"""Bo'lim 2 — Memory API trust_level siyosati testlari.

Audit'ga muvofiq HTTP qatlamda `check_write`/`check_read` chaqirilishi
kafolatlanadi. `X-Trust-Level` header'i orqali chaqiruvchi darajasi
uzatiladi (default `"owner"` — backward compat).

Bog'liq qarorlar:
    V-14 — ruxsatga bog'liq ko'rinish
    A-05 — trust-level dinamik oqim
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_memory_store
from zet.domain.memory import MemoryLayer
from zet.memory.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(store: MemoryStore) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_memory_store] = lambda: store
    return TestClient(app)


class TestMemoryAPIWritePolicy:
    """POST /api/v1/memory — yozish siyosati."""

    def test_owner_default_can_write_knowledge(self, client: TestClient) -> None:
        """Header berilmasa default `owner` — KNOWLEDGE ga yozadi (backward compat)."""
        resp = client.post(
            "/api/v1/memory",
            json={"layer": "knowledge", "content": "python bilim"},
        )
        assert resp.status_code == 201
        data = resp.json()
        # Server trust_level'ni chaqiruvchi darajasiga tenglaydi.
        assert data["trust_level"] == "owner"
        assert data["layer"] == "knowledge"

    def test_system_trust_cannot_write_knowledge(self, client: TestClient) -> None:
        """`system` KNOWLEDGE ga yoza olmaydi — 403 va aniq sabab."""
        resp = client.post(
            "/api/v1/memory",
            headers={"X-Trust-Level": "system"},
            json={"layer": "knowledge", "content": "yolg'on bilim"},
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert "knowledge" in detail
        assert "system" in detail

    def test_untrusted_cannot_write_personal(self, client: TestClient) -> None:
        """`untrusted` faqat SHORT_TERM — PERSONAL ga 403."""
        resp = client.post(
            "/api/v1/memory",
            headers={"X-Trust-Level": "untrusted"},
            json={"layer": "personal", "content": "shaxsiy"},
        )
        assert resp.status_code == 403

    def test_system_roundtrip_short_term(self, client: TestClient, store: MemoryStore) -> None:
        """`system` SHORT_TERM ga yozadi, keyin o'qiy oladi."""
        resp = client.post(
            "/api/v1/memory",
            headers={"X-Trust-Level": "system"},
            json={"layer": "short_term", "content": "vaqtincha"},
        )
        assert resp.status_code == 201
        entry_id = resp.json()["id"]
        assert resp.json()["trust_level"] == "system"

        # Aynan shu ID orqali qaytib olamiz — system SHORT_TERM ni o'qiy oladi.
        get_resp = client.get(
            f"/api/v1/memory/{entry_id}",
            headers={"X-Trust-Level": "system"},
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["content"] == "vaqtincha"

    def test_invalid_header_returns_400(self, client: TestClient) -> None:
        """Noto'g'ri X-Trust-Level qiymati — 400, siyosat bypass qilinmasin."""
        resp = client.post(
            "/api/v1/memory",
            headers={"X-Trust-Level": "root"},
            json={"layer": "knowledge", "content": "test"},
        )
        assert resp.status_code == 400
        assert "X-Trust-Level" in resp.json()["detail"]


class TestMemoryAPIReadPolicy:
    """GET/search — o'qish siyosati."""

    def test_untrusted_cannot_search_personal_explicit(
        self, client: TestClient, store: MemoryStore
    ) -> None:
        """`untrusted` `layers=[personal]` bilan qidirsa — 403."""
        store.add(layer=MemoryLayer.PERSONAL, content="maxfiy yozuv")

        resp = client.post(
            "/api/v1/memory/search",
            headers={"X-Trust-Level": "untrusted"},
            json={
                "text": "maxfiy",
                "layers": ["personal"],
                "min_similarity": 0.0,
            },
        )
        assert resp.status_code == 403
        assert "personal" in resp.json()["detail"]

    def test_untrusted_search_no_filter_hides_personal(
        self, client: TestClient, store: MemoryStore
    ) -> None:
        """Filtr yuborilmasa — untrusted uchun PERSONAL yozuvlar chiqmaydi.

        Aks holda filtr yo'qligini bahona qilib untrusted PERSONAL ni
        bemalol o'qishi mumkin edi.
        """
        store.add(layer=MemoryLayer.PERSONAL, content="maxfiy tag")
        store.add(layer=MemoryLayer.SHORT_TERM, content="vaqtinchalik tag")

        resp = client.post(
            "/api/v1/memory/search",
            headers={"X-Trust-Level": "untrusted"},
            json={"text": "tag", "min_similarity": 0.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        layers = {r["entry"]["layer"] for r in data}
        assert "personal" not in layers

    def test_untrusted_cannot_read_task_layer(self, client: TestClient) -> None:
        """`GET /memory/layer/task` untrusted uchun 403."""
        resp = client.get(
            "/api/v1/memory/layer/task",
            headers={"X-Trust-Level": "untrusted"},
        )
        assert resp.status_code == 403
        assert "task" in resp.json()["detail"]

    def test_untrusted_cannot_read_task_entry(self, client: TestClient, store: MemoryStore) -> None:
        """TASK yozuvni `untrusted` GET orqali olmaydi — 403."""
        entry = store.add(layer=MemoryLayer.TASK, content="vazifa konteksti")
        resp = client.get(
            f"/api/v1/memory/{entry.id}",
            headers={"X-Trust-Level": "untrusted"},
        )
        assert resp.status_code == 403


class TestMemoryAPIPolicyBackwardCompat:
    """Header'siz eski mijozlar sinishmasligi."""

    def test_no_header_defaults_to_owner(self, client: TestClient, store: MemoryStore) -> None:
        """Header yo'q → owner: PERSONAL yozish/o'qish ishlaydi."""
        add = client.post(
            "/api/v1/memory",
            json={"layer": "personal", "content": "test"},
        )
        assert add.status_code == 201
        entry_id = add.json()["id"]

        get_resp = client.get(f"/api/v1/memory/{entry_id}")
        assert get_resp.status_code == 200
