"""GitHub Intelligence tool'lari (JB-19) — repo qidirish/tahlil/taqqoslash.

`github.read`/`github.write` (`github.py`, Bo'lim 7) BILAN ADASHTIRMASLIK
kerak — ular BITTA MA'LUM repo'ning issue/PR'lari bilan ISHLAYDI
(operatsion). Bu tool'lar esa YANGI repo'larni QIDIRISH/TAHLIL qilish
uchun (kashfiyot) — mavjud `_GitHubHttpMixin`ni QAYTA ISHLATADI (ikkinchi
HTTP klient/auth mantiqi QURILMAYDI), lekin butunlay boshqa semantik
maqsad.

QAT'IY CHEKLOV (spec Bo'lim 4/6): bu tool'lar HECH QACHON topilgan
repo'ning KODINI ishga tushirmaydi, klonlamaydi yoki bajarmaydi — faqat
GitHub REST/Search API orqali metadata (tavsif, til, litsenziya, README,
papka tuzilishi) o'qiydi. Xulosa chiqarish (bu naqsh foydalimi, qanday
moslashtirish kerak) — LLM (Brain/Research agent)ning ishi, tool esa
faqat TEKSHIRILADIGAN faktlarni beradi (Bo'lim 11 — "no fabrication").
"""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.integrations.github_intel.analyzer import RepositoryAnalysis, analyze_repository
from zet.tools.base import Tool, ToolError
from zet.tools.builtin.github import _GitHubHttpMixin, _validate_repo

_SEARCH_URL = "/search/repositories"
_MAX_COMPARE = 5


def _analysis_to_dict(analysis: RepositoryAnalysis) -> dict[str, Any]:
    return dataclasses.asdict(analysis)


