"""Memory Manager — yuqori darajali xotira xizmati (Bo'lim 2).

MemoryStore + Policy + Summarizer ni birlashtiradi.

Qoidalar:
    - Yozishdan oldin policy tekshiruvi
    - Uzun matnlar avtomatik summarize qilinadi
    - Teglar avtomatik ajratiladi (agar berilmasa)
    - cleanup periodli chaqiriladi

Bog'liq qarorlar:
    V-14 — ruxsatga bog'liq ko'rinish
    V-15 — xotira versiyalash
    A-05 — ishonch darajalari
"""

from __future__ import annotations

import structlog

from zet.domain.memory import MemoryEntry, MemoryLayer, MemoryQuery, MemorySearchResult
from zet.memory.policy import check_read, check_write
from zet.memory.store import MemoryStore
from zet.memory.summarizer import extract_keywords, should_summarize, truncate_summary

log = structlog.get_logger(__name__)


class MemoryManager:
    """Xotira boshqaruvchisi.

    Barcha xotira operatsiyalari shu orqali o'tadi.
    Policy tekshiruvi, auto-summarize, auto-tag qo'shadi.
    """

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or MemoryStore()

    @property
    def store(self) -> MemoryStore:
        """Asosiy xotira do'koni."""
        return self._store

    def remember(
        self,
        *,
        layer: MemoryLayer,
        content: str,
        trust_level: str = "owner",
        summary: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        auto_summarize: bool = True,
        auto_tag: bool = True,
    ) -> MemoryEntry:
        """Yangi narsani eslab qolish.

        Policy tekshiruvidan o'tadi.
        Uzun matnlar avtomatik qisqartiriladi.
        Teglar berilmasa — matndan ajratiladi.

        Args:
            layer: Qatlam.
            content: Matn.
            trust_level: Manba ishonchliligi.
            summary: Qisqartma (None bo'lsa avtomatik).
            tags: Teglar (None bo'lsa avtomatik).
            source: Manba identifikatori.
            auto_summarize: Avtomatik qisqartirish.
            auto_tag: Avtomatik teg qo'shish.

        Returns:
            Yaratilgan xotira yozuvi.

        Raises:
            MemoryPolicyError: Ruxsat bo'lmasa.
        """
        # 1. Policy tekshiruvi
        check_write(trust_level, layer)

        # 2. Auto-summarize
        if auto_summarize and summary is None and should_summarize(content):
            summary = truncate_summary(content, max_length=200)

        # 3. Auto-tag
        if auto_tag and not tags:
            tags = extract_keywords(content, max_keywords=5)

        # 4. Yozuv yaratish
        entry = self._store.add(
            layer=layer,
            content=content,
            summary=summary,
            tags=tags or [],
            source=source,
            trust_level=trust_level,
        )

        log.info(
            "memory.remember",
            id=entry.id,
            layer=layer.value,
            trust_level=trust_level,
            auto_summary=summary is not None,
            tags_count=len(entry.tags),
        )

        return entry

    def recall(
        self,
        entry_id: str,
        *,
        trust_level: str = "owner",
    ) -> MemoryEntry | None:
        """Yozuvni esga olish (ID bo'yicha).

        Args:
            entry_id: Yozuv IDsi.
            trust_level: O'quvchi ishonchliligi.

        Returns:
            Yozuv yoki None.

        Raises:
            MemoryPolicyError: O'qish ruxsati bo'lmasa.
        """
        entry = self._store.get(entry_id)
        if entry is None:
            return None

        # Policy tekshiruvi
        check_read(trust_level, entry.layer)

        return entry

    def search(
        self,
        text: str,
        *,
        trust_level: str = "owner",
        layers: list[MemoryLayer] | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        min_similarity: float = 0.5,
    ) -> list[MemorySearchResult]:
        """Xotiradan qidirish.

        Faqat o'qish ruxsati bor qatlamlardan qidiradi.
        """
        from zet.memory.policy import readable_layers

        allowed = readable_layers(trust_level)

        # Faqat ruxsat etilgan qatlamlardan
        filtered_layers = [la for la in layers if la in allowed] if layers else list(allowed)

        if not filtered_layers:
            return []

        query = MemoryQuery(
            text=text,
            layers=filtered_layers,
            tags=tags,
            limit=limit,
            min_similarity=min_similarity,
        )

        return self._store.search(query)

    def update(
        self,
        entry_id: str,
        *,
        content: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        trust_level: str = "owner",
    ) -> MemoryEntry | None:
        """Yozuvni yangilash.

        Raises:
            MemoryPolicyError: Yozish ruxsati bo'lmasa.
        """
        entry = self._store.get(entry_id)
        if entry is None:
            return None

        check_write(trust_level, entry.layer)

        return self._store.update(
            entry_id,
            content=content,
            summary=summary,
            tags=tags,
        )

    def forget(
        self,
        entry_id: str,
        *,
        trust_level: str = "owner",
    ) -> bool:
        """Yozuvni unutish (soft delete).

        Raises:
            MemoryPolicyError: Yozish ruxsati bo'lmasa.
        """
        entry = self._store.get(entry_id)
        if entry is None:
            return False

        check_write(trust_level, entry.layer)

        result = self._store.delete(entry_id)
        if result:
            log.info("memory.forget", id=entry_id)
        return result

    def cleanup(self) -> int:
        """Eskirgan yozuvlarni tozalash."""
        count = self._store.cleanup_expired()
        if count > 0:
            log.info("memory.manager.cleanup", removed=count)
        return count

    @property
    def count(self) -> int:
        """Faol yozuvlar soni."""
        return self._store.count
