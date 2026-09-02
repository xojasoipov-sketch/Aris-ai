"""public-apis discovery qatlami testlari (JB-18, Bo'lim 4/5/14) —
qidiruv, reyting, capability xaritalash, ENABLED provayder tanlovi.

Hammasi DETERMINISTIK, LLM chaqiruvisiz — vazifa tavsifining ochiq
talabi ("Do not create unnecessary LLM calls for tool
enumeration/classification").
"""

from __future__ import annotations

from zet.integrations.public_apis.catalog.models import (
    APIStatus,
    AuthType,
    PricingStatus,
    PublicAPIEntry,
    entry_id,
)
from zet.integrations.public_apis.discovery.capability_mapper import capabilities_for_category
from zet.integrations.public_apis.discovery.matcher import enabled_providers_for_capability
from zet.integrations.public_apis.discovery.ranker import rank_candidates
from zet.integrations.public_apis.discovery.search import (
    SearchMatch,
    search_by_capability,
    search_catalog,
)


def _entry(
    name: str,
    *,
    category: str = "Geocoding",
    description: str = "",
    auth_type: AuthType = AuthType.NONE,
    https_supported: bool = True,
    status: APIStatus = APIStatus.DISCOVERED,
    trust_score: float = 0.0,
    health_score: float | None = None,
    capabilities: tuple[str, ...] = (),
    provider: str | None = None,
) -> PublicAPIEntry:
    return PublicAPIEntry(
        id=entry_id(category=category, name=name),
        name=name,
        description=description or f"{name} tavsifi",
        category=category,
        documentation_url=f"https://{name.lower()}.example/docs",
        homepage_url=f"https://{name.lower()}.example",
        auth_type=auth_type,
        https_supported=https_supported,
        cors_supported=True,
        source="public-apis",
        source_repository="public-apis/public-apis",
        pricing_status=PricingStatus.UNKNOWN,
        api_key_required=auth_type != AuthType.NONE,
        provider=provider or f"{name.lower()}.example",
        status=status,
        trust_score=trust_score,
        health_score=health_score,
        capabilities=capabilities,
    )


# ── search.py ────────────────────────────────────────────────────────


class TestSearchCatalog:
    def test_matches_by_name_and_description(self) -> None:
        entries = [
            _entry("Geocodio", description="Geocoding and address lookup"),
            _entry("Weatherstack", category="Weather", description="Weather forecast"),
        ]
        matches = search_catalog(entries, ["geocoding"])
        assert len(matches) == 1
        assert matches[0].entry.name == "Geocodio"

    def test_score_counts_all_keyword_occurrences_across_fields(self) -> None:
        entries = [
            _entry(
                "CurrencyAPI",
                category="Currency Exchange",
                description="currency currency rate conversion",
            ),
            _entry("Other", category="Weather", description="weather only"),
        ]
        matches = search_catalog(entries, ["currency"])
        assert len(matches) == 1
        assert matches[0].score >= 3  # nom + kategoriya + tavsifda 2 marta

    def test_empty_keywords_returns_empty(self) -> None:
        entries = [_entry("X")]
        assert search_catalog(entries, []) == []
        assert search_catalog(entries, ["   "]) == []

    def test_no_match_excludes_entry(self) -> None:
        entries = [_entry("Geocodio", description="geocoding")]
        assert search_catalog(entries, ["nonexistent-keyword-xyz"]) == []

    def test_respects_limit(self) -> None:
        entries = [_entry(f"Api{i}", description="currency") for i in range(10)]
        matches = search_catalog(entries, ["currency"], limit=3)
        assert len(matches) == 3

    def test_sorted_by_score_descending(self) -> None:
        entries = [
            _entry("Low", description="currency"),
            _entry("High", description="currency currency currency currency"),
        ]
        matches = search_catalog(entries, ["currency"])
        assert matches[0].entry.name == "High"

    def test_case_insensitive(self) -> None:
        entries = [_entry("Geocodio", description="GEOCODING service")]
        matches = search_catalog(entries, ["Geocoding"])
        assert len(matches) == 1

    def test_matches_capabilities_field(self) -> None:
        entries = [_entry("X", description="unrelated", capabilities=("geocoding", "location"))]
        matches = search_catalog(entries, ["location"])
        assert len(matches) == 1


class TestSearchByCapability:
    def test_returns_entries_with_matching_capability_tag(self) -> None:
        entries = [
            _entry("A", capabilities=("geocoding",)),
            _entry("B", capabilities=("weather",)),
        ]
        result = search_by_capability(entries, "geocoding")
        assert [e.name for e in result] == ["A"]

    def test_case_insensitive_tag_match(self) -> None:
        entries = [_entry("A", capabilities=("Geocoding",))]
        assert len(search_by_capability(entries, "geocoding")) == 1

    def test_no_match_returns_empty(self) -> None:
        entries = [_entry("A", capabilities=("weather",))]
        assert search_by_capability(entries, "geocoding") == []


# ── ranker.py ────────────────────────────────────────────────────────