class GitHubSearchRepositoryTool(_GitHubHttpMixin, Tool):
    """GitHub'da mavzu/kalit so'z bo'yicha repo qidiradi (GitHub Search API)."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token=token, client=client)

    @property
    def name(self) -> str:
        return "github.search_repository"

    @property
    def description(self) -> str:
        return (
            "O'QISH: GitHub'da kalit so'z/mavzu bo'yicha ochiq repozitoriylarni "
            "qidiradi (masalan 'JARVIS uchun yaxshiroq memory architecture "
            "top' so'ralganda). Faqat METADATA qaytaradi (nom, tavsif, til, "
            "yulduz, litsenziya) — hech qanday kodni yuklamaydi yoki ishga "
            "tushirmaydi. Bitta repo'ni CHUQUR tahlil qilish uchun EMAS — "
            "buning uchun github.analyze_repository."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Qidiruv so'zi/iborasi (masalan 'AI agent framework').",
                },
                "language": {
                    "type": "string",
                    "description": "Ixtiyoriy: dasturlash tili bo'yicha filtrlash (masalan 'Python').",
                },
                "min_stars": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Ixtiyoriy: eng kam yulduz soni.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Nechta natija (sukut 5, max 20).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = str(params["query"]).strip()
        if not query:
            raise ToolError("Qidiruv so'zi bo'sh bo'lishi mumkin emas")

        qualifiers = [query]
        language = params.get("language")
        if language:
            qualifiers.append(f"language:{language}")
        min_stars = params.get("min_stars")
        if isinstance(min_stars, int) and min_stars > 0:
            qualifiers.append(f"stars:>={min_stars}")

        limit = params.get("limit")
        per_page = limit if isinstance(limit, int) and 0 < limit <= 20 else 5

        response = await self._request(
            "GET",
            _SEARCH_URL,
            params={
                "q": " ".join(qualifiers),
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
            },
        )

        items = response.get("items") or []
        results = [
            {
                "repository": item.get("full_name"),
                "description": item.get("description"),
                "language": item.get("language"),
                "stars": item.get("stargazers_count", 0),
                "license": (item.get("license") or {}).get("spdx_id"),
                "topics": item.get("topics") or [],
                "archived": item.get("archived", False),
                "homepage_url": item.get("html_url"),
            }
            for item in items
        ]
        return {
            "query": query,
            "total_count": response.get("total_count", len(results)),
            "results": results,
        }


class GitHubAnalyzeRepositoryTool(_GitHubHttpMixin, Tool):
    """Bitta repo haqida HAQIQIY faktlarni to'playdi (til, litsenziya, README, tuzilish)."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token=token, client=client)

    @property
    def name(self) -> str:
        return "github.analyze_repository"

    @property
    def description(self) -> str:
        return (
            "O'QISH: bitta MA'LUM repo (owner/name) haqida chuqurroq HAQIQIY "
            "ma'lumot — til taqsimoti, litsenziya, README parchasi, ildiz "
            "papka tuzilishi, yulduz/fork soni. Bu FAKT to'plami — 'bu "
            "arxitektura naqshi yaxshimi' kabi XULOSANI o'zi chiqarmaydi, "
            "faktlarga qarab xulosani siz chiqarasiz. Repo NOMINI oldindan "
            "bilmasangiz avval github.search_repository ishlating."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "'owner/name' formatida (masalan 'donnemartin/system-design-primer').",
                },
            },
            "required": ["repository"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        # 4 tagacha ketma-ket HTTP chaqiruv (meta/languages/readme/contents)
        # — default 30s ba'zan yetmasligi mumkin.
        return 45

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        repository = str(params["repository"]).strip()
        _validate_repo(repository)
        analysis = await analyze_repository(self._request, repository)
        return _analysis_to_dict(analysis)


class GitHubCompareRepositoriesTool(_GitHubHttpMixin, Tool):
    """Bir nechta repo'ni yonma-yon HAQIQIY faktlar bilan taqqoslaydi."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token=token, client=client)

    @property
    def name(self) -> str:
        return "github.compare_repositories"

    @property
    def description(self) -> str:
        return (
            "O'QISH: 2 dan 5 tagacha repo'ni yonma-yon taqqoslaydi (til, "
            "litsenziya, yulduz, README) — 'X yoki Y qaysi biri yaxshiroq' "
            "kabi savolga HAQIQIY faktlar bilan javob tayyorlash uchun. "
            "Har biri uchun github.analyze_repository bilan bir xil "
            "ma'lumotni qaytaradi, faqat bir chaqiruvda."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repositories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": _MAX_COMPARE,
                    "description": "'owner/name' formatidagi repo nomlari ro'yxati (2-5 ta).",
                },
            },
            "required": ["repositories"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        # Ketma-ket (bir vaqtda emas — GitHub rate-limit portlashining
        # oldini olish uchun ataylab) — max 5 repo x 4 chaqiruv.
        return 90

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        repositories = params["repositories"]
        if not isinstance(repositories, list) or not (2 <= len(repositories) <= _MAX_COMPARE):
            raise ToolError(f"2 dan {_MAX_COMPARE} tagacha repo kerak")

        results: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for repository in repositories:
            repo_str = str(repository).strip()
            try:
                _validate_repo(repo_str)
                analysis = await analyze_repository(self._request, repo_str)
                results.append(_analysis_to_dict(analysis))
            except ToolError as exc:
                # Bo'lim 3 ruhida: bitta repo topilmasa BUTUN taqqoslash
                # yiqilmaydi — nechta muvaffaqiyatli bo'lsa, o'shani beradi,
                # muvaffaqiyatsizlarni OCHIQ ko'rsatadi (jimgina yashirmaydi).
                errors[repo_str] = str(exc)

        return {
            "compared": len(results),
            "requested": len(repositories),
            "results": results,
            "errors": errors,
        }


__all__ = [
    "GitHubAnalyzeRepositoryTool",
    "GitHubCompareRepositoriesTool",
    "GitHubSearchRepositoryTool",
]
