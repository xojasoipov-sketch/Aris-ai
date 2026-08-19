"""`public_apis.search` Brain tooli testlari (JB-18) —
`PublicAPISearchTool`, `CapabilityDiscoveryTool` bilan bir xil naqsh
(registry/repository ISHORASI, so'rov vaqtida o'qiladi).

MUHIM: LLM javobida "ZET buni bajara oladi" deb adashtirmaslik —
JB-16 CASE B bilan bir xil xato sinfi. Shuning uchun bu testlar
ayniqsa `summary_text`/`executable_now` maydoni HAR DOIM to'g'ri
signal berishini qulflaydi.
"""

from __future__ import annotations

import datetime as dt

from zet.domain.enums import PermissionLevel, RiskLevel
from zet.integrations.public_apis.catalog.models import (
    APIStatus,
    AuthType,
    PricingStatus,
    PublicAPIEntry,
    entry_id,
)
from zet.integrations.public_apis.catalog.repository import CatalogRepository
from zet.tools.builtin.public_apis_search import PublicAPISearchTool


def _entry(
    name: str, *, category: str = "Geocoding", status: APIStatus = APIStatus.DISCOVERED
) -> PublicAPIEntry:
    return PublicAPIEntry(
        id=entry_id(category=category, name=name),
        name=name,
        description=f"{name} — {category} xizmati",
        category=category,
        documentation_url=f"https://{name.lower()}.example/docs",
        homepage_url=f"https://{name.lower()}.example",
        auth_type=AuthType.NONE,
        https_supported=True,
        cors_supported=True,
        source="public-apis",
        source_repository="public-apis/public-apis",
        pricing_status=PricingStatus.UNKNOWN,
        api_key_required=False,
        provider=f"{name.lower()}.example",
        status=status,
    )


class TestPublicAPISearchToolContract:
    def test_name_permission_risk(self) -> None:
        tool = PublicAPISearchTool()
        assert tool.name == "public_apis.search"
        assert tool.permission_level == PermissionLevel.READ
        assert tool.risk_level == RiskLevel.LOW  # jadvalda yo'q — fallback LOW, to'g'ri
        assert tool.idempotent is True

    def test_input_schema_requires_query(self) -> None:
        schema = PublicAPISearchTool().input_schema
        assert schema["required"] == ["query"]
        assert "query" in schema["properties"]
        assert "limit" in schema["properties"]


class TestNoRepositoryOrEmptyCatalog:
    async def test_no_repository_returns_honest_empty_state(self) -> None:
        tool = PublicAPISearchTool(repository=None)
        result = await tool.execute({"query": "currency"})
        assert result.success is True
        assert result.output["total_candidates"] == 0
        assert result.output["candidates"] == []

    async def test_empty_repository_says_not_yet_synced_not_no_results(self) -> None:
        """"Hali sinxronlanmagan" bilan "bunday API yo'q" — ikki XIL
        xabar (Bo'lim: taxmin qilinmaydi)."""
        repo = CatalogRepository()
        tool = PublicAPISearchTool(repository=repo)
        result = await tool.execute({"query": "currency"})
        assert result.success is True
        assert "sinxronlanmagan" in result.output["summary_text"]

    async def test_blank_query_returns_empty_without_touching_repository(self) -> None:
        repo = CatalogRepository()
        entries = [_entry("X")]
        repo.replace_all(entries, source_url="https://example.com", now=dt.datetime.now(dt.UTC))
        tool = PublicAPISearchTool(repository=repo)
        result = await tool.execute({"query": "   "})
        assert result.output["total_candidates"] == 0


class TestSearchResultsHonesty:
    def _synced_repo(self) -> CatalogRepository:
        repo = CatalogRepository()
        entries = [
            _entry("Geocodio", category="Geocoding", status=APIStatus.DISCOVERED),
            _entry("MyEnabledLocationTool", category="Geocoding", status=APIStatus.ENABLED),
            _entry("Weatherstack", category="Weather", status=APIStatus.DISCOVERED),
        ]
        repo.replace_all(entries, source_url="https://example.com", now=dt.datetime.now(dt.UTC))
        return repo

    async def test_finds_matching_entries(self) -> None:
        tool = PublicAPISearchTool(repository=self._synced_repo())
        result = await tool.execute({"query": "geocoding"})
        names = {c["name"] for c in result.output["candidates"]}
        assert "Geocodio" in names
        assert "MyEnabledLocationTool" in names
        assert "Weatherstack" not in names

    async def test_no_match_says_not_in_catalog_not_generic_empty(self) -> None:
        tool = PublicAPISearchTool(repository=self._synced_repo())
        result = await tool.execute({"query": "totally-unrelated-xyz-keyword"})
        assert result.output["total_candidates"] == 0
        assert "yo'q" in result.output["summary_text"]

    async def test_discovered_status_marked_not_executable(self) -> None:
        """ENG MUHIM xavfsizlik/halollik tekshiruvi: DISCOVERED yozuv
        `executable_now=False` bo'lishi va matn buni ochiq aytishi kerak
        — aks holda LLM "ZET buni qila oladi" deb noto'g'ri xulosa
        chiqarishi mumkin (JB-16 CASE B bilan bir xil xato sinfi)."""
        tool = PublicAPISearchTool(repository=self._synced_repo())
        result = await tool.execute({"query": "Geocodio"})
        candidate = next(c for c in result.output["candidates"] if c["name"] == "Geocodio")
        assert candidate["executable_now"] is False
        assert candidate["status"] == "discovered"
        assert "OLMAYDI" in result.output["summary_text"]

    async def test_enabled_status_marked_executable(self) -> None:
        tool = PublicAPISearchTool(repository=self._synced_repo())
        result = await tool.execute({"query": "MyEnabledLocationTool"})
        candidate = next(
            c for c in result.output["candidates"] if c["name"] == "MyEnabledLocationTool"
        )
        assert candidate["executable_now"] is True
        assert candidate["status"] == "enabled"
        assert "ULANGAN" in result.output["summary_text"]

    async def test_description_warns_against_overclaiming(self) -> None:
        """Planner tool tanlash paytida o'qiydigan matn — ANIQ ogohlantirish
        bo'lishi kerak, aks holda tool noto'g'ri kontekstda tanlanadi."""
        description = PublicAPISearchTool().description.lower()
        assert "kashfiyot" in description
        assert "ishlamaydi" in description or "olmaydi" in description or "aytmang" in description

    async def test_limit_is_respected_and_clamped(self) -> None:
        repo = CatalogRepository()
        entries = [
            _entry(f"CurrencyApi{i}", category="Currency Exchange", status=APIStatus.DISCOVERED)
            for i in range(5)
        ]
        repo.replace_all(entries, source_url="https://example.com", now=dt.datetime.now(dt.UTC))
        tool = PublicAPISearchTool(repository=repo)

        result = await tool.execute({"query": "currency", "limit": 2})
        assert result.output["total_candidates"] == 2

        # Haddan tashqari katta limit — max 25ga qisqartiriladi (portlashning oldi olinadi).
        result_big = await tool.execute({"query": "currency", "limit": 10_000})
        assert result_big.output["total_candidates"] <= 25
