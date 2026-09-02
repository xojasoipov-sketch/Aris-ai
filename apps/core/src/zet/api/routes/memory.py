"""Memory API endpoint'lari (Bo'lim 2).

Xotira CRUD va qidirish:
    POST   /api/v1/memory           — yangi yozuv qo'shish
    GET    /api/v1/memory/{id}      — yozuvni olish
    PATCH  /api/v1/memory/{id}      — yozuvni yangilash
    DELETE /api/v1/memory/{id}      — yozuvni o'chirish (soft)
    POST   /api/v1/memory/search    — qidirish
    GET    /api/v1/memory/layer/{layer} — qatlam bo'yicha ro'yxat
    POST   /api/v1/memory/cleanup   — eskirganlarni tozalash
    POST   /api/v1/memory/ingest-profile — profil faylini (markdown)
        fayl-yuklash orqali PERSONAL qatlamga bo'lib yuklash

`store` — `PgMemoryStore` (DB-backed, async) yoki test'larda `MemoryStore`
(in-memory, sync) bo'lishi mumkin. `_maybe_await()` ikkalasini ham
qo'llab-quvvatlaydi — endpoint kodi bittasiga qattiq bog'lanmaydi.

TRUST_LEVEL SIYOSATI (V-14, A-05).

Har bir endpoint `X-Trust-Level` header'idan chaqiruvchining trust
darajasini oladi (default `"owner"` — backward compat). Yozish/o'qish
`memory/policy.py::check_write`/`check_read` orqali tekshiriladi:
    - `owner` — barcha qatlamlar
    - `system` — PERSONAL/KNOWLEDGE ga yoza olmaydi, KNOWLEDGE ga o'qiy oladi
    - `untrusted` — faqat SHORT_TERM yozadi, SHORT_TERM+KNOWLEDGE o'qiydi

Ilgari (audit'gacha) bu tekshiruv umuman yo'q edi — mijoz istagan
qatlamga yozardi. Endi siyosat buzilganda 403 qaytariladi.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from zet.api.deps import (
    MemoryStoreLike,
    get_caller_trust_level,
    get_memory_manager,
    get_memory_store,
)
from zet.domain.memory import MemoryEntry, MemoryLayer, MemoryQuery
from zet.memory.manager import MemoryManager
from zet.memory.policy import (
    MemoryPolicyError,
    check_read,
    check_write,
    readable_layers,
)
from zet.memory.profile_ingest import SOURCE_TAG, _slug, split_sections

router = APIRouter(prefix="/memory", tags=["memory"])

MAX_UPLOAD_SIZE = 2_000_000
"""`POST /memory/ingest-profile` uchun eng katta fayl hajmi (2MB).

Profil fayllari (masalan `BOSS_PROFILE.md`) bir necha KB — bu chegara
oddiy noto'g'ri (yoki zararli katta) yuklamalarni erta rad etish uchun
yetarli xavfsizlik chegarasi.
"""


async def _maybe_await[T](value: T | Any) -> T:
    """`PgMemoryStore` (async) va `MemoryStore` (sync) natijalarini bir xil ko'rinishga keltiradi."""
    if inspect.isawaitable(value):
        return await value
    return value


def _enforce_write(trust_level: str, layer: MemoryLayer) -> None:
    """`check_write` ni chaqirib, `MemoryPolicyError` ni 403 ga aylantiradi.

    Xato matni "layer <X> requires <Y> trust" ko'rinishida — mijozga
    aynan qaysi qatlam qaysi darajani talab qilishi ochiq ko'rinsin
    (audit'da so'ralgan format).
    """
    try:
        check_write(trust_level, layer)
    except MemoryPolicyError as exc:
        raise HTTPException(
            status_code=403,
            detail=(
                f"layer {layer.value} requires higher trust for write (got {trust_level!r}): {exc}"
            ),
        ) from exc


def _enforce_read(trust_level: str, layer: MemoryLayer) -> None:
    """`check_read` ni chaqirib, `MemoryPolicyError` ni 403 ga aylantiradi."""
    try:
        check_read(trust_level, layer)
    except MemoryPolicyError as exc:
        raise HTTPException(
            status_code=403,
            detail=(
                f"layer {layer.value} requires higher trust for read (got {trust_level!r}): {exc}"
            ),
        ) from exc


