"""PgMemoryStore — DB-backed xotira do'koni (Bo'lim 2, produksiya).

`MemoryStore` (in-memory) bilan bir xil amaliy operatsiyalarni bajaradi
(add/get/update/delete/search/list_by_layer/cleanup_expired), lekin
`AsyncSession` orqali `memory_entries` jadvaliga yozadi — ma'lumotlar
protsess qayta ishga tushgandan keyin ham saqlanadi.

Ilgari bu klass umuman mavjud emas edi (faqat docstring'da nomlangan) —
gap-analysis #5: "PgMemoryStore does not exist anywhere in the codebase".

Metodlar `MemoryStore`dan farqli — ASYNC (DB I/O bor). Chaqiruvchi kod
(`api/routes/memory.py`) ikkalasini ham qo'llab-quvvatlash uchun
`_maybe_await()` yordamchisidan foydalanadi.

Bog'liq qarorlar:
    V-14 — ruxsatga bog'liq ko'rinish
    V-15 — xotira versiyalash
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.memory import MemoryEntry as MemoryEntryRow
from zet.domain.memory import (
    LAYER_TTL,
    MemoryEntry,
    MemoryLayer,
    MemoryQuery,
    MemorySearchResult,
)
from zet.memory.embeddings import EMBEDDING_MODEL_KEY, EmbeddingProvider
from zet.memory.scoring import cosine_similarity, hybrid_score, keyword_score

log = structlog.get_logger(__name__)


def _embedding_column(vector: list[float] | None, model_id: str) -> dict[str, Any] | None:
    """Vektorni model belgisi bilan JSON ustunga tayyorlash.

    Belgi shart: `bge-m3` va `mistral-embed` ikkalasi ham 1024 o'lchamli,
    ya'ni o'lcham tekshiruvi ularni ajratmaydi, lekin fazolari boshqa.
    Belgisiz taqqoslash ma'nosiz "o'xshashlik" beradi.
    """
    if vector is None:
        return None
    return {"v": vector, EMBEDDING_MODEL_KEY: model_id}


def _to_domain(row: MemoryEntryRow) -> MemoryEntry:
    """DB qatorini domen modeliga o'giradi."""
    embedding: list[float] | None = None
    if row.embedding is not None:
        embedding = row.embedding.get("v")

    return MemoryEntry(
        id=str(row.id),
        layer=MemoryLayer(row.layer),
        content=row.content,
        summary=row.summary,
        tags=list(row.tags or []),
        source=row.source,
        embedding=embedding,
        version=row.version,
        created_at=row.created_at,
        expires_at=row.expires_at,
        trust_level=row.trust_level,
    )


