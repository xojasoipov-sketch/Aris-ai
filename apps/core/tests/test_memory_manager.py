"""Bo'lim 2 — Memory Manager testlari.

Tekshiriladi:
    - remember — yozish + policy + auto-summarize + auto-tag
    - recall — o'qish + policy
    - search — policy filtri bilan
    - update — yozish policy bilan
    - forget — o'chirish + policy
    - cleanup — eskirganlarni tozalash
"""

from __future__ import annotations

import pytest

from zet.domain.memory import MemoryLayer
from zet.memory.manager import MemoryManager
from zet.memory.policy import MemoryPolicyError


@pytest.fixture
def manager() -> MemoryManager:
    return MemoryManager()


class TestRemember:
    def test_basic_remember(self, manager: MemoryManager) -> None:
        """Oddiy eslab qolish."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="Python dasturlash tili",
        )
        assert entry.content == "Python dasturlash tili"
        assert entry.layer == MemoryLayer.KNOWLEDGE
        assert manager.count == 1

    def test_auto_tag(self, manager: MemoryManager) -> None:
        """Teglar avtomatik ajratiladi."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="Python dasturlash tilini o'rganish",
        )
        assert len(entry.tags) > 0
        assert "python" in entry.tags

    def test_auto_summarize(self, manager: MemoryManager) -> None:
        """Uzun matn avtomatik qisqartiriladi."""
        long_content = "Python " * 200
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content=long_content,
        )
        assert entry.summary is not None
        assert len(entry.summary) <= 210  # 200 + "..."

    def test_no_auto_summarize_short(self, manager: MemoryManager) -> None:
        """Qisqa matn qisqartirilmaydi."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="qisqa matn",
        )
        assert entry.summary is None

    def test_manual_tags(self, manager: MemoryManager) -> None:
        """Qo'lda berilgan teglar saqlanadi."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
            tags=["custom_tag"],
        )
        assert entry.tags == ["custom_tag"]

    def test_policy_blocks_untrusted(self, manager: MemoryManager) -> None:
        """Untrusted knowledge ga yoza olmaydi."""
        with pytest.raises(MemoryPolicyError):
            manager.remember(
                layer=MemoryLayer.KNOWLEDGE,
                content="test",
                trust_level="untrusted",
            )

    def test_policy_allows_untrusted_short_term(self, manager: MemoryManager) -> None:
        """Untrusted short_term ga yozishi mumkin."""
        entry = manager.remember(
            layer=MemoryLayer.SHORT_TERM,
            content="vaqtinchalik",
            trust_level="untrusted",
        )
        assert entry.layer == MemoryLayer.SHORT_TERM


class TestRecall:
    def test_basic_recall(self, manager: MemoryManager) -> None:
        """Oddiy esga olish."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
        )
        recalled = manager.recall(entry.id)
        assert recalled is not None
        assert recalled.content == "test"

    def test_recall_nonexistent(self, manager: MemoryManager) -> None:
        """Mavjud bo'lmagan yozuv → None."""
        assert manager.recall("nonexistent") is None

    def test_recall_policy_blocks(self, manager: MemoryManager) -> None:
        """System personal ni o'qiy olmaydi."""
        entry = manager.remember(
            layer=MemoryLayer.PERSONAL,
            content="shaxsiy",
            trust_level="owner",
        )
        with pytest.raises(MemoryPolicyError):
            manager.recall(entry.id, trust_level="system")


class TestSearch:
    def test_basic_search(self, manager: MemoryManager) -> None:
        """Oddiy qidirish."""
        manager.remember(layer=MemoryLayer.KNOWLEDGE, content="Python dasturlash")
        results = manager.search("Python")
        assert len(results) >= 1

    def test_search_policy_filter(self, manager: MemoryManager) -> None:
        """Untrusted faqat ruxsat etilgan qatlamlardan ko'radi."""
        manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="umumiy bilim test",
        )
        manager.remember(
            layer=MemoryLayer.PERSONAL,
            content="shaxsiy bilim test",
        )

        # untrusted knowledge ni ko'radi
        results = manager.search("test", trust_level="untrusted", min_similarity=0.0)
        layers = {r.entry.layer for r in results}
        assert MemoryLayer.PERSONAL not in layers

    def test_search_empty_for_unknown_trust(self, manager: MemoryManager) -> None:
        """Noma'lum trust_level uchun hech narsa topilmaydi."""
        manager.remember(layer=MemoryLayer.KNOWLEDGE, content="test")
        results = manager.search("test", trust_level="alien")
        assert len(results) == 0


