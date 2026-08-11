"""Memory API endpoint'lari (Bo'lim 2).

Xotira CRUD va qidirish:
    POST   /api/v1/memory           — yangi yozuv qo'shish
    GET    /api/v1/memory/{id}      — yozuvni olish
    PATCH  /api/v1/memory/{id}      — yozuvni yangilash
    DELETE /api/v1/memory/{id}      — yozuvni o'chirish (soft)
    POST   /api/v1/memory/search    — qidirish
    GET    /api/v1/memory/layer/{layer} — qatlam bo'yicha ro'yxat
    POST   /api/v1/memory/cleanup   — eskirganlarni tozalash

`store` — `PgMemoryStore` (DB-backed, async) yoki test'larda `MemoryStore`
(in-memory, sync) bo'lishi mumkin. `_maybe_await()` ikkalasini ham
qo'llab-quvvatlaydi — endpoint kodi bittasiga qattiq bog'lanmaydi.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import MemoryStoreLike, get_memory_store
from zet.domain.memory import MemoryEntry, MemoryLayer, MemoryQuery

router = APIRouter(prefix="/memory", tags=["memory"])


async def _maybe_await[T](value: T | Any) -> T:
    """`PgMemoryStore` (async) va `MemoryStore` (sync) natijalarini bir xil ko'rinishga keltiradi."""
    if inspect.isawaitable(value):
        return await value
    return value


# ── Request / Response modellari ──────────────────────────────────


class MemoryAddRequest(BaseModel):
    """Yangi xotira yozuvi."""

    layer: MemoryLayer
    content: str = Field(..., min_length=1, max_length=50_000)
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    trust_level: str = "owner"


class MemoryUpdateRequest(BaseModel):
    """Yozuvni yangilash."""

    content: str | None = None
    summary: str | None = None
    tags: list[str] | None = None


class MemorySearchRequest(BaseModel):
    """Qidiruv so'rovi."""

    text: str = Field(..., min_length=1)
    layers: list[MemoryLayer] | None = None
    tags: list[str] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    include_expired: bool = False


class MemoryEntryResponse(BaseModel):
    """Yozuv javobi."""

    id: str | None
    layer: str
    content: str
    summary: str | None = None
    tags: list[str]
    source: str | None = None
    version: int
    trust_level: str
    created_at: str | None = None
    expires_at: str | None = None


class MemorySearchResultResponse(BaseModel):
    """Qidiruv natijasi."""

    entry: MemoryEntryResponse
    similarity: float
    rank: int


class CleanupResponse(BaseModel):
    """Tozalash natijasi."""

    removed: int


# ── Yordamchi ─────────────────────────────────────────────────────


def _entry_to_response(entry: MemoryEntry) -> MemoryEntryResponse:
    """Domain MemoryEntry ni response ga o'girish."""
    return MemoryEntryResponse(
        id=entry.id,
        layer=entry.layer.value if isinstance(entry.layer, MemoryLayer) else str(entry.layer),
        content=entry.content,
        summary=entry.summary,
        tags=list(entry.tags),
        source=entry.source,
        version=entry.version,
        trust_level=entry.trust_level,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
        expires_at=entry.expires_at.isoformat() if entry.expires_at else None,
    )


# ── Endpoint'lar ──────────────────────────────────────────────────


@router.post("", response_model=MemoryEntryResponse, status_code=201)
async def add_memory(
    request: MemoryAddRequest,
    store: MemoryStoreLike = Depends(get_memory_store),
) -> MemoryEntryResponse:
    """Yangi xotira yozuvi qo'shish."""
    entry = await _maybe_await(
        store.add(
            layer=request.layer,
            content=request.content,
            summary=request.summary,
            tags=request.tags,
            source=request.source,
            trust_level=request.trust_level,
        )
    )
    return _entry_to_response(entry)


@router.get("/{entry_id}", response_model=MemoryEntryResponse)
async def get_memory(
    entry_id: str,
    store: MemoryStoreLike = Depends(get_memory_store),
) -> MemoryEntryResponse:
    """Yozuvni ID bo'yicha olish."""
    entry = await _maybe_await(store.get(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    return _entry_to_response(entry)


@router.patch("/{entry_id}", response_model=MemoryEntryResponse)
async def update_memory(
    entry_id: str,
    request: MemoryUpdateRequest,
    store: MemoryStoreLike = Depends(get_memory_store),
) -> MemoryEntryResponse:
    """Yozuvni yangilash (versiya oshadi)."""
    updated = await _maybe_await(
        store.update(
            entry_id,
            content=request.content,
            summary=request.summary,
            tags=request.tags,
        )
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    return _entry_to_response(updated)


@router.delete("/{entry_id}", status_code=204)
async def delete_memory(
    entry_id: str,
    store: MemoryStoreLike = Depends(get_memory_store),
) -> None:
    """Yozuvni o'chirish (soft delete)."""
    if not await _maybe_await(store.delete(entry_id)):
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")


@router.post("/search", response_model=list[MemorySearchResultResponse])
async def search_memory(
    request: MemorySearchRequest,
    store: MemoryStoreLike = Depends(get_memory_store),
) -> list[MemorySearchResultResponse]:
    """Xotiradan qidirish."""
    query = MemoryQuery(
        text=request.text,
        layers=request.layers,
        tags=request.tags,
        limit=request.limit,
        min_similarity=request.min_similarity,
        include_expired=request.include_expired,
    )
    results = await _maybe_await(store.search(query))
    return [
        MemorySearchResultResponse(
            entry=_entry_to_response(r.entry),
            similarity=r.similarity,
            rank=r.rank,
        )
        for r in results
    ]


@router.get("/layer/{layer}", response_model=list[MemoryEntryResponse])
async def list_by_layer(
    layer: MemoryLayer,
    limit: int = 50,
    store: MemoryStoreLike = Depends(get_memory_store),
) -> list[MemoryEntryResponse]:
    """Qatlam bo'yicha yozuvlar ro'yxati."""
    entries = await _maybe_await(store.list_by_layer(layer, limit=limit))
    return [_entry_to_response(e) for e in entries]


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_expired(
    store: MemoryStoreLike = Depends(get_memory_store),
) -> CleanupResponse:
    """Eskirgan yozuvlarni tozalash."""
    count = await _maybe_await(store.cleanup_expired())
    return CleanupResponse(removed=count)
