"""Sync orkestratsiyasi — source → parser → normalizer → repository.

Bo'lim 3'ning to'liq oqimi: manba olinadi, kategoriyalar/yozuvlar
ajratiladi, normallashtiriladi, repository'ga BIRLASHTIRILADI (eski
baholash ma'lumoti yo'qolmaydi), va sync HISOBOTI qaytariladi.

Bu funksiya HECH QANDAY API'ni ijro ETMAYDI — faqat katalog
ma'lumotini yangilaydi (Bo'lim 3: "ingestion, execution emas").
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from zet.integrations.public_apis.catalog.normalizer import normalize_entries
from zet.integrations.public_apis.catalog.parser import parse_readme
from zet.integrations.public_apis.catalog.repository import CatalogRepository, SyncReport
from zet.integrations.public_apis.catalog.source import (
    CatalogSyncError,
    fetch_catalog_text,
    resolve_source_url,
)

log = structlog.get_logger(__name__)


async def sync_catalog(
    repository: CatalogRepository,
    *,
    source_url_template: str,
    branch: str,
) -> SyncReport:
    """Katalogni haqiqiy manbadan qayta sinxronlaydi.

    Muvaffaqiyatsiz bo'lsa — repository O'ZGARISHSIZ qoladi, hisobot
    `ok=False` bilan qaytadi (eski katalog yo'qolmaydi).
    """
    source_url = resolve_source_url(source_url_template=source_url_template, branch=branch)
    now = datetime.now(UTC)
    try:
        text = await fetch_catalog_text(source_url=source_url)
    except CatalogSyncError as exc:
        log.warning("public_apis.sync_failed", source_url=source_url, error=str(exc))
        return repository.record_failed_sync(source_url=source_url, now=now, error=str(exc))

    raw_entries = parse_readme(text)
    entries = normalize_entries(raw_entries)
    report = repository.replace_all(entries, source_url=source_url, now=now)
    log.info(
        "public_apis.synced",
        total=report.total_entries,
        added=report.added,
        changed=report.changed,
        removed=report.removed,
        categories=report.categories,
    )
    return report


__all__ = ["sync_catalog"]
