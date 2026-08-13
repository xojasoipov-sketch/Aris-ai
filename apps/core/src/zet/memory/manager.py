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

import inspect
from typing import Any

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

    `store` — sinxron `MemoryStore` (in-memory) yoki asinxron `PgMemoryStore`
    (DB-backed) bo'lishi mumkin. Sinxron chaqiruvchilar `remember()`, asinxron
    (API route) `aremember()` ishlatadi. Har ikkalasi bir xil policy/summarize/
    tag pipeline'idan o'tadi — ilgari API route `store.add()`ni to'g'ridan-
    to'g'ri chaqirib policy'ni chetlab o'tardi.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._store = store if store is not None else MemoryStore()

    @property
    def store(self) -> Any:
        """Asosiy xotira do'koni."""
        return self._store

    def _prepare_write(
        self,
        *,
        layer: MemoryLayer,
        content: str,
        trust_level: str,
        summary: str | None,
        tags: list[str] | None,
        source: str | None,
        auto_summarize: bool,
        auto_tag: bool,
    ) -> dict[str, Any]:
        """Policy tekshiruvi + auto-summarize + auto-tag — `store.add()` kwargs qaytaradi.

        NEGA alohida yordamchi. `remember()` va `aremember()` ikkalasi bir xil
        pipeline'dan o'tishi kerak — mantiqni sinxron/asinxron oxirgi
        `store.add()`ga qarab ikki nusxada saqlash siljish xavfini keltiradi.
        """
        # 1. Policy tekshiruvi
        check_write(trust_level, layer)

        # 2. Auto-summarize
        if auto_summarize and summary is None and should_summarize(content):
            summary = truncate_summary(content, max_length=200)

        # 3. Auto-tag
        if auto_tag and not tags:
            tags = extract_keywords(content, max_keywords=5)

        return {
            "layer": layer,
            "content": content,
            "summary": summary,
            "tags": tags or [],
            "source": source,
            "trust_level": trust_level,
        }

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
        """Yangi narsani eslab qolish (SINXRON store uchun).

        Policy tekshiruvidan o'tadi.
        Uzun matnlar avtomatik qisqartiriladi.
        Teglar berilmasa — matndan ajratiladi.

        Raises:
            MemoryPolicyError: Ruxsat bo'lmasa.
            TypeError: `store.add()` awaitable qaytarsa (asinxron store) —
                bunda `aremember()` ishlatilishi kerak.
        """
        kwargs = self._prepare_write(
            layer=layer,
            content=content,
            trust_level=trust_level,
            summary=summary,
            tags=tags,
            source=source,
            auto_summarize=auto_summarize,
            auto_tag=auto_tag,
        )
        result = self._store.add(**kwargs)
        if inspect.isawaitable(result):
            # Aks holda coroutine sirtga sizib chiqadi va chaqiruvchi kutilmagan
            # tarzda MemoryEntry o'rniga Coroutine oladi. Kutilmagan awaitable'ni
            # avval close() bilan yopamiz — GC vaqtida "coroutine never awaited"
            # ogohlantirishini yaratmasin.
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TypeError(
                "MemoryManager.remember() sinxron store bilan ishlaydi; "
                "asinxron store uchun aremember() ishlating."
            )

        log.info(
            "memory.remember",
            id=result.id,
            layer=layer.value,
            trust_level=trust_level,
            auto_summary=summary is not None,
            tags_count=len(result.tags),
        )
        return result

    async def aremember(
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
        """Yangi narsani eslab qolish — sinxron va asinxron store'ga ishlaydi.

        `PgMemoryStore.add()` (async) yoki `MemoryStore.add()` (sync) — har
        ikkalasi bilan bir xil ishlaydi. API route (`api/routes/memory.py`)
        shu orqali policy'ni chetlab o'tmasdan yozadi.
        """
        kwargs = self._prepare_write(
            layer=layer,
            content=content,
            trust_level=trust_level,
            summary=summary,
            tags=tags,
            source=source,
            auto_summarize=auto_summarize,
            auto_tag=auto_tag,
        )
        result = self._store.add(**kwargs)
        entry: MemoryEntry = await result if inspect.isawaitable(result) else result

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
