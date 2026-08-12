"""PgMemoryStore testlari — DB-backed xotira (gap-analysis #5).

`conftest.py`dagi `session`/`owner` fixture'lari orqali real (in-memory
sqlite) DB'ga yozadi/o'qiydi — ma'lumotlar sessiya davomida saqlanishini
tekshiradi.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.owner import Owner
from zet.domain.memory import MemoryLayer, MemoryQuery
from zet.memory.pg_store import PgMemoryStore


@pytest.fixture()
def store(session: AsyncSession, owner: Owner) -> PgMemoryStore:
    return PgMemoryStore(session, owner_id=owner.id)


class _FakeEmbedder:
    """Oldindan belgilangan matn->vektor xaritasi; noma'lum matn uchun `None`."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float] | None:
        self.calls.append(text)
        return self._vectors.get(text)


class _AlwaysNoneEmbedder:
    """Ollama ulanmaganini simulyatsiya qiladi — har doim `None`."""

    async def embed(self, text: str) -> list[float] | None:
        return None


class TestAdd:
    async def test_add_returns_entry(self, store: PgMemoryStore) -> None:
        entry = await store.add(layer=MemoryLayer.KNOWLEDGE, content="Python haqida")
        assert entry.id is not None
        assert entry.content == "Python haqida"
        assert entry.version == 1

    async def test_add_computes_ttl(self, store: PgMemoryStore) -> None:
        now = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
        entry = await store.add(layer=MemoryLayer.SHORT_TERM, content="vaqtinchalik", now=now)
        assert entry.expires_at is not None
        assert entry.expires_at > now

    async def test_add_no_ttl_for_knowledge(self, store: PgMemoryStore) -> None:
        entry = await store.add(layer=MemoryLayer.KNOWLEDGE, content="doimiy")
        assert entry.expires_at is None


class TestGet:
    async def test_get_persists_across_reads(self, store: PgMemoryStore) -> None:
        """Yozilgan yozuv keyinroq (bir xil sessiyada) o'qib olinadi."""
        created = await store.add(layer=MemoryLayer.PROJECT, content="loyiha")
        fetched = await store.get(created.id)
        assert fetched is not None
        assert fetched.content == "loyiha"

    async def test_get_missing_returns_none(self, store: PgMemoryStore) -> None:
        import uuid

        assert await store.get(str(uuid.uuid4())) is None

    async def test_get_invalid_id_returns_none(self, store: PgMemoryStore) -> None:
        assert await store.get("not-a-uuid") is None

    async def test_get_wrong_owner_returns_none(self, session: AsyncSession, owner: Owner) -> None:
        store_a = PgMemoryStore(session, owner_id=owner.id)
        entry = await store_a.add(layer=MemoryLayer.PERSONAL, content="maxfiy")

        other_owner = Owner(external_id="other-owner")
        session.add(other_owner)
        await session.flush()
        store_b = PgMemoryStore(session, owner_id=other_owner.id)

        assert await store_b.get(entry.id) is None


class TestUpdate:
    async def test_update_increments_version(self, store: PgMemoryStore) -> None:
        entry = await store.add(layer=MemoryLayer.TASK, content="v1")
        updated = await store.update(entry.id, content="v2")
        assert updated is not None
        assert updated.version == 2
        assert updated.content == "v2"

    async def test_update_missing_returns_none(self, store: PgMemoryStore) -> None:
        import uuid

        assert await store.update(str(uuid.uuid4()), content="x") is None


class TestDelete:
    async def test_delete_soft_deletes(self, store: PgMemoryStore) -> None:
        entry = await store.add(layer=MemoryLayer.TASK, content="o'chiriladi")
        assert await store.delete(entry.id) is True
        assert await store.get(entry.id) is None

    async def test_delete_missing_returns_false(self, store: PgMemoryStore) -> None:
        import uuid

        assert await store.delete(str(uuid.uuid4())) is False


class TestSearch:
    async def test_search_substring_match(self, store: PgMemoryStore) -> None:
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="Python dasturlash tili")
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="JavaScript veb uchun")

        results = await store.search(MemoryQuery(text="Python", min_similarity=0.5))

        assert len(results) == 1
        assert "Python" in results[0].entry.content

    async def test_search_filters_by_layer(self, store: PgMemoryStore) -> None:
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="Python bilim")
        await store.add(layer=MemoryLayer.PERSONAL, content="Python shaxsiy")

        results = await store.search(
            MemoryQuery(text="Python", layers=[MemoryLayer.KNOWLEDGE], min_similarity=0.5)
        )

        assert len(results) == 1
        assert results[0].entry.layer == MemoryLayer.KNOWLEDGE

    async def test_search_respects_limit(self, store: PgMemoryStore) -> None:
        for i in range(5):
            await store.add(layer=MemoryLayer.KNOWLEDGE, content=f"item {i} test")

        results = await store.search(MemoryQuery(text="test", limit=2, min_similarity=0.1))
        assert len(results) == 2


class TestListByLayer:
    async def test_list_by_layer(self, store: PgMemoryStore) -> None:
        await store.add(layer=MemoryLayer.TASK, content="vazifa 1")
        await store.add(layer=MemoryLayer.TASK, content="vazifa 2")
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim")

        entries = await store.list_by_layer(MemoryLayer.TASK)
        assert len(entries) == 2


