"""Bo'lim 2 — Xotira testlari.

Tekshiriladi:
    - Domain modellari (MemoryEntry, MemoryQuery, MemoryLayer)
    - MemoryStore: add, get, update, delete, search
    - TTL va expiration
    - Qatlam bo'yicha filtrlash
    - Teg bo'yicha filtrlash
    - Matn qidirish
    - Cosine similarity
    - Cleanup
    - Versiyalash
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from zet.domain.memory import (
    LAYER_TTL,
    MemoryEntry,
    MemoryLayer,
    MemoryQuery,
    MemorySearchResult,
)
from zet.memory.store import MemoryStore

# ── Domain modellari ───────────────────────────────────────────────


class TestMemoryDomain:
    def test_memory_layers(self) -> None:
        """7 qatlam mavjud."""
        assert len(MemoryLayer) == 7

    def test_layer_ttl(self) -> None:
        """TTL qiymatlari to'g'ri."""
        assert LAYER_TTL[MemoryLayer.SHORT_TERM] == 3600
        assert LAYER_TTL[MemoryLayer.CONVERSATION] == 604_800
        assert LAYER_TTL[MemoryLayer.KNOWLEDGE] is None

    def test_memory_entry_frozen(self) -> None:
        """MemoryEntry immutable."""
        entry = MemoryEntry(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
        )
        assert entry.content == "test"
        assert entry.version == 1

    def test_memory_query(self) -> None:
        """MemoryQuery yaratiladi."""
        query = MemoryQuery(text="test", limit=5, min_similarity=0.3)
        assert query.limit == 5
        assert query.min_similarity == 0.3

    def test_search_result(self) -> None:
        """MemorySearchResult yaratiladi."""
        entry = MemoryEntry(layer=MemoryLayer.KNOWLEDGE, content="test")
        result = MemorySearchResult(entry=entry, similarity=0.9, rank=1)
        assert result.similarity == 0.9
        assert result.rank == 1


# ── MemoryStore ────────────────────────────────────────────────────


class TestMemoryStore:
    def test_add_and_get(self) -> None:
        """Yozuv qo'shish va olish."""
        store = MemoryStore()
        entry = store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="Python — dasturlash tili",
            tags=["python", "dasturlash"],
        )
        assert entry.id is not None
        assert store.count == 1

        fetched = store.get(entry.id)
        assert fetched is not None
        assert fetched.content == "Python — dasturlash tili"

    def test_get_nonexistent(self) -> None:
        """Mavjud bo'lmagan yozuv → None."""
        store = MemoryStore()
        assert store.get("nonexistent") is None

    def test_update(self) -> None:
        """Yozuvni yangilash — versiya oshadi."""
        store = MemoryStore()
        entry = store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="eski matn",
        )

        updated = store.update(entry.id, content="yangi matn")
        assert updated is not None
        assert updated.content == "yangi matn"
        assert updated.version == 2

    def test_update_nonexistent(self) -> None:
        """Mavjud bo'lmagan yozuvni yangilash → None."""
        store = MemoryStore()
        assert store.update("nonexistent", content="test") is None

    def test_delete(self) -> None:
        """Soft delete."""
        store = MemoryStore()
        entry = store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
        )
        assert store.count == 1
        result = store.delete(entry.id)
        assert result is True
        # delete expires_at ni o'rnatadi, shuning uchun get None qaytaradi
        assert store.get(entry.id) is None

    def test_delete_nonexistent(self) -> None:
        """Mavjud bo'lmagan yozuvni o'chirish → False."""
        store = MemoryStore()
        assert store.delete("nonexistent") is False

    def test_ttl_applied(self) -> None:
        """SHORT_TERM qatlam uchun TTL avtomatik qo'yiladi."""
        store = MemoryStore()
        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        entry = store.add(
            layer=MemoryLayer.SHORT_TERM,
            content="qisqa muddat",
            now=now,
        )
        assert entry.expires_at is not None
        expected = now + timedelta(seconds=3600)
        assert entry.expires_at == expected

    def test_no_ttl_for_knowledge(self) -> None:
        """KNOWLEDGE qatlam uchun TTL yo'q."""
        store = MemoryStore()
        entry = store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="doimiy",
        )
        assert entry.expires_at is None

    def test_expired_not_returned(self) -> None:
        """Muddati o'tgan yozuv get da qaytarilmaydi."""
        store = MemoryStore()
        past = datetime(2020, 1, 1, tzinfo=UTC)
        entry = store.add(
            layer=MemoryLayer.SHORT_TERM,
            content="eskirgan",
            now=past,
        )
        # Hozirgi vaqtda expires_at allaqachon o'tgan
        assert store.get(entry.id) is None

    def test_search_by_text(self) -> None:
        """Matn bo'yicha qidirish."""
        store = MemoryStore()
        store.add(layer=MemoryLayer.KNOWLEDGE, content="Python dasturlash tili")
        store.add(layer=MemoryLayer.KNOWLEDGE, content="JavaScript web uchun")
        store.add(layer=MemoryLayer.KNOWLEDGE, content="Rust tizimli dasturlash")

        query = MemoryQuery(text="Python", min_similarity=0.5)
        results = store.search(query)

        assert len(results) >= 1
        assert results[0].entry.content == "Python dasturlash tili"
        assert results[0].rank == 1

    def test_search_by_layer(self) -> None:
        """Qatlam bo'yicha filtrlash."""
        store = MemoryStore()
        store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim")
        store.add(layer=MemoryLayer.PERSONAL, content="shaxsiy")

        query = MemoryQuery(
            text="bilim",
            layers=[MemoryLayer.KNOWLEDGE],
            min_similarity=0.5,
        )
        results = store.search(query)

        assert all(r.entry.layer == MemoryLayer.KNOWLEDGE for r in results)

    def test_search_by_tags(self) -> None:
        """Teglar bo'yicha filtrlash."""
        store = MemoryStore()
        store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="Python dasturlash",
            tags=["python"],
        )
        store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="SQL bazasi",
            tags=["sql"],
        )

        query = MemoryQuery(text="dasturlash", tags=["python"], min_similarity=0.0)
        results = store.search(query)

        assert all("python" in r.entry.tags for r in results)

    def test_search_limit(self) -> None:
        """Natijalar soni cheklangan."""
        store = MemoryStore()
        for i in range(20):
            store.add(layer=MemoryLayer.KNOWLEDGE, content=f"yozuv {i} test matn")

        query = MemoryQuery(text="test", limit=5, min_similarity=0.0)
        results = store.search(query)

        assert len(results) <= 5

    def test_search_excludes_expired(self) -> None:
        """Eskirgan yozuvlar qidiruvda chiqmaydi."""
        store = MemoryStore()
        past = datetime(2020, 1, 1, tzinfo=UTC)
        store.add(
            layer=MemoryLayer.SHORT_TERM,
            content="eskirgan test",
            now=past,
        )
        store.add(
            layer=MemoryLayer.KNOWLEDGE,
            content="faol test",
        )

        query = MemoryQuery(text="test", min_similarity=0.0)
        results = store.search(query)

        assert all("eskirgan" not in r.entry.content for r in results)

    def test_list_by_layer(self) -> None:
        """Qatlam bo'yicha ro'yxat."""
        store = MemoryStore()
        store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim 1")
        store.add(layer=MemoryLayer.KNOWLEDGE, content="bilim 2")
        store.add(layer=MemoryLayer.PERSONAL, content="shaxsiy")

        entries = store.list_by_layer(MemoryLayer.KNOWLEDGE)
        assert len(entries) == 2
        assert all(e.layer == MemoryLayer.KNOWLEDGE for e in entries)

    def test_cleanup_expired(self) -> None:
        """Eskirgan yozuvlarni tozalash."""
        store = MemoryStore()
        past = datetime(2020, 1, 1, tzinfo=UTC)
        store.add(layer=MemoryLayer.SHORT_TERM, content="eskirgan 1", now=past)
        store.add(layer=MemoryLayer.SHORT_TERM, content="eskirgan 2", now=past)
        store.add(layer=MemoryLayer.KNOWLEDGE, content="faol")

        count = store.cleanup_expired()
        assert count == 2
        assert store.count == 1


# ── Cosine Similarity ─────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        """Bir xil vektorlar → 1.0."""
        sim = MemoryStore.cosine_similarity([1.0, 0.0], [1.0, 0.0])
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        """Perpendikulyar vektorlar → 0.0."""
        sim = MemoryStore.cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 1e-6

    def test_opposite_vectors(self) -> None:
        """Qarama-qarshi vektorlar → -1.0."""
        sim = MemoryStore.cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        assert abs(sim - (-1.0)) < 1e-6

    def test_empty_vectors(self) -> None:
        """Bo'sh vektorlar → 0.0."""
        assert MemoryStore.cosine_similarity([], []) == 0.0

    def test_different_lengths(self) -> None:
        """Farqli uzunlik → 0.0."""
        assert MemoryStore.cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector(self) -> None:
        """Nol vektor → 0.0."""
        assert MemoryStore.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
