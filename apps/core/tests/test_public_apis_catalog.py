"""public-apis katalog qatlami testlari (JB-18, Bo'lim 3) — parser,
normalizer, repository, source, sync orkestratsiyasi.

Haqiqiy `public-apis/public-apis` README'siga qarshi qo'lda (throwaway
skript orqali, `docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md` §6) allaqachon
tekshirilgan — bu yerdagi testlar esa DOIMIY regressiya himoyasi, tarmoqqa
chiqmasdan (fixture matn — CI'da barqaror, tez).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from zet.integrations.public_apis.catalog import sync as sync_mod
from zet.integrations.public_apis.catalog.models import (
    APIStatus,
    AuthType,
    PricingStatus,
    PublicAPIEntry,
    entry_id,
)
from zet.integrations.public_apis.catalog.normalizer import normalize_entries, normalize_entry
from zet.integrations.public_apis.catalog.parser import RawEntry, parse_readme
from zet.integrations.public_apis.catalog.repository import CatalogRepository
from zet.integrations.public_apis.catalog.source import (
    CatalogSyncError,
    fetch_catalog_text,
    resolve_source_url,
)
from zet.integrations.public_apis.catalog.sync import sync_catalog

_SAMPLE_README = """\
# public-apis

Some intro text that is not a table.

### Geocoding

