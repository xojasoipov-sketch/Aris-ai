"""public-apis → `ToolRegistry` ulanishi testlari (JB-18, Bo'lim 9) —
4 ta yangi tool ro'yxatdan o'tishi + ulashilgan `ProviderHealthTracker`/
`CatalogRepository` ISHORASI (nusxa emas) haqiqatan bitta ekanligi.

Umumiy "har tool TOOL_PERMISSIONS'da bormi" tekshiruvi allaqachon
`test_agent_factory.py::TestToolPermissionMap`da (generic, ro'yxatni
o'zi aylanadi) — bu fayl FAQAT public-apis'ga XOS ulanish tafsilotlarini
qo'shadi (dublikat emas).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.domain.enums import PermissionLevel, RiskLevel
from zet.integrations.public_apis.catalog.repository import CatalogRepository
from zet.integrations.public_apis.health.scoring import ProviderHealthTracker
from zet.tools.builtin import build_default_registry

_NEW_TOOL_NAMES = [
    "location.geocode",
    "location.reverse_geocode",
    "ip.lookup",
    "public_apis.search",
]


class TestNewToolsAreRegistered:
    def test_all_four_tools_present(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        names = set(registry.tool_names())
        for tool_name in _NEW_TOOL_NAMES:
            assert tool_name in names

    @pytest.mark.parametrize("tool_name", _NEW_TOOL_NAMES)
    def test_each_tool_is_read_low_risk(self, tmp_path: Path, tool_name: str) -> None:
        """Bo'lim 9: barcha 4 tashqi tool O'QISH-FAQAT, past xavf — hech
        biri Bo'lim 21 spec ustuvorligidan tashqariga chiqmaydi."""
        registry = build_default_registry(notes_dir=tmp_path)
        tool = registry.get(tool_name)
        assert tool.permission_level == PermissionLevel.READ
        assert tool.risk_level == RiskLevel.LOW

    def test_default_construction_does_not_crash_without_explicit_deps(
        self, tmp_path: Path
    ) -> None:
        """Hech qanday `public_apis_*` argument berilmasa ham — registry
        muvaffaqiyatli quriladi (izolyatsiyalangan ichki nusxalar bilan)."""
        registry = build_default_registry(notes_dir=tmp_path)
        for tool_name in _NEW_TOOL_NAMES:
            assert registry.get(tool_name) is not None


class TestSharedHealthTrackerIsSameInstance:
    def test_all_three_adapters_share_the_passed_tracker(self, tmp_path: Path) -> None:
        """`api/deps.py`ning butun maqsadi shu: bitta jarayon-umriga teng
        tracker — barcha so'rovlar BIR XIL statistikani ko'rishi kerak."""
        tracker = ProviderHealthTracker()
        registry = build_default_registry(notes_dir=tmp_path, public_apis_health_tracker=tracker)

        geocode = registry.get("location.geocode")
        reverse = registry.get("location.reverse_geocode")
        ip_lookup = registry.get("ip.lookup")

        assert geocode._health is tracker  # type: ignore[attr-defined]
        assert reverse._health is tracker  # type: ignore[attr-defined]
        assert ip_lookup._health is tracker  # type: ignore[attr-defined]

    def test_calls_through_one_adapter_are_visible_via_shared_tracker(self, tmp_path: Path) -> None:
        tracker = ProviderHealthTracker()
        registry = build_default_registry(notes_dir=tmp_path, public_apis_health_tracker=tracker)
        ip_lookup = registry.get("ip.lookup")

        import asyncio

        asyncio.run(ip_lookup.execute({"ip": "not-a-valid-ip"}))
        # `ToolValidationError` — tashqi so'rov qilinmadi, health YOZILMAYDI
        # (faqat HAQIQIY provayder chaqiruvlari kuzatiladi).
        assert tracker.snapshot("ipwho.is") is None


class TestSharedCatalogRepositoryIsSameInstance:
    def test_search_tool_reads_the_passed_repository_live(self, tmp_path: Path) -> None:
        """`PublicAPISearchTool` konstruksiya vaqtida BO'SH repository
        ko'rgan bo'lsa ham, keyinroq (masalan operator `refresh`
        chaqirgandan keyin) TO'LGAN holatni ko'rishi kerak — chunki bu
        REFERENCE, nusxa emas (`CapabilityDiscoveryTool` bilan bir xil
        naqsh, `capability_discovery.py`ga qarang)."""
        import asyncio
        import datetime as dt

        from zet.integrations.public_apis.catalog.models import (
            AuthType,
            PricingStatus,
            PublicAPIEntry,
            entry_id,
        )

        repo = CatalogRepository()
        registry = build_default_registry(notes_dir=tmp_path, public_apis_catalog_repository=repo)
        search_tool = registry.get("public_apis.search")

        # Ro'yxatga olingan PAYTDA katalog BO'SH edi.
        result_before = asyncio.run(search_tool.execute({"query": "currency"}))
        assert result_before.output["total_candidates"] == 0

        # Endi "operator" katalogni to'ldiradi — XUDDI SHU repository obyektiga.
        entry = PublicAPIEntry(
            id=entry_id(category="Currency Exchange", name="Currencylayer"),
            name="Currencylayer",
            description="Exchange rates",
            category="Currency Exchange",
            documentation_url="https://currencylayer.com/docs",
            homepage_url="https://currencylayer.com",
            auth_type=AuthType.API_KEY,
            https_supported=True,
            cors_supported=True,
            source="public-apis",
            source_repository="public-apis/public-apis",
            pricing_status=PricingStatus.UNKNOWN,
            api_key_required=True,
            provider="currencylayer.com",
        )
        repo.replace_all([entry], source_url="https://example.com", now=dt.datetime.now(dt.UTC))

        # Tool HALI HAM o'sha registratsiya vaqtidagi obyektga ISHORA
        # qiladi — endi to'lgan holatni ko'rishi kerak.
        result_after = asyncio.run(search_tool.execute({"query": "currency"}))
        assert result_after.output["total_candidates"] == 1
        assert result_after.output["candidates"][0]["name"] == "Currencylayer"