# ── Request / Response modellari ──────────────────────────────────


class MemoryAddRequest(BaseModel):
    """Yangi xotira yozuvi.

    `trust_level` maydoni backward-compat uchun saqlangan — lekin server
    uni chaqiruvchining haqiqiy trust'iga cheklaydi (mijoz o'zidan yuqori
    trust bilan yoza olmaydi).
    """

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


class ProfileIngestResponse(BaseModel):
    """`POST /memory/ingest-profile` natijasi."""

    sections_found: int
    added: int
    failed: int
    errors: list[str] = Field(default_factory=list)


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
    manager: MemoryManager = Depends(get_memory_manager),
    trust_level: str = Depends(get_caller_trust_level),
) -> MemoryEntryResponse:
    """Yangi xotira yozuvi qo'shish.

    Chaqiruvchining trust'i qatlamga yozishga yetmasa — 403. Yozuvning
    `trust_level` maydoni sifatida chaqiruvchi trust'i saqlanadi
    (mijoz JSON'da yuborgan `trust_level` server tomonidan almashtiriladi
    — mijoz o'zidan yuqori trust bilan yoza olmasin).

    NEGA `MemoryManager` orqali. Ilgari route `store.add()`ni to'g'ridan-
    to'g'ri chaqirar edi — bu `memory.write` tool bilan bir xil policy
    darvozasidan o'tmasdi va auto-summarize/auto-tag ham ishlamasdi.
    Endi manager `check_write` + summarize + tag pipeline'ini bajaradi;
    quyidagi qo'shimcha `_enforce_write` faqat tez 403 xato matni uchun
    (ichki `MemoryPolicyError` matni mijoz uchun mos emas).
    """
    _enforce_write(trust_level, request.layer)
    try:
        entry = await manager.aremember(
            layer=request.layer,
            content=request.content,
            trust_level=trust_level,
            summary=request.summary,
            tags=request.tags or None,
            source=request.source,
        )
    except MemoryPolicyError as exc:
        # Manager policy'ni ikkinchi bor tekshirishi mumkin (bir xil qoida) —
        # yuqoridagi `_enforce_write` tuzoqqa tushmagan chekka holat uchun
        # xavfsiz zaxira.
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _entry_to_response(entry)