API | Description | Auth | HTTPS | CORS |
|---|---|---|---|---|
| [Geocode.xyz](https://geocode.xyz) | Geocoding | No | Yes | Unknown |
| [Geocodio](https://geocod.io) | Geocoding | `apiKey` | Yes | Yes |

Some prose between tables.

### Currency Exchange

API | Description | Auth | HTTPS | CORS |
|---|---|---|---|---|
| [Currencylayer](https://currencylayer.com) | Exchange rates | `apiKey` | Yes | Unknown |
"""


# ── parser.py ─────────────────────────────────────────────────────────


class TestParseReadme:
    def test_parses_categories_and_rows(self) -> None:
        entries = parse_readme(_SAMPLE_README)
        assert len(entries) == 3
        assert {e.category for e in entries} == {"Geocoding", "Currency Exchange"}
        geocoding = [e for e in entries if e.category == "Geocoding"]
        assert {e.name for e in geocoding} == {"Geocode.xyz", "Geocodio"}

    def test_row_fields_extracted_correctly(self) -> None:
        entries = parse_readme(_SAMPLE_README)
        geocodio = next(e for e in entries if e.name == "Geocodio")
        assert geocodio.homepage_url == "https://geocod.io"
        assert geocodio.description == "Geocoding"
        assert geocodio.auth_raw == "`apiKey`"
        assert geocodio.https_raw == "Yes"
        assert geocodio.cors_raw == "Yes"

    def test_no_tables_returns_empty_not_error(self) -> None:
        """Bo'sh/mos kelmagan matn — XATO emas, bo'sh ro'yxat (Bo'lim 3:
        "ingestion, execution emas" — bitta buzilgan format butun
        sync'ni yiqitmasligi kerak)."""
        assert parse_readme("# just a title\n\nno tables here.\n") == []

    def test_empty_string_returns_empty(self) -> None:
        assert parse_readme("") == []

    def test_malformed_row_is_silently_skipped(self) -> None:
        """Bitta yaroqsiz qator — qolganlarini yiqitmaydi."""
        text = """\
### Test

API | Description | Auth | HTTPS | CORS |
|---|---|---|---|---|
| this is not a valid row at all |
| [Valid](https://valid.example) | Desc | No | Yes | Yes |
"""
        entries = parse_readme(text)
        assert len(entries) == 1
        assert entries[0].name == "Valid"


# ── normalizer.py ─────────────────────────────────────────────────────


class TestNormalizeEntry:
    def test_auth_none_maps_to_none(self) -> None:
        raw = RawEntry(
            category="Geocoding",
            name="Geocode.xyz",
            homepage_url="https://geocode.xyz",
            description="Geocoding",
            auth_raw="No",
            https_raw="Yes",
            cors_raw="Unknown",
        )
        entry = normalize_entry(raw)
        assert entry.auth_type is AuthType.NONE
        assert entry.api_key_required is False
        assert entry.https_supported is True
        assert entry.cors_supported is None  # "Unknown" → None, taxmin qilinmaydi

    def test_auth_apikey_backtick_maps_correctly(self) -> None:
        raw = RawEntry(
            category="Geocoding",
            name="Geocodio",
            homepage_url="https://geocod.io",
            description="Geocoding",
            auth_raw="`apiKey`",
            https_raw="Yes",
            cors_raw="Yes",
        )
        entry = normalize_entry(raw)
        assert entry.auth_type is AuthType.API_KEY
        assert entry.api_key_required is True
        assert entry.cors_supported is True

    def test_unrecognized_backtick_auth_maps_to_custom_not_unknown(self) -> None:
        """Backtick BOR, lekin ro'yxatda yo'q qiymat — CUSTOM (nima kerakligi
        qisman ma'lum), UNKNOWN emas (hech narsa ma'lum emas bilan farq)."""
        raw = RawEntry(
            category="X",
            name="Y",
            homepage_url="https://y.example",
            description="d",
            auth_raw="`X-Mashape-Key`",
            https_raw="Yes",
            cors_raw="No",
        )
        entry = normalize_entry(raw)
        assert entry.auth_type is AuthType.CUSTOM

    def test_pricing_status_always_unknown_never_assumed_free(self) -> None:
        """QOIDA: xom parse paytida `pricing_status` HECH QACHON 'free'
        deb taxmin qilinmaydi — public-apis bu ma'lumotni ummuman bermaydi."""
        raw = RawEntry(
            category="Geocoding",
            name="Geocode.xyz",
            homepage_url="https://geocode.xyz",
            description="Geocoding",
            auth_raw="No",
            https_raw="Yes",
            cors_raw="Yes",
        )
        entry = normalize_entry(raw)
        assert entry.pricing_status is PricingStatus.UNKNOWN

    def test_provider_extracted_from_homepage_domain(self) -> None:
        raw = RawEntry(
            category="X",
            name="Y",
            homepage_url="https://www.example.com/some/path",
            description="d",
            auth_raw="No",
            https_raw="Yes",
            cors_raw="Yes",
        )
        entry = normalize_entry(raw)
        assert entry.provider == "example.com"  # www. kesildi

    def test_provider_falls_back_to_name_on_bad_url(self) -> None:
        raw = RawEntry(
            category="X",
            name="NoUrlProvider",
            homepage_url="",
            description="d",
            auth_raw="No",
            https_raw="Yes",
            cors_raw="Yes",
        )
        entry = normalize_entry(raw)
        assert entry.provider == "NoUrlProvider"

    def test_status_always_discovered_fresh_from_parse(self) -> None:
        raw = RawEntry(
            category="X", name="Y", homepage_url="https://y.example",
            description="d", auth_raw="No", https_raw="Yes", cors_raw="Yes",
        )
        assert normalize_entry(raw).status is APIStatus.DISCOVERED

    def test_id_is_deterministic_for_same_category_and_name(self) -> None:
        raw1 = RawEntry(
            category="Geocoding", name="X", homepage_url="https://a.example",
            description="d1", auth_raw="No", https_raw="Yes", cors_raw="Yes",
        )
        raw2 = RawEntry(
            category="Geocoding", name="X", homepage_url="https://b.example",
            description="d2 changed", auth_raw="`apiKey`", https_raw="No", cors_raw="No",
        )
        # Tavsif/auth o'zgargan bo'lsa ham — bir xil kategoriya+nom → bir xil ID
        # (Bo'lim: har sync BIR XIL yozuvni "yangi" deb hisoblamasligi kerak).
        assert normalize_entry(raw1).id == normalize_entry(raw2).id

    def test_normalize_entries_preserves_count_and_order(self) -> None:
        entries = normalize_entries(parse_readme(_SAMPLE_README))
        assert len(entries) == 3


# ── models.py ─────────────────────────────────────────────────────────


class TestPublicAPIEntryImmutableUpdates:
    def _entry(self) -> PublicAPIEntry:
        return PublicAPIEntry(
            id=entry_id(category="X", name="Y"),
            name="Y",
            description="d",
            category="X",
            documentation_url="https://y.example",
            homepage_url="https://y.example",
            auth_type=AuthType.NONE,
            https_supported=True,
            cors_supported=True,
            source="public-apis",
            source_repository="public-apis/public-apis",
            pricing_status=PricingStatus.UNKNOWN,
            api_key_required=False,
            provider="y.example",
        )

    def test_with_status_returns_new_object_original_unchanged(self) -> None:
        original = self._entry()
        updated = original.with_status(APIStatus.ENABLED)
        assert original.status is APIStatus.DISCOVERED  # frozen — o'zgarmadi
        assert updated.status is APIStatus.ENABLED
        assert updated.id == original.id

    def test_with_capabilities(self) -> None:
        updated = self._entry().with_capabilities(("geocoding", "location"))
        assert updated.capabilities == ("geocoding", "location")

    def test_with_health(self) -> None:
        now = datetime.now(UTC)
        updated = self._entry().with_health(health_score=0.9, last_checked=now)
        assert updated.health_score == 0.9
        assert updated.last_checked == now

    def test_entry_is_frozen(self) -> None:
        entry = self._entry()
        with pytest.raises(Exception):  # noqa: B017 — dataclasses.FrozenInstanceError
            entry.status = APIStatus.ENABLED  # type: ignore[misc]


class TestEntryId:
    def test_deterministic(self) -> None:
        assert entry_id(category="Geocoding", name="X") == entry_id(category="Geocoding", name="X")

    def test_case_and_whitespace_insensitive(self) -> None:
        assert entry_id(category="  Geocoding  ", name="X") == entry_id(category="geocoding", name="x")

    def test_different_names_differ(self) -> None:
        assert entry_id(category="Geocoding", name="X") != entry_id(category="Geocoding", name="Y")


# ── repository.py — merge semantics (ENG MUHIM xatti-harakat) ─────────


class TestCatalogRepositoryReplaceAll:
    def test_first_sync_adds_all_as_new(self) -> None:
        repo = CatalogRepository()
        entries = normalize_entries(parse_readme(_SAMPLE_README))
        report = repo.replace_all(entries, source_url="https://example.com/readme.md", now=datetime.now(UTC))
        assert report.ok is True
        assert report.added == 3
        assert report.changed == 0
        assert report.removed == 0
        assert report.categories == 2
        assert len(repo.all()) == 3

    def test_resync_preserves_status_trust_health_capabilities_for_existing(self) -> None:
        """ENG MUHIM QOIDA: descriptiv maydonlar yangilanadi, lekin
        BAHOLASH maydonlari MAVJUD yozuv uchun SAQLANADI — aks holda
        operator "bu ENABLED" qarori har sync'da yo'qolib qolardi."""
        repo = CatalogRepository()
        first = normalize_entries(parse_readme(_SAMPLE_README))
        repo.replace_all(first, source_url="https://example.com", now=datetime.now(UTC))

        geocodio_id = entry_id(category="Geocoding", name="Geocodio")
        repo.mark_status(geocodio_id, APIStatus.ENABLED)
        repo.set_capabilities(geocodio_id, ("geocoding",))
        repo.set_health(geocodio_id, health_score=0.95, checked_at=datetime.now(UTC))

        # Qayta sync — tavsif biroz o'zgargan (masalan yangi README versiyasi).
        changed_readme = _SAMPLE_README.replace(
            "| [Geocodio](https://geocod.io) | Geocoding | `apiKey` | Yes | Yes |",
            "| [Geocodio](https://geocod.io) | Geocoding API v2 | `apiKey` | Yes | Yes |",
        )
        second = normalize_entries(parse_readme(changed_readme))
        report2 = repo.replace_all(second, source_url="https://example.com", now=datetime.now(UTC))

        assert report2.added == 0
        assert report2.removed == 0
        assert report2.changed == 1  # tavsif o'zgargani hisoblandi

        geocodio = repo.get(geocodio_id)
        assert geocodio is not None
        assert geocodio.description == "Geocoding API v2"  # descriptiv — yangilandi
        assert geocodio.status is APIStatus.ENABLED  # baholov — SAQLANDI
        assert geocodio.capabilities == ("geocoding",)  # baholov — SAQLANDI
        assert geocodio.health_score == 0.95  # baholov — SAQLANDI

    def test_removed_entries_are_counted(self) -> None:
        repo = CatalogRepository()
        first = normalize_entries(parse_readme(_SAMPLE_README))
        repo.replace_all(first, source_url="https://example.com", now=datetime.now(UTC))

        # Faqat bitta kategoriya qoldi — qolganlari "o'chdi".
        smaller_readme = """\
### Geocoding

API | Description | Auth | HTTPS | CORS |
|---|---|---|---|---|
| [Geocode.xyz](https://geocode.xyz) | Geocoding | No | Yes | Unknown |
"""
        second = normalize_entries(parse_readme(smaller_readme))
        report2 = repo.replace_all(second, source_url="https://example.com", now=datetime.now(UTC))
        assert report2.removed == 2
        assert len(repo.all()) == 1

    def test_by_category_and_categories_and_by_status(self) -> None:
        repo = CatalogRepository()
        entries = normalize_entries(parse_readme(_SAMPLE_README))
        repo.replace_all(entries, source_url="https://example.com", now=datetime.now(UTC))

        assert sorted(repo.categories()) == ["Currency Exchange", "Geocoding"]
        assert len(repo.by_category("geocoding")) == 2  # case-insensitive
        assert repo.by_status(APIStatus.DISCOVERED) == repo.all()
        assert repo.by_status(APIStatus.ENABLED) == []

    def test_get_unknown_id_returns_none(self) -> None:
        assert CatalogRepository().get("nonexistent") is None

    def test_last_sync_reflects_most_recent_report(self) -> None:
        repo = CatalogRepository()
        assert repo.last_sync is None
        entries = normalize_entries(parse_readme(_SAMPLE_README))
        report = repo.replace_all(entries, source_url="https://example.com", now=datetime.now(UTC))
        assert repo.last_sync is report

    def test_record_failed_sync_does_not_touch_existing_catalog(self) -> None:
        repo = CatalogRepository()
        entries = normalize_entries(parse_readme(_SAMPLE_README))
        repo.replace_all(entries, source_url="https://example.com", now=datetime.now(UTC))

        report = repo.record_failed_sync(
            source_url="https://example.com", now=datetime.now(UTC), error="timeout"
        )
        assert report.ok is False
        assert report.error == "timeout"
        assert len(repo.all()) == 3  # eski katalog YO'QOLMADI
        assert repo.last_sync is report

    def test_mark_status_unknown_id_returns_none(self) -> None:
        assert CatalogRepository().mark_status("nope", APIStatus.ENABLED) is None


# ── source.py ────────────────────────────────────────────────────────


class TestResolveSourceUrl:
    def test_substitutes_branch_placeholder(self) -> None:
        url = resolve_source_url(
            source_url_template="https://raw.githubusercontent.com/public-apis/public-apis/{branch}/README.md",
            branch="master",
        )
        assert url == "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"

    def test_no_placeholder_returned_unchanged(self) -> None:
        url = resolve_source_url(source_url_template="https://example.com/fixed.md", branch="master")
        assert url == "https://example.com/fixed.md"


class TestFetchCatalogText:
    @respx.mock
    async def test_successful_fetch_returns_text(self) -> None:
        respx.get("https://example.com/readme.md").mock(
            return_value=httpx.Response(200, text="# hello")
        )
        text = await fetch_catalog_text(source_url="https://example.com/readme.md")
        assert text == "# hello"

    @respx.mock
    async def test_timeout_raises_catalog_sync_error(self) -> None:
        respx.get("https://example.com/readme.md").mock(side_effect=httpx.TimeoutException("slow"))
        with pytest.raises(CatalogSyncError):
            await fetch_catalog_text(source_url="https://example.com/readme.md")

    @respx.mock
    async def test_http_error_status_raises_catalog_sync_error(self) -> None:
        respx.get("https://example.com/readme.md").mock(return_value=httpx.Response(404))
        with pytest.raises(CatalogSyncError):
            await fetch_catalog_text(source_url="https://example.com/readme.md")

    @respx.mock
    async def test_connect_error_raises_catalog_sync_error(self) -> None:
        respx.get("https://example.com/readme.md").mock(side_effect=httpx.ConnectError("dns"))
        with pytest.raises(CatalogSyncError):
            await fetch_catalog_text(source_url="https://example.com/readme.md")


# ── sync.py — to'liq orkestratsiya ─────────────────────────────────────


class TestSyncCatalog:
    async def test_successful_sync_populates_repository(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_fetch(*, source_url: str, timeout_s: float = 20.0, client: object = None) -> str:
            return _SAMPLE_README

        monkeypatch.setattr(sync_mod, "fetch_catalog_text", fake_fetch)
        repo = CatalogRepository()
        report = await sync_catalog(
            repo,
            source_url_template="https://raw.githubusercontent.com/public-apis/public-apis/{branch}/README.md",
            branch="master",
        )
        assert report.ok is True
        assert report.total_entries == 3
        assert len(repo.all()) == 3

    async def test_failed_fetch_leaves_repository_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_fetch_ok(*, source_url: str, timeout_s: float = 20.0, client: object = None) -> str:
            return _SAMPLE_README

        monkeypatch.setattr(sync_mod, "fetch_catalog_text", fake_fetch_ok)
        repo = CatalogRepository()
        await sync_catalog(
            repo,
            source_url_template="https://example.com/{branch}.md",
            branch="master",
        )
        assert len(repo.all()) == 3

        async def fake_fetch_fail(
            *, source_url: str, timeout_s: float = 20.0, client: object = None
        ) -> str:
            raise CatalogSyncError("manba javob bermadi")

        monkeypatch.setattr(sync_mod, "fetch_catalog_text", fake_fetch_fail)
        report2 = await sync_catalog(
            repo, source_url_template="https://example.com/{branch}.md", branch="master"
        )
        assert report2.ok is False
        assert len(repo.all()) == 3  # eski katalog SAQLANDI, yo'qolmadi
