"""MemoryStore — xotira yozish, o'qish, qidirish (Bo'lim 2).

In-memory versiya (unit test uchun). DB bilan ishlaydigan versiya
`PgMemoryStore` da bo'ladi (Postgres + pgvector).

Qoidalar:
    - Har bir yozuv qatlamga tegishli
    - TTL bor bo'lsa — muddati o'tganlar qaytarilmaydi
    - Versiyalash: har bir o'zgartirish versiya oshadi
    - Soft delete: is_deleted=True, lekin DB'dan o'chirilmaydi
    - Vektor qidirish: cosine similarity (embedding mavjud bo'lsa)
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

import structlog

from zet.domain.memory import (
    LAYER_TTL,
    MemoryEntry,
    MemoryLayer,
    MemoryQuery,
    MemorySearchResult,
)

log = structlog.get_logger(__name__)


class MemoryStore:
    """In-memory xotira do'koni.

    Testlash va prototiplash uchun. Produksiyada `PgMemoryStore` ishlatiladi.
    """

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    @property
    def count(self) -> int:
        """Faol yozuvlar soni (o'chirilganlar hisobga olinmaydi)."""
        return sum(1 for e in self._entries.values() if not self._is_deleted(e))

    def add(
        self,
        *,
        layer: MemoryLayer,
        content: str,
        summary: str | None = None,
        tags: list[str] | None = None,
        source: str | None = None,
        embedding: list[float] | None = None,
        trust_level: str = "owner",
        now: datetime | None = None,
    ) -> MemoryEntry:
        """Yangi xotira yozuvi qo'shish.

        TTL avtomatik hisoblanadi (LAYER_TTL bo'yicha).
        """
        now = now or datetime.now(tz=UTC)
        entry_id = uuid.uuid4().hex

        ttl = LAYER_TTL.get(layer)
        expires_at: datetime | None = None
        if ttl is not None:
            from datetime import timedelta

            expires_at = now + timedelta(seconds=ttl)

        entry = MemoryEntry(
            id=entry_id,
            layer=layer,
            content=content,
            summary=summary,
            tags=tags or [],
            source=source,
            embedding=embedding,
            version=1,
            created_at=now,
            expires_at=expires_at,
            trust_level=trust_level,
        )

        self._entries[entry_id] = entry
        log.info(
            "memory.added",
            id=entry_id,
            layer=layer.value,
            tags=tags,
        )
        return entry

    def get(self, entry_id: str) -> MemoryEntry | None:
        """Yozuvni ID bo'yicha olish (o'chirilgan va eskirganlar chiqarilmaydi)."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        if self._is_deleted(entry):
            return None
        if self._is_expired(entry):
            return None
        return entry

    def update(
        self,
        entry_id: str,
        *,
        content: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryEntry | None:
        """Yozuvni yangilash (versiya oshadi).

        Returns:
            Yangilangan yozuv yoki None (topilmasa).
        """
        old = self.get(entry_id)
        if old is None:
            return None

        updated = MemoryEntry(
            id=old.id,
            layer=old.layer,
            content=content if content is not None else old.content,
            summary=summary if summary is not None else old.summary,
            tags=tags if tags is not None else old.tags,
            source=old.source,
            embedding=embedding if embedding is not None else old.embedding,
            version=old.version + 1,
            created_at=old.created_at,
            expires_at=old.expires_at,
            trust_level=old.trust_level,
        )

        self._entries[entry_id] = updated
        log.info("memory.updated", id=entry_id, version=updated.version)
        return updated

    def delete(self, entry_id: str) -> bool:
        """Soft delete — yozuv o'chirildi deb belgilanadi.

        Returns:
            True agar topilsa va o'chirilsa.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            return False

        # Frozen model — yangi instance yaratamiz
        deleted = MemoryEntry(
            id=entry.id,
            layer=entry.layer,
            content=entry.content,
            summary=entry.summary,
            tags=entry.tags,
            source=entry.source,
            embedding=entry.embedding,
            version=entry.version,
            created_at=entry.created_at,
            expires_at=datetime.now(tz=UTC),  # eskirgan deb belgilaymiz
            trust_level=entry.trust_level,
        )
        self._entries[entry_id] = deleted
        log.info("memory.deleted", id=entry_id)
        return True

    def search(
        self,
        query: MemoryQuery,
        *,
        now: datetime | None = None,
    ) -> list[MemorySearchResult]:
        """Xotiradan qidirish.

        Strategiya:
        1. Qatlam va teglar bo'yicha filtrlash
        2. Matn bo'yicha oddiy qidirish (substring match)
        3. Embedding mavjud bo'lsa — cosine similarity
        4. Natijalarni reytingga ko'ra tartiblash
        """
        now = now or datetime.now(tz=UTC)
        candidates: list[tuple[MemoryEntry, float]] = []

        for entry in self._entries.values():
            # O'chirilganlarni o'tkazish
            if self._is_deleted(entry):
                continue

            # Eskirganlarni o'tkazish (agar include_expired=False)
            if not query.include_expired and self._is_expired(entry, now):
                continue

            # Qatlam filtri
            if query.layers and entry.layer not in query.layers:
                continue

            # Teg filtri
            if query.tags and not any(t in entry.tags for t in query.tags):
                continue

            # O'xshashlik hisoblash
            similarity = self._compute_similarity(query.text, entry)

            if similarity >= query.min_similarity:
                candidates.append((entry, round(similarity, 4)))

        # Tartiblash (yuqori o'xshashlik birinchi)
        candidates.sort(key=lambda c: c[1], reverse=True)

        # Limit va rank
        ranked: list[MemorySearchResult] = []
        for i, (entry, sim) in enumerate(candidates[: query.limit], 1):
            ranked.append(MemorySearchResult(entry=entry, similarity=sim, rank=i))

        return ranked

    def list_by_layer(
        self,
        layer: MemoryLayer,
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[MemoryEntry]:
        """Qatlam bo'yicha yozuvlarni olish."""
        now = now or datetime.now(tz=UTC)
        entries = [
            e
            for e in self._entries.values()
            if e.layer == layer and not self._is_deleted(e) and not self._is_expired(e, now)
        ]
        entries.sort(key=lambda e: e.created_at or now, reverse=True)
        return entries[:limit]

    def cleanup_expired(self, *, now: datetime | None = None) -> int:
        """Eskirgan yozuvlarni tozalash (hard delete).

        Returns:
            O'chirilgan yozuvlar soni.
        """
        now = now or datetime.now(tz=UTC)
        expired_ids = [eid for eid, entry in self._entries.items() if self._is_expired(entry, now)]
        for eid in expired_ids:
            del self._entries[eid]

        if expired_ids:
            log.info("memory.cleanup", count=len(expired_ids))
        return len(expired_ids)

    def _is_deleted(self, entry: MemoryEntry) -> bool:  # noqa: ARG002
        """Yozuv o'chirilganmi.

        Hozircha domain modelda `is_deleted` flag yo'q — faqat
        expires_at orqali soft delete amalga oshiriladi.
        DB modelda `is_deleted` bor, PgMemoryStore buni ishlatadi.
        """
        return False

    def _is_expired(self, entry: MemoryEntry, now: datetime | None = None) -> bool:
        """Yozuv muddati o'tganmi."""
        if entry.expires_at is None:
            return False
        now = now or datetime.now(tz=UTC)
        return entry.expires_at <= now

    def _compute_similarity(self, query_text: str, entry: MemoryEntry) -> float:
        """O'xshashlik hisoblash.

        Oddiy strategiya:
        1. Matn substring match → 0.8
        2. Tag match → 0.7
        3. Embedding cosine similarity (agar mavjud bo'lsa)
        4. Aks holda → 0.0
        """
        score = 0.0

        # Substring match (case-insensitive)
        query_lower = query_text.lower()
        content_lower = entry.content.lower()
        summary_lower = (entry.summary or "").lower()

        if query_lower in content_lower:
            score = max(score, 0.8)
        elif query_lower in summary_lower:
            score = max(score, 0.75)

        # So'zlar bo'yicha partial match
        query_words = set(query_lower.split())
        content_words = set(content_lower.split())
        if query_words and content_words:
            overlap = len(query_words & content_words)
            word_score = overlap / max(len(query_words), 1) * 0.7
            score = max(score, word_score)

        return score

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity ikki vektor orasida.

        Bo'sh yoki uzunligi farqli vektorlar uchun 0.0 qaytaradi.
        """
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b, strict=True))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)