class TestRankCandidates:
    def test_empty_matches_returns_empty(self) -> None:
        assert rank_candidates([]) == []

    def test_enabled_status_ranks_above_discovered_with_equal_relevance(self) -> None:
        enabled = _entry("Enabled", status=APIStatus.ENABLED, health_score=0.9)
        discovered = _entry("Discovered", status=APIStatus.DISCOVERED)
        matches = [SearchMatch(entry=enabled, score=1), SearchMatch(entry=discovered, score=1)]
        ranked = rank_candidates(matches)
        assert ranked[0].name == "Enabled"
        assert ranked[0].composite_score > ranked[1].composite_score

    def test_https_and_auth_none_bonus_ranks_above_no_https_apikey(self) -> None:
        good = _entry("Good", https_supported=True, auth_type=AuthType.NONE)
        worse = _entry("Worse", https_supported=False, auth_type=AuthType.OAUTH)
        matches = [SearchMatch(entry=good, score=1), SearchMatch(entry=worse, score=1)]
        ranked = rank_candidates(matches)
        assert ranked[0].name == "Good"

    def test_unmeasured_health_is_neutral_not_punished(self) -> None:
        """`health_score=None` (hali tekshirilmagan) — past sog'liqli
        (masalan 0.1) yozuvdan PASTROQ emas bo'lishi kerak (neytral 0.5)."""
        untested = _entry("Untested", health_score=None)
        poor_health = _entry("PoorHealth", health_score=0.1)
        matches = [
            SearchMatch(entry=untested, score=1),
            SearchMatch(entry=poor_health, score=1),
        ]
        ranked = rank_candidates(matches)
        untested_score = next(c.composite_score for c in ranked if c.name == "Untested")
        poor_score = next(c.composite_score for c in ranked if c.name == "PoorHealth")
        assert untested_score > poor_score

    def test_reasons_are_transparent_not_black_box(self) -> None:
        entry = _entry(
            "X", status=APIStatus.ENABLED, https_supported=True,
            auth_type=AuthType.NONE, health_score=0.8,
        )
        ranked = rank_candidates([SearchMatch(entry=entry, score=1)])
        reasons = " ".join(ranked[0].reasons)
        assert "ZET'da ulangan" in reasons
        assert "HTTPS" in reasons
        assert "kalit talab qilmaydi" in reasons
        assert "sog'liq" in reasons

    def test_composite_score_never_exceeds_one(self) -> None:
        entry = _entry(
            "Perfect", status=APIStatus.ENABLED, https_supported=True,
            auth_type=AuthType.NONE, health_score=1.0, trust_score=1.0,
        )
        ranked = rank_candidates([SearchMatch(entry=entry, score=1)])
        assert ranked[0].composite_score <= 1.0

    def test_relevance_is_normalized_to_top_scorer(self) -> None:
        a = _entry("A")
        b = _entry("B")
        matches = [SearchMatch(entry=a, score=10), SearchMatch(entry=b, score=5)]
        ranked = rank_candidates(matches)
        top = next(c for c in ranked if c.name == "A")
        assert top.relevance == 1.0


# ── capability_mapper.py ────────────────────────────────────────────


class TestCapabilitiesForCategory:
    def test_known_category_maps_to_expected_tags(self) -> None:
        assert capabilities_for_category("Geocoding") == ("geocoding", "location")

    def test_case_and_whitespace_insensitive(self) -> None:
        assert capabilities_for_category("  geocoding  ") == ("geocoding", "location")

    def test_unknown_category_returns_empty_tuple_not_error(self) -> None:
        """Xaritada yo'q kategoriya — XATO emas, bo'sh tuple (hali ZET
        capability tiliga tarjima qilinmagan, degani)."""
        assert capabilities_for_category("Some Totally Unknown Category") == ()


# ── matcher.py ───────────────────────────────────────────────────────


class TestEnabledProvidersForCapability:
    def test_only_enabled_status_returned(self) -> None:
        enabled = _entry("Enabled", status=APIStatus.ENABLED, capabilities=("geocoding",))
        discovered = _entry("Discovered", status=APIStatus.DISCOVERED, capabilities=("geocoding",))
        result = enabled_providers_for_capability([enabled, discovered], "geocoding")
        assert [e.name for e in result] == ["Enabled"]

    def test_sorted_by_health_descending(self) -> None:
        low = _entry("Low", status=APIStatus.ENABLED, capabilities=("geocoding",), health_score=0.3)
        high = _entry("High", status=APIStatus.ENABLED, capabilities=("geocoding",), health_score=0.9)
        result = enabled_providers_for_capability([low, high], "geocoding")
        assert [e.name for e in result] == ["High", "Low"]

    def test_unmeasured_health_sorted_as_neutral(self) -> None:
        untested = _entry("Untested", status=APIStatus.ENABLED, capabilities=("geocoding",), health_score=None)
        poor = _entry("Poor", status=APIStatus.ENABLED, capabilities=("geocoding",), health_score=0.1)
        result = enabled_providers_for_capability([poor, untested], "geocoding")
        assert result[0].name == "Untested"  # 0.5 neytral > 0.1

    def test_no_matching_capability_returns_empty(self) -> None:
        entry = _entry("X", status=APIStatus.ENABLED, capabilities=("weather",))
        assert enabled_providers_for_capability([entry], "geocoding") == []