@router.get("/{entry_id}", response_model=MemoryEntryResponse)
async def get_memory(
    entry_id: str,
    store: MemoryStoreLike = Depends(get_memory_store),
    trust_level: str = Depends(get_caller_trust_level),
) -> MemoryEntryResponse:
    """Yozuvni ID bo'yicha olish.

    Yozuvning qatlami chaqiruvchi uchun o'qish siyosatiga to'g'ri kelmasa
    — 403 (yozuvning mavjudligi ham fosh bo'lmasin uchun avval fetch,
    keyin policy).
    """
    entry = await _maybe_await(store.get(entry_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    _enforce_read(trust_level, entry.layer)
    return _entry_to_response(entry)


@router.patch("/{entry_id}", response_model=MemoryEntryResponse)
async def update_memory(
    entry_id: str,
    request: MemoryUpdateRequest,
    store: MemoryStoreLike = Depends(get_memory_store),
    trust_level: str = Depends(get_caller_trust_level),
) -> MemoryEntryResponse:
    """Yozuvni yangilash (versiya oshadi).

    Yangilanadigan yozuvning qatlamiga yozish ruxsati tekshiriladi.
    """
    existing = await _maybe_await(store.get(entry_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    _enforce_write(trust_level, existing.layer)
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
    trust_level: str = Depends(get_caller_trust_level),
) -> None:
    """Yozuvni o'chirish (soft delete).

    O'chirishdan oldin qatlam bo'yicha yozish siyosati tekshiriladi —
    untrusted trust PERSONAL yozuvni o'chira olmaydi.
    """
    existing = await _maybe_await(store.get(entry_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    _enforce_write(trust_level, existing.layer)
    if not await _maybe_await(store.delete(entry_id)):
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")


@router.post("/search", response_model=list[MemorySearchResultResponse])
async def search_memory(
    request: MemorySearchRequest,
    store: MemoryStoreLike = Depends(get_memory_store),
    trust_level: str = Depends(get_caller_trust_level),
) -> list[MemorySearchResultResponse]:
    """Xotiradan qidirish.

    Chaqiruvchi ochiq ravishda o'qib bo'lmaydigan qatlamni so'rasa (masalan,
    untrusted → PERSONAL) — 403. Aks holda so'rov `readable_layers` bilan
    kesib olinadi: filtr yuborilmasa faqat ruxsat etilgan qatlamlar
    qidiriladi, shu bilan bekilgan qatlamdan sirt chiqmaydi.
    """
    allowed = readable_layers(trust_level)
    if request.layers is not None:
        for layer in request.layers:
            if layer not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"layer {layer.value} requires higher trust for read (got {trust_level!r})"
                    ),
                )
        effective_layers = list(request.layers)
    else:
        # Filtr yo'q — o'qib bo'ladigan qatlamlar bilan cheklaymiz. Aks
        # holda untrusted mijoz butun xotirani qidirib chiqib, kimningdir
        # PERSONAL yozuvini `text` orqali chiqarib olishi mumkin edi.
        effective_layers = list(allowed)

    query = MemoryQuery(
        text=request.text,
        layers=effective_layers,
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
    trust_level: str = Depends(get_caller_trust_level),
) -> list[MemoryEntryResponse]:
    """Qatlam bo'yicha yozuvlar ro'yxati.

    Qatlam chaqiruvchi uchun o'qib bo'lmasa — 403.
    """
    _enforce_read(trust_level, layer)
    entries = await _maybe_await(store.list_by_layer(layer, limit=limit))
    return [_entry_to_response(e) for e in entries]


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_expired(
    store: MemoryStoreLike = Depends(get_memory_store),
) -> CleanupResponse:
    """Eskirgan yozuvlarni tozalash."""
    count = await _maybe_await(store.cleanup_expired())
    return CleanupResponse(removed=count)


@router.post("/ingest-profile", response_model=ProfileIngestResponse, status_code=201)
async def ingest_profile(
    file: UploadFile = File(...),
    manager: MemoryManager = Depends(get_memory_manager),
    trust_level: str = Depends(get_caller_trust_level),
) -> ProfileIngestResponse:
    """Profil faylini (markdown) fayl-yuklash orqali xotiraga yuklaydi.

    `zet.memory.profile_ingest.split_sections()` bilan bir xil mantiqdan
    foydalanadi — bu `scripts/ingest_profile.py` CLI skripti ishlatadigan
    ANIQ SHU funksiya, ya'ni fayl CLI orqali yoki shu endpoint orqali
    yuklansa bir xil bo'linadi. Har bo'lim PERSONAL qatlamga
    `MemoryManager.aremember()` orqali yoziladi — `add_memory()` (POST
    /memory) qanday policy darvozasidan o'tsa, shu ham o'shandan o'tadi.

    Bitta bo'lim yozilishida xato bo'lsa (masalan policy yoki DB xatosi)
    — qolgan bo'limlar baribir davom etadi (bittasi qulasa hammasi
    yo'qolmasin); sabab `errors`da qaytadi, `failed` sanaladi.
    """
    _enforce_write(trust_level, MemoryLayer.PERSONAL)

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Fayl bo'sh")
    if len(raw) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Fayl juda katta (max {MAX_UPLOAD_SIZE} bayt)",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Fayl UTF-8 kodlashda emas"
        ) from exc

    sections = split_sections(text)
    added = 0
    errors: list[str] = []
    for title, content in sections:
        try:
            await manager.aremember(
                layer=MemoryLayer.PERSONAL,
                content=content,
                trust_level=trust_level,
                summary=title[:200],
                tags=[SOURCE_TAG, _slug(title)],
                source=SOURCE_TAG,
            )
            added += 1
        except MemoryPolicyError as exc:
            errors.append(f"{title}: {exc}")

    return ProfileIngestResponse(
        sections_found=len(sections),
        added=added,
        failed=len(errors),
        errors=errors,
    )