class TestCleanupExpired:
    async def test_cleanup_removes_expired(self, store: PgMemoryStore) -> None:
        past = datetime(2020, 1, 1, tzinfo=UTC)
        entry = await store.add(layer=MemoryLayer.SHORT_TERM, content="eski", now=past)

        removed = await store.cleanup_expired(now=datetime.now(tz=UTC))

        assert removed == 1
        assert await store.get(entry.id) is None

    async def test_cleanup_keeps_active(self, store: PgMemoryStore) -> None:
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="doimiy")
        removed = await store.cleanup_expired()
        assert removed == 0


class TestCount:
    async def test_count_active_entries(self, store: PgMemoryStore) -> None:
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="a")
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="b")
        assert await store.count() == 2

    async def test_count_excludes_deleted(self, store: PgMemoryStore) -> None:
        entry = await store.add(layer=MemoryLayer.KNOWLEDGE, content="a")
        await store.delete(entry.id)
        assert await store.count() == 0


class TestEmbeddingIntegration:
    """`embedder` sozlangan bo'lsa vektor avtomatik hisoblanadi/ishlatiladi."""

    async def test_add_computes_and_stores_embedding(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        embedder = _FakeEmbedder({"Mushuklar haqida": [1.0, 0.0]})
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        entry = await store.add(layer=MemoryLayer.KNOWLEDGE, content="Mushuklar haqida")

        assert entry.embedding == [1.0, 0.0]
        assert embedder.calls == ["Mushuklar haqida"]

    async def test_explicit_embedding_skips_provider_call(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        embedder = _FakeEmbedder({})
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        entry = await store.add(layer=MemoryLayer.KNOWLEDGE, content="matn", embedding=[0.5, 0.5])

        assert entry.embedding == [0.5, 0.5]
        assert embedder.calls == []

    async def test_add_survives_provider_returning_none(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Ollama ulanmagan bo'lsa ham (fail-open) yozuv saqlanadi, embedding'siz."""
        store = PgMemoryStore(session, owner_id=owner.id, embedder=_AlwaysNoneEmbedder())

        entry = await store.add(layer=MemoryLayer.KNOWLEDGE, content="matn")

        assert entry.embedding is None

    async def test_update_recomputes_embedding_for_new_content(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        embedder = _FakeEmbedder({"eski": [1.0, 0.0], "yangi": [0.0, 1.0]})
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        entry = await store.add(layer=MemoryLayer.TASK, content="eski")
        assert entry.embedding == [1.0, 0.0]

        updated = await store.update(entry.id, content="yangi")
        assert updated is not None
        assert updated.embedding == [0.0, 1.0]

    async def test_search_finds_semantically_close_without_keyword_overlap(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Kalit-so'z mos kelmasa ham, semantik yaqin bo'lsa yuqori reytingda chiqadi."""
        vectors = {
            "Mushuklar mustaqil hayvonlar": [1.0, 0.0],
            "Itlar sodiq hayvonlar": [0.0, 1.0],
            "Pisiylar haqida gap": [0.95, 0.05],  # so'rov — "mushuk" so'zi yo'q
        }
        embedder = _FakeEmbedder(vectors)
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        await store.add(layer=MemoryLayer.KNOWLEDGE, content="Mushuklar mustaqil hayvonlar")
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="Itlar sodiq hayvonlar")

        results = await store.search(MemoryQuery(text="Pisiylar haqida gap", min_similarity=0.1))

        assert len(results) >= 1
        assert "Mushuklar" in results[0].entry.content

    async def test_search_falls_back_to_keyword_when_embedder_returns_none(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Ollama qidiruv vaqtida ulanmagan bo'lsa ham — kalit-so'z bo'yicha ishlaydi."""
        store = PgMemoryStore(session, owner_id=owner.id, embedder=_AlwaysNoneEmbedder())
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="Python dasturlash")

        results = await store.search(MemoryQuery(text="Python", min_similarity=0.5))

        assert len(results) == 1

    async def test_search_without_embedder_unaffected(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """`embedder=None` (default) — avvalgi xatti-harakat o'zgarmaydi."""
        store = PgMemoryStore(session, owner_id=owner.id)
        await store.add(layer=MemoryLayer.KNOWLEDGE, content="Python dasturlash")

        results = await store.search(MemoryQuery(text="Python", min_similarity=0.5))

        assert len(results) == 1

    async def test_search_ignores_entries_without_stored_embedding(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Eski (embedding'siz) yozuvlar semantik so'rovda ham qidiruvdan tushib qolmaydi."""
        embedder = _FakeEmbedder({"so'rov matni": [1.0, 0.0]})
        store = PgMemoryStore(session, owner_id=owner.id, embedder=embedder)

        # Embedder'siz qo'shilgan — embedding yo'q
        no_embed_store = PgMemoryStore(session, owner_id=owner.id)
        await no_embed_store.add(layer=MemoryLayer.KNOWLEDGE, content="so'rov matni ustida")

        results = await store.search(MemoryQuery(text="so'rov matni", min_similarity=0.5))
        assert len(results) == 1  # kalit-so'z orqali baribir topiladi
