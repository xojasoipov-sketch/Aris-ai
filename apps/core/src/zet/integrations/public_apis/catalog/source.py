"""Katalog manbasidan xom matnni olish — HECH QANDAY parse/ijro shu yerda.

Bo'lim 3 talabi: "ingestion va execution ALOHIDA qatlam bo'lishi kerak."
Bu modul faqat HTTP GET qiladi va matn qaytaradi — `parser.py`/
`normalizer.py` uni qayta ishlaydi, `adapters/` esa umuman bu modulni
chaqirmaydi (adapterlar haqiqiy provayder API'siga bevosita boradi).
"""

from __future__ import annotations

import httpx
import structlog

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_S = 20.0
USER_AGENT = "ZET/1.0 (public-apis catalog sync; +https://github.com/public-apis/public-apis)"


class CatalogSyncError(RuntimeError):
    """Katalog manbasi javob bermadi yoki o'qib bo'lmadi."""


def resolve_source_url(*, source_url_template: str, branch: str) -> str:
    """`{branch}` o'rniga haqiqiy tarmoq nomini qo'yadi.

    Shablonda `{branch}` bo'lmasa (operator to'liq URL bergan bo'lsa) —
    o'zgarishsiz qaytadi.
    """
    if "{branch}" in source_url_template:
        return source_url_template.format(branch=branch)
    return source_url_template


async def fetch_catalog_text(
    *,
    source_url: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Katalog manbasining XOM matnini oladi (odatda README.md).

    Raises:
        CatalogSyncError: tarmoq xatosi, timeout, yoki HTTP xato holati.
    """
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await http_client.get(source_url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text
    except httpx.TimeoutException as exc:
        raise CatalogSyncError(f"Katalog manbasi javob bermadi (timeout): {source_url}") from exc
    except httpx.HTTPStatusError as exc:
        raise CatalogSyncError(
            f"Katalog manbasi HTTP {exc.response.status_code} qaytardi: {source_url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise CatalogSyncError(f"Katalog manbasiga ulanib bo'lmadi: {exc}") from exc
    finally:
        if owns_client:
            await http_client.aclose()


__all__ = ["CatalogSyncError", "fetch_catalog_text", "resolve_source_url"]