def _parse_uuid(entry_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(entry_id)
    except ValueError:
        return None


class PgMemoryStore:
    """DB-backed xotira do'koni — bitta egaga tegishli yozuvlar bilan ishlaydi.

    Har bir metod `flush()` qiladi (natija darhol o'qilishi uchun), lekin
    `commit()` qilmaydi — bu chaqiruvchining (odatda `session_scope()`)
    vazifasi.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_id: uuid.UUID,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._session = session
        self._owner_id = owner_id
        self._embedder = embedder

    @property
    def _embedder_model_id(self) -> str:
        """Joriy vektor fazosi belgisi ('unknown' — eski/nomsiz provayder)."""
        return getattr(self._embedder, "model_id", "unknown")

    async def add(
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
        """Yangi xotira yozuvi qo'shish. TTL avtomatik hisoblanadi.

        `embedding` berilmasa va `embedder` sozlangan bo'lsa — vektor
        avtomatik hisoblanadi (fail-open: Ollama ulanmagan bo'lsa ham
        yozuv oddiy saqlanadi, faqat embedding'siz).
        """
        now = now or datetime.now(tz=UTC)
        ttl = LAYER_TTL.get(layer)
        expires_at = now + timedelta(seconds=ttl) if ttl is not None else None

        if embedding is None and self._embedder is not None:
            embedding = await self._embedder.embed(content)

        row = MemoryEntryRow(
            owner_id=self._owner_id,
            layer=layer.value,
            content=content,
            summary=summary,
            tags=tags or [],
            source=source,
            embedding=_embedding_column(embedding, self._embedder_model_id),
            version=1,
            trust_level=trust_level,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        log.info("memory.pg.added", id=str(row.id), layer=layer.value)
        return _to_domain(row)

    async def get(self, entry_id: str) -> MemoryEntry | None:
        """Yozuvni ID bo'yicha olish (o'chirilgan/eskirgan/boshqa ega — None)."""
        row = await self._get_row(entry_id)
        if row is None:
            return None
        return _to_domain(row)

    async def update(
        self,
        entry_id: str,
        *,
        content: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> MemoryEntry | None:
        """Yozuvni yangilash (versiya oshadi).

        `content` o'zgarsa va `embedding` aniq berilmasa — `embedder`
        sozlangan bo'lsa vektor yangi matn uchun qayta hisoblanadi.
        """
        row = await self._get_row(entry_id)
        if row is None:
            return None

        if content is not None:
            row.content = content
            if embedding is None and self._embedder is not None:
                embedding = await self._embedder.embed(content)
        if summary is not None:
            row.summary = summary
        if tags is not None:
            row.tags = tags
        if embedding is not None:
            row.embedding = _embedding_column(embedding, self._embedder_model_id)
        row.version += 1

        await self._session.flush()
        log.info("memory.pg.updated", id=entry_id, version=row.version)
        return _to_domain(row)

    async def delete(self, entry_id: str) -> bool:
        """Soft delete."""
        uid = _parse_uuid(entry_id)
        if uid is None:
            return False
        row = await self._session.get(MemoryEntryRow, uid)
        if row is None or row.owner_id != self._owner_id:
            return False
        row.is_deleted = True
        await self._session.flush()
        log.info("memory.pg.deleted", id=entry_id)
        return True

    async def search(
        self,
        query: MemoryQuery,
        *,
        now: datetime | None = None,
    ) -> list[MemorySearchResult]:
        """Xotiradan qidirish — kalit-so'z + vektor (hybrid, `embedder` sozlangan bo'lsa).

        `embedder` yo'q yoki so'rov vektorini hisoblab bo'lmasa (Ollama
        ulanmagan) — faqat kalit-so'z balliga tushadi (fail-open, avvalgi
        xatti-harakat bilan bir xil).
        """
        now = now or datetime.now(tz=UTC)
        stmt = select(MemoryEntryRow).where(
            MemoryEntryRow.owner_id == self._owner_id,
            MemoryEntryRow.is_deleted.is_(False),
        )
        if query.layers:
            stmt = stmt.where(MemoryEntryRow.layer.in_([layer.value for layer in query.layers]))

        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        query_embedding: list[float] | None = None
        if self._embedder is not None:
            query_embedding = await self._embedder.embed(query.text)

        candidates: list[tuple[MemoryEntryRow, float]] = []
        for row in rows:
            if not query.include_expired and row.expires_at is not None and row.expires_at <= now:
                continue
            if query.tags and not any(t in (row.tags or []) for t in query.tags):
                continue

            kw_score = keyword_score(query.text, row.content, row.summary)
            vector_score: float | None = None
            if query_embedding is not None and row.embedding is not None:
                row_vector = row.embedding.get("v")
                row_model = row.embedding.get(EMBEDDING_MODEL_KEY)
                # Boshqa model bilan yozilgan vektor TAQQOSLANMAYDI —
                # o'lchamlari mos kelsa ham fazolari boshqa. Bunday yozuv
                # kalit-so'z balli bilan qatnashadi, xolos.
                if row_vector and row_model == self._embedder_model_id:
                    vector_score = cosine_similarity(query_embedding, row_vector)

            similarity = hybrid_score(keyword=kw_score, vector=vector_score)
            if similarity >= query.min_similarity:
                candidates.append((row, round(similarity, 4)))

        candidates.sort(key=lambda c: c[1], reverse=True)

        ranked: list[MemorySearchResult] = []
        for i, (row, sim) in enumerate(candidates[: query.limit], 1):
            ranked.append(MemorySearchResult(entry=_to_domain(row), similarity=sim, rank=i))
        return ranked

    async def list_by_layer(
        self,
        layer: MemoryLayer,
        *,
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[MemoryEntry]:
        """Qatlam bo'yicha yozuvlarni olish (eng yangi birinchi)."""
        now = now or datetime.now(tz=UTC)
        stmt = (
            select(MemoryEntryRow)
            .where(
                MemoryEntryRow.owner_id == self._owner_id,
                MemoryEntryRow.layer == layer.value,
                MemoryEntryRow.is_deleted.is_(False),
            )
            .order_by(MemoryEntryRow.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return [_to_domain(row) for row in rows if row.expires_at is None or row.expires_at > now]

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        """Eskirgan yozuvlarni tozalash (hard delete)."""
        now = now or datetime.now(tz=UTC)
        stmt = select(MemoryEntryRow).where(
            MemoryEntryRow.owner_id == self._owner_id,
            MemoryEntryRow.expires_at.is_not(None),
            MemoryEntryRow.expires_at <= now,
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        count = len(rows)
        for row in rows:
            await self._session.delete(row)
        if count:
            await self._session.flush()
            log.info("memory.pg.cleanup", count=count)
        return count

    async def count(self, *, now: datetime | None = None) -> int:
        """Faol yozuvlar soni (o'chirilgan/eskirganlar hisobga olinmaydi)."""
        now = now or datetime.now(tz=UTC)
        stmt = select(MemoryEntryRow).where(
            MemoryEntryRow.owner_id == self._owner_id,
            MemoryEntryRow.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return sum(1 for row in rows if row.expires_at is None or row.expires_at > now)

    async def _get_row(self, entry_id: str) -> MemoryEntryRow | None:
        uid = _parse_uuid(entry_id)
        if uid is None:
            return None
        row = await self._session.get(MemoryEntryRow, uid)
        if row is None or row.owner_id != self._owner_id or row.is_deleted:
            return None
        if row.expires_at is not None and row.expires_at <= datetime.now(tz=UTC):
            return None
        return row


__all__ = ["PgMemoryStore"]
