"""public-apis katalogi — admin/operator endpoint'lari (Bo'lim 17).

    GET  /api/v1/public-apis/search?q=...   — katalogni qidirish (reytinglangan)
    POST /api/v1/public-apis/refresh        — katalogni haqiqiy manbadan qayta sinxronlash
    GET  /api/v1/public-apis/health         — ENABLED adapterlar sog'ligi
    GET  /api/v1/public-apis/stats          — katalog holati (oxirgi sync, kategoriyalar)

Bu endpoint'lar FAQAT kuzatuv/boshqaruv uchun — hech biri LLM/Brain
yo'lidan chaqirilmaydi (Brain `public_apis.search` TOOL orqali ishlaydi,
`tools/builtin/public_apis_search.py`ga qarang) — ikkalasi ham BIR XIL
`CatalogRepository` singletonini o'qiydi (`api/deps.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from zet.api.deps import (
    get_config,
    get_public_apis_catalog_repository,
    get_public_apis_health_tracker,
)
from zet.config import Settings
from zet.integrations.public_apis.catalog.models import APIStatus
from zet.integrations.public_apis.catalog.repository import CatalogRepository
from zet.integrations.public_apis.catalog.sync import sync_catalog
from zet.integrations.public_apis.discovery import rank_candidates, search_catalog
from zet.integrations.public_apis.health.scoring import ProviderHealthTracker

router = APIRouter(prefix="/public-apis", tags=["public-apis"])


class SearchCandidate(BaseModel):
    entry_id: str
    name: str
    provider: str
    category: str
    relevance: float
    composite_score: float
    auth_type: str
    https_supported: bool
    pricing_status: str
    status: str
    health_score: float | None
    reasons: list[str]


class SearchResponse(BaseModel):
    query: str
    total_candidates: int
    candidates: list[SearchCandidate]


class RefreshResponse(BaseModel):
    ok: bool
    total_entries: int
    added: int
    changed: int
    removed: int
    categories: int
    error: str | None = None


class CatalogStatsResponse(BaseModel):
    total_entries: int
    categories: int
    enabled: int
    last_sync_at: str | None
    last_sync_source: str | None
    last_sync_ok: bool | None


class ProviderHealthResponse(BaseModel):
    provider: str
    total_calls: int
    successes: int
    failures: int
    timeouts: int
    rate_limited: int
    avg_latency_ms: float
    success_rate: float | None


@router.get("/search", response_model=SearchResponse)
async def search_public_apis(
    q: str = Query(..., min_length=1, max_length=200, description="Kalit so'z(lar)"),
    limit: int = Query(default=10, ge=1, le=50),
    repository: CatalogRepository = Depends(get_public_apis_catalog_repository),
) -> SearchResponse:
    """Katalogni qidiradi — HAQIQIY yozuvlar, reytinglangan (Bo'lim 4)."""
    keywords = [w for w in q.split() if w.strip()]
    matches = search_catalog(repository.all(), keywords, limit=limit)
    ranked = rank_candidates(matches)
    return SearchResponse(
        query=q,
        total_candidates=len(ranked),
        candidates=[
            SearchCandidate(
                entry_id=c.entry_id,
                name=c.name,
                provider=c.provider,
                category=c.category,
                relevance=c.relevance,
                composite_score=c.composite_score,
                auth_type=c.auth_type.value,
                https_supported=c.https_supported,
                pricing_status=c.pricing_status,
                status=c.status.value,
                health_score=c.health_score,
                reasons=list(c.reasons),
            )
            for c in ranked
        ],
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_public_apis_catalog(
    repository: CatalogRepository = Depends(get_public_apis_catalog_repository),
    settings: Settings = Depends(get_config),
) -> RefreshResponse:
    """Katalogni `public-apis/public-apis`dan HAQIQIY qayta sinxronlaydi.

    Faqat operator/CLI orqali qo'lda chaqiriladi — hech qanday avtomatik
    fon vazifasi yo'q (`config.py::public_apis_auto_enable`ning haqiqiy
    ma'nosi shu: bu yerga avtomatik yo'l yo'q, faqat shu endpoint)."""
    report = await sync_catalog(
        repository,
        source_url_template=settings.public_apis_source_url,
        branch=settings.public_apis_branch,
    )
    return RefreshResponse(
        ok=report.ok,
        total_entries=report.total_entries,
        added=report.added,
        changed=report.changed,
        removed=report.removed,
        categories=report.categories,
        error=report.error,
    )


@router.get("/stats", response_model=CatalogStatsResponse)
async def public_apis_catalog_stats(
    repository: CatalogRepository = Depends(get_public_apis_catalog_repository),
) -> CatalogStatsResponse:
    """Katalog holati — hali sync qilinmagan bo'lsa, HALOL bo'sh holat."""
    last_sync = repository.last_sync
    return CatalogStatsResponse(
        total_entries=len(repository.all()),
        categories=len(repository.categories()),
        enabled=len(repository.by_status(APIStatus.ENABLED)),
        last_sync_at=last_sync.synced_at.isoformat() if last_sync else None,
        last_sync_source=last_sync.source_url if last_sync else None,
        last_sync_ok=last_sync.ok if last_sync else None,
    )


@router.get("/health", response_model=list[ProviderHealthResponse])
async def public_apis_health(
    tracker: ProviderHealthTracker = Depends(get_public_apis_health_tracker),
) -> list[ProviderHealthResponse]:
    """ENABLED adapterlarning HAQIQIY chaqiruv statistikasi (Bo'lim 13).

    Hali chaqirilmagan provayder bu ro'yxatda UMUMAN ko'rinmaydi — bu
    "sog'lom" degani emas, "hali sinalmagan" degani (soxta 100%
    ko'rsatishdan yaxshiroq)."""
    snapshots = tracker.all_snapshots()
    return [
        ProviderHealthResponse(
            provider=s.provider,
            total_calls=s.total_calls,
            successes=s.successes,
            failures=s.failures,
            timeouts=s.timeouts,
            rate_limited=s.rate_limited,
            avg_latency_ms=s.avg_latency_ms,
            success_rate=s.success_rate,
        )
        for s in snapshots
    ]


__all__: list[str] = ["router"]
