"""Bo'lim 2 — Memory API testlari.

Tekshiriladi:
    - POST /api/v1/memory — yozuv qo'shish
    - GET /api/v1/memory/{id} — yozuv olish
    - PATCH /api/v1/memory/{id} — yozuv yangilash
    - DELETE /api/v1/memory/{id} — yozuv o'chirish
    - POST /api/v1/memory/search — qidirish
    - GET /api/v1/memory/layer/{layer} — qatlam bo'yicha
    - POST /api/v1/memory/cleanup — tozalash
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_memory_store
from zet.memory.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(store: MemoryStore) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_memory_store] = lambda: store
    return TestClient(app)


class TestMemoryAPI:
    def test_add_memory(self, client: TestClient) -> None:
        """POST /api/v1/memory — yozuv qo'shish."""
        resp = client.post(
            "/api/v1/memory",
            json={
                "layer": "knowledge",
                "content": "Python dasturlash tili",
                "tags": ["python"],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Python dasturlash tili"
        assert data["layer"] == "knowledge"
        assert data["version"] == 1
        assert "python" in data["tags"]

    def test_get_memory(self, client: TestClient, store: MemoryStore) -> None:
        """GET /api/v1/memory/{id} — yozuv olish."""
        from zet.domain.memory import MemoryLayer

        entry = store.add(layer=MemoryLayer.KNOWLEDGE, content="test matn")
        resp = client.get(f"/api/v1/memory/{entry.id}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "test matn"

    def test_get_nonexistent(self, client: TestClient) -> None:
        """GET 404 for nonexistent."""
        resp = client.get("/api/v1/memory/nonexistent")
        assert resp.status_code == 404

    def test_update_memory(self, client: TestClient, store: MemoryStore) -> None:
        """PATCH /api/v1/memory/{id} — versiya oshadi."""
        from zet.domain.memory import MemoryLayer

        entry = store.add(layer=MemoryLayer.KNOWLEDGE, content="eski matn")
        resp = client.patch(
            f"/api/v1/memory/{entry.id}",
            json={"content": "yangi matn"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "yangi matn"
        assert data["version"] == 2

    def test_update_nonexistent(self, client: TestClient) -> None:
        """PATCH 404 for nonexistent."""
        resp = client.patch(
            "/api/v1/memory/nonexistent",
            json={"content": "test"},
        )
        assert resp.status_code == 404

    def test_delete_memory(self, client: TestClient, store: MemoryStore) -> None:
        """DELETE /api/v1/memory/{id} — soft delete."""
        from zet.domain.memory import MemoryLayer

        entry = store.add(layer=MemoryLayer.KNOWLEDGE, content="test")
        resp = client.delete(f"/api/v1/memory/{entry.id}")
        assert resp.status_code == 204

        # Endi get 404 qaytarishi kerak
        resp = client.get(f"/api/v1/memory/{entry.id}")
        assert resp.status_code == 404

    def test_delete_nonexistent(self, client: TestClient) -> None:
        """DELETE 404 for nonexistent."""
        resp = client.delete("/api/v1/memory/nonexistent")
        assert resp.status_code == 404

    def test_search(self, client: TestClient, store: MemoryStore) -> None:
        """POST /api/v1/memory/search — qidirish."""
        from zet.domain.memory import MemoryLayer

        store.add(layer=MemoryLayer.KNOWLEDGE, content="Python dasturlash tili")
        store.add(layer=MemoryLayer.KNOWLEDGE, content="JavaScript web uchun")

        resp = client.post(
            "/api/v1/memory/search",
            json={"text": "Python", "min_similarity": 0.5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["entry"]["content"] == "Python dasturlash tili"
        assert data[0]["rank"] == 1

    def test_search_with_layer_filter(self, client: TestClient, store: MemoryStore) -> None:
        """Qatlam bo'yicha filtrlangan qidirish."""
        from zet.domain.memory import MemoryLayer

        store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim test")
        store.add(layer=MemoryLayer.PERSONAL, content="shaxsiy test")

        resp = client.post(
            "/api/v1/memory/search",
            json={
                "text": "test",
                "layers": ["knowledge"],
                "min_similarity": 0.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["entry"]["layer"] == "knowledge" for r in data)

    def test_list_by_layer(self, client: TestClient, store: MemoryStore) -> None:
        """GET /api/v1/memory/layer/{layer} — ro'yxat."""
        from zet.domain.memory import MemoryLayer

        store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim 1")
        store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim 2")
        store.add(layer=MemoryLayer.PERSONAL, content="shaxsiy")

        resp = client.get("/api/v1/memory/layer/knowledge")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert all(d["layer"] == "knowledge" for d in data)

    def test_cleanup(self, client: TestClient, store: MemoryStore) -> None:
        """POST /api/v1/memory/cleanup — eskirganlarni tozalash."""
        from datetime import UTC, datetime

        from zet.domain.memory import MemoryLayer

        past = datetime(2020, 1, 1, tzinfo=UTC)
        store.add(layer=MemoryLayer.SHORT_TERM, content="eskirgan", now=past)
        store.add(layer=MemoryLayer.KNOWLEDGE, content="faol")

        resp = client.post("/api/v1/memory/cleanup")
        assert resp.status_code == 200
        assert resp.json()["removed"] == 1

    def test_add_validation(self, client: TestClient) -> None:
        """Bo'sh matn rad etiladi."""
        resp = client.post(
            "/api/v1/memory",
            json={"layer": "knowledge", "content": ""},
        )
        assert resp.status_code == 422

    def test_add_invalid_layer(self, client: TestClient) -> None:
        """Noto'g'ri qatlam rad etiladi."""
        resp = client.post(
            "/api/v1/memory",
            json={"layer": "invalid", "content": "test"},
        )
        assert resp.status_code == 422
