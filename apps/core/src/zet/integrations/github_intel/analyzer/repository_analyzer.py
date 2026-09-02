"""`analyze_repository()` — HAQIQIY GitHub REST API'dan olinadigan
FAKTLAR (spec Bo'lim 5).

MUHIM CHEKLOV (Bo'lim 11 — "no fabrication" falsafasi, `public_apis`
bilan bir xil): bu funksiya "design pattern", "integration candidate",
"duplicate functionality" kabi XULOSA chiqarmaydi — bularning barchasi
QARASH/MULOHAZA talab qiladi, deterministik kod emas. Bu funksiya
FAQAT tekshiriladigan, haqiqiy faktlarni (til, litsenziya, yulduz,
README, papka tuzilishi) qaytaradi — xulosa chiqarish Brain/Research
agent (LLM)ning ishi, shu faktlarga qarab.

Qayta ishlatiladigan, `Tool`dan MUSTAQIL funksiya (Callable orqali
HTTP so'rovchisi in'ektsiya qilinadi) — `GitHubAnalyzeRepositoryTool`
VA `GitHubCompareRepositoriesTool` ikkalasi ham shuni chaqiradi,
mantiq ikki joyda TAKRORLANMAYDI.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from zet.tools.base import ToolError

RequestFn = Callable[[str, str], Awaitable[Any]]
"""`_GitHubHttpMixin._request`ning imzosi (method, path) -> javob.

QAYTISH TURI ATAYLAB `Any` (`dict[str, Any]` EMAS): GitHub API HAR XIL
shakl qaytaradi — `/repos/{owner}/{repo}` obyekt (dict), lekin
`/repos/{owner}/{repo}/contents/` PAPKA uchun MASSIV (list) qaytaradi.
`dict[str, Any]` deb yolg'on va'da berish `isinstance(x, list)`
tekshiruvini mypy uchun "unreachable" qilib qo'yardi."""

_README_EXCERPT_CHARS = 2000
"""README'ning butun matni EMAS — LLM kontekstini shishirmaslik uchun
qisqa parcha (birinchi taassurot/maqsad odatda boshida bo'ladi)."""


@dataclass(frozen=True, slots=True)
class RepositoryAnalysis:
    """Bitta repo haqidagi HAQIQIY, tekshirilgan faktlar to'plami."""

    repository: str
    name: str
    description: str | None
    primary_language: str | None
    languages: dict[str, int]
    """Til → bayt soni (GitHub `/languages` endpoint'idan, taxmin emas)."""
    license: str | None
    """SPDX identifikatori (masalan 'MIT') — GitHub aniqlay olmasa `None`."""
    stars: int
    forks: int
    open_issues: int
    topics: tuple[str, ...]
    default_branch: str
    last_pushed_at: str | None
    archived: bool
    homepage_url: str
    readme_excerpt: str | None
    readme_truncated: bool
    top_level_entries: tuple[str, ...]
    """Repo ILDIZIDAGI fayl/papka nomlari (ichki tarkib EMAS) — 'important
    modules' signalining eng arzon, eng ishonchli qismi."""


async def analyze_repository(request: RequestFn, repository: str) -> RepositoryAnalysis:
    """Bitta `owner/name` repo uchun HAQIQIY faktlarni yig'adi.

    Asosiy chaqiruv (`/repos/{owner}/{repo}`) muvaffaqiyatsiz bo'lsa —
    `ToolError` ko'tariladi (repo yo'q bo'lsa tahlil UMUMAN mumkin
    emas). Ikkilamchi chaqiruvlar (languages/readme/contents)
    ENG YAXSHI-HARAKAT — biri muvaffaqiyatsiz bo'lsa (masalan README
    yo'q), qolganlari baribir qaytadi, butun tahlil YIQILMAYDI.
    """
    meta = await request("GET", f"/repos/{repository}")

    languages: dict[str, int] = {}
    with contextlib.suppress(ToolError):
        languages = await request("GET", f"/repos/{repository}/languages")

    readme_excerpt: str | None = None
    readme_truncated = False
    try:
        readme_raw = await request("GET", f"/repos/{repository}/readme")
        content_b64 = readme_raw.get("content", "")
        decoded = base64.b64decode(content_b64.replace("\n", ""), validate=False)
        text = decoded.decode("utf-8", errors="replace")
        readme_truncated = len(text) > _README_EXCERPT_CHARS
        readme_excerpt = text[:_README_EXCERPT_CHARS]
    except (ToolError, binascii.Error, UnicodeDecodeError):
        pass

    top_level_entries: tuple[str, ...] = ()
    try:
        contents = await request("GET", f"/repos/{repository}/contents/")
        if isinstance(contents, list):
            top_level_entries = tuple(
                str(item.get("name")) for item in contents if isinstance(item, dict) and item.get("name")
            )
    except ToolError:
        pass

    license_info = meta.get("license") or {}
    return RepositoryAnalysis(
        repository=repository,
        name=str(meta.get("name") or repository),
        description=meta.get("description"),
        primary_language=meta.get("language"),
        languages=languages,
        license=license_info.get("spdx_id") if license_info.get("spdx_id") != "NOASSERTION" else None,
        stars=int(meta.get("stargazers_count") or 0),
        forks=int(meta.get("forks_count") or 0),
        open_issues=int(meta.get("open_issues_count") or 0),
        topics=tuple(meta.get("topics") or ()),
        default_branch=str(meta.get("default_branch") or "main"),
        last_pushed_at=meta.get("pushed_at"),
        archived=bool(meta.get("archived", False)),
        homepage_url=str(meta.get("html_url") or f"https://github.com/{repository}"),
        readme_excerpt=readme_excerpt,
        readme_truncated=readme_truncated,
        top_level_entries=top_level_entries,
    )


__all__ = ["RepositoryAnalysis", "RequestFn", "analyze_repository"]