class TestUpdate:
    def test_basic_update(self, manager: MemoryManager) -> None:
        """Oddiy yangilash."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="eski",
        )
        updated = manager.update(entry.id, content="yangi")
        assert updated is not None
        assert updated.content == "yangi"
        assert updated.version == 2

    def test_update_policy_blocks(self, manager: MemoryManager) -> None:
        """Untrusted knowledge ni yangilay olmaydi."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
        )
        with pytest.raises(MemoryPolicyError):
            manager.update(entry.id, content="hacked", trust_level="untrusted")

    def test_update_nonexistent(self, manager: MemoryManager) -> None:
        """Mavjud bo'lmagan yozuv → None."""
        assert manager.update("nonexistent", content="test") is None


class TestForget:
    def test_basic_forget(self, manager: MemoryManager) -> None:
        """Oddiy unutish."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
        )
        assert manager.forget(entry.id) is True
        assert manager.recall(entry.id) is None

    def test_forget_policy_blocks(self, manager: MemoryManager) -> None:
        """Untrusted knowledge ni o'chira olmaydi."""
        entry = manager.remember(
            layer=MemoryLayer.KNOWLEDGE,
            content="test",
        )
        with pytest.raises(MemoryPolicyError):
            manager.forget(entry.id, trust_level="untrusted")

    def test_forget_nonexistent(self, manager: MemoryManager) -> None:
        """Mavjud bo'lmagan yozuv → False."""
        assert manager.forget("nonexistent") is False


class TestAremember:
    """`aremember()` sinxron va asinxron store bilan ishlashini isbotlash.

    NEGA. `api/routes/memory.py::add_memory` `PgMemoryStore` (async) bilan
    ishlaydi — `remember()` (sync) uni qo'llab-quvvatlamaydi. Route
    `aremember()`ga bog'liq, shu sabab u erda ham qamrov kerak.
    """

    async def test_aremember_with_sync_store(self, manager: MemoryManager) -> None:
        """`aremember()` sinxron store bilan ham ishlaydi."""
        entry = await manager.aremember(
            layer=MemoryLayer.KNOWLEDGE,
            content="asinxron eslab qolish",
        )
        assert entry.content == "asinxron eslab qolish"
        assert manager.count == 1

    async def test_aremember_with_async_store(self) -> None:
        """`aremember()` awaitable qaytaruvchi store bilan ishlaydi."""
        from zet.domain.memory import MemoryEntry

        recorded: list[dict[str, object]] = []

        class FakeAsyncStore:
            async def add(self, **kwargs: object) -> MemoryEntry:
                recorded.append(kwargs)
                return MemoryEntry(
                    id="fake-id",
                    layer=kwargs["layer"],  # type: ignore[arg-type]
                    content=kwargs["content"],  # type: ignore[arg-type]
                    summary=kwargs.get("summary"),  # type: ignore[arg-type]
                    tags=list(kwargs.get("tags") or []),  # type: ignore[arg-type]
                    source=kwargs.get("source"),  # type: ignore[arg-type]
                    trust_level=kwargs["trust_level"],  # type: ignore[arg-type]
                )

        async_manager = MemoryManager(store=FakeAsyncStore())
        entry = await async_manager.aremember(
            layer=MemoryLayer.KNOWLEDGE,
            content="async store yozuvi",
        )
        assert entry.id == "fake-id"
        assert len(recorded) == 1
        assert recorded[0]["content"] == "async store yozuvi"

    async def test_aremember_enforces_policy(self, manager: MemoryManager) -> None:
        """`aremember()` `check_write`ni chetlab o'tmaydi."""
        with pytest.raises(MemoryPolicyError):
            await manager.aremember(
                layer=MemoryLayer.KNOWLEDGE,
                content="ruxsatsiz",
                trust_level="untrusted",
            )

    def test_remember_rejects_async_store(self) -> None:
        """Sinxron `remember()` awaitable qaytaradigan store bilan aniq xato."""
        from zet.domain.memory import MemoryEntry

        class FakeAsyncStore:
            async def add(self, **_kwargs: object) -> MemoryEntry:  # pragma: no cover
                raise AssertionError("shouldn't be awaited in sync path")

        sync_bad_manager = MemoryManager(store=FakeAsyncStore())
        with pytest.raises(TypeError, match="aremember"):
            sync_bad_manager.remember(
                layer=MemoryLayer.KNOWLEDGE,
                content="test",
            )


class TestCleanup:
    def test_cleanup(self, manager: MemoryManager) -> None:
        """Eskirgan yozuvlarni tozalash."""
        from datetime import UTC, datetime

        past = datetime(2020, 1, 1, tzinfo=UTC)
        manager.store.add(
            layer=MemoryLayer.SHORT_TERM,
            content="eskirgan",
            now=past,
        )
        manager.remember(layer=MemoryLayer.KNOWLEDGE, content="faol")

        count = manager.cleanup()
        assert count == 1
        assert manager.count == 1
