"""Bo'lim 2 — Memory API testlari.

Tekshiriladi:
    - POST /api/v1/memory — yozuv qo'shish
    - GET /api/v1/memory/{id} — yozuv olish
    - PATCH /api/v1/memory/{id} — yozuv yangilash
    - DELETE /api/v1/memory/{id} — yozuv o'chirish
    - POST /api/v1/memory/search — qidirish
    - GET /api/v1/memory/layer/{layer} — qatlam bo'yicha
    - POST /api/v1/memory/cleanup — tozalash
    - POST /api/v1/memory — MemoryManager wire-in (policy + auto-tag)
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_db_session, get_memory_manager, get_memory_store
from zet.memory.manager import MemoryManager
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


class TestMemoryManagerWireIn:
    """POST /api/v1/memory `MemoryManager.aremember()` orqali o'tishini isbotlash.

    NEGA. Ilgari route `store.add()`ni to'g'ridan-to'g'ri chaqirar edi va
    `check_write` policy'sini chetlab o'tardi (`docs/AUDIT_GAPS` #4).
    Endi manager yagona darvoza — auto-tag pipeline shu tomondan ishlaydi.
    """

    def test_untrusted_blocked_from_knowledge(self, client: TestClient) -> None:
        """`untrusted` trust KNOWLEDGE qatlamga yoza olmaydi (policy manager orqali)."""
        resp = client.post(
            "/api/v1/memory",
            json={"layer": "knowledge", "content": "hacked"},
            headers={"X-Trust-Level": "untrusted"},
        )
        assert resp.status_code == 403

    def test_untrusted_allowed_short_term(self, client: TestClient) -> None:
        """`untrusted` trust SHORT_TERM ga yozishi mumkin."""
        resp = client.post(
            "/api/v1/memory",
            json={"layer": "short_term", "content": "vaqtinchalik yozuv"},
            headers={"X-Trust-Level": "untrusted"},
        )
        assert resp.status_code == 201
        # Manager `trust_level`ni chaqiruvchi trust'iga cheklaydi
        assert resp.json()["trust_level"] == "untrusted"

    def test_auto_tag_via_manager(self, client: TestClient) -> None:
        """Tegsiz yozuv — manager auto-tag orqali kalit-so'z chiqaradi."""
        resp = client.post(
            "/api/v1/memory",
            json={
                "layer": "knowledge",
                "content": "Python dasturlash tili sintaksisi",
                # Tag berilmagan — manager avtomatik ajratsin
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        # Manager `extract_keywords` orqali kamida bitta tag qo'shadi
        assert len(data["tags"]) > 0

    def test_manager_dependency_injected(self, client: TestClient, store: MemoryStore) -> None:
        """`get_memory_manager` override bilan almashtirilsa — route uni ishlatadi.

        Manager ustidan spy qo'yib, `aremember()` chaqirilganini kuzatamiz.
        """
        called: list[dict[str, object]] = []

        class SpyManager(MemoryManager):
            async def aremember(self, **kwargs: object) -> object:  # type: ignore[override]
                called.append(kwargs)
                return await super().aremember(**kwargs)  # type: ignore[arg-type]

        app = create_app()
        app.dependency_overrides[get_memory_store] = lambda: store
        app.dependency_overrides[get_memory_manager] = lambda: SpyManager(store=store)
        spy_client = TestClient(app)

        resp = spy_client.post(
            "/api/v1/memory",
            json={"layer": "knowledge", "content": "wire-in isboti"},
        )
        assert resp.status_code == 201
        assert len(called) == 1
        assert called[0]["layer"].value == "knowledge"
        assert called[0]["content"] == "wire-in isboti"
        assert called[0]["trust_level"] == "owner"


class TestMemoryAPIPersistence:
    """Default `get_memory_store` (PgMemoryStore) — real DB'ga yozadi.

    Ilgari `MemoryStore` doim in-memory edi (gap-analysis #5) — bu test
    default dependency zanjirini (session→owner→PgMemoryStore) `get_memory_store`
    override qilmasdan, faqat DB sessiyasini almashtirib tekshiradi.
    """

    @pytest.fixture()
    def pg_client(self, session: AsyncSession) -> TestClient:
        app = create_app()

        async def _session_override():
            yield session

        app.dependency_overrides[get_db_session] = _session_override
        return TestClient(app)

    async def test_write_then_read_via_pg_store(self, pg_client: TestClient) -> None:
        add_resp = pg_client.post(
            "/api/v1/memory",
            json={"layer": "knowledge", "content": "DB'ga yozilgan"},
        )
        assert add_resp.status_code == 201
        entry_id = add_resp.json()["id"]

        get_resp = pg_client.get(f"/api/v1/memory/{entry_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["content"] == "DB'ga yozilgan"

    async def test_search_via_pg_store(self, pg_client: TestClient) -> None:
        pg_client.post(
            "/api/v1/memory",
            json={"layer": "knowledge", "content": "Postgres persistensiya"},
        )
        resp = pg_client.post(
            "/api/v1/memory/search",
            json={"text": "Postgres", "min_similarity": 0.5},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
