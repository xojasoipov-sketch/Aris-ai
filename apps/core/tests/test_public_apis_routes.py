"""public-apis operator/admin REST endpoint testlari (JB-18, Bo'lim 17)
— `test_system_routes.py` bilan bir xil naqsh: DB shart emas
(`CatalogRepository`/`ProviderHealthTracker` jarayon-xotirasida),
dependency override orqali HAR bir test o'z, izolyatsiyalangan
nusxasi bilan ishlaydi (lru_cache singleton testlar orasida sizib
chiqmasin).
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import (
    get_config,
    get_public_apis_catalog_repository,
    get_public_apis_health_tracker,
)
from zet.config import Settings
from zet.integrations.public_apis.catalog.models import (
    APIStatus,
    AuthType,
    PricingStatus,
    PublicAPIEntry,
    entry_id,
)
from zet.integrations.public_apis.catalog.repository import CatalogRepository
from zet.integrations.public_apis.health.scoring import ProviderHealthTracker


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "telegram_bot_token": None,
        "elevenlabs_api_key": None,
        "azure_speech_key": None,
        "azure_speech_region": "",
        "google_api_key": None,
        "mistral_api_key": None,
        "openrouter_api_key": None,
        "cohere_api_key": None,
        "anthropic_api_key": None,
        "github_token": None,
        "web_search_api_key": None,
        "youtube_api_key": None,
        "instagram_access_token": None,
        "instagram_business_account_id": "",
        "hikvision_password": None,
        "hikvision_host": "",
        "hikvision_username": "",
    }
    base |= overrides
    return Settings(**base)  # type: ignore[arg-type]


def _entry(
    name: str, *, category: str = "Geocoding", status: APIStatus = APIStatus.DISCOVERED
) -> PublicAPIEntry:
    return PublicAPIEntry(
        id=entry_id(category=category, name=name),
        name=name,
        description=f"{name} tavsifi",
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


def _client(
    settings: Settings,
    *,
    repository: CatalogRepository | None = None,
    tracker: ProviderHealthTracker | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_config] = lambda: settings
    app.dependency_overrides[get_public_apis_catalog_repository] = lambda: (
        repository if repository is not None else CatalogRepository()
    )
    app.dependency_overrides[get_public_apis_health_tracker] = lambda: (
        tracker if tracker is not None else ProviderHealthTracker()
    )
    return TestClient(app)


class TestSearchEndpoint:
    def test_empty_catalog_returns_no_candidates(self) -> None:
        response = _client(_settings()).get("/api/v1/public-apis/search?q=currency")
        assert response.status_code == 200
        body = response.json()
        assert body["total_candidates"] == 0
        assert body["candidates"] == []

    def test_returns_ranked_candidates_for_synced_catalog(self) -> None:
        repo = CatalogRepository()
        repo.replace_all(
            [_entry("Geocodio"), _entry("Weatherstack", category="Weather")],
            source_url="https://example.com",
            now=dt.datetime.now(dt.UTC),
        )
        response = _client(_settings(), repository=repo).get("/api/v1/public-apis/search?q=geocoding")
        assert response.status_code == 200
        body = response.json()
        assert body["total_candidates"] == 1
        assert body["candidates"][0]["name"] == "Geocodio"

    def test_missing_query_param_is_422(self) -> None:
        response = _client(_settings()).get("/api/v1/public-apis/search")
        assert response.status_code == 422

    def test_limit_out_of_range_is_422(self) -> None:
        response = _client(_settings()).get("/api/v1/public-apis/search?q=x&limit=999")
        assert response.status_code == 422


class TestRefreshEndpoint:
    def test_refresh_failure_does_not_500_returns_ok_false(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Tarmoqqa chiqib bo'lmasa (masalan testda haqiqiy manba yo'q) —
        endpoint 500 emas, tushunarli `ok=False` hisobot qaytaradi."""
        from zet.api.routes import public_apis as routes_mod

        async def fake_sync(repository, *, source_url_template, branch):  # type: ignore[no-untyped-def]
            return repository.record_failed_sync(
                source_url="https://example.com",
                now=dt.datetime.now(dt.UTC),
                error="test: manba mavjud emas",
            )

        monkeypatch.setattr(routes_mod, "sync_catalog", fake_sync)
        response = _client(_settings()).post("/api/v1/public-apis/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "manba mavjud emas" in body["error"]

    def test_successful_refresh_reports_counts(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from zet.api.routes import public_apis as routes_mod

        async def fake_sync(repository, *, source_url_template, branch):  # type: ignore[no-untyped-def]
            return repository.replace_all(
                [_entry("Geocodio")],
                source_url="https://example.com",
                now=dt.datetime.now(dt.UTC),
            )

        monkeypatch.setattr(routes_mod, "sync_catalog", fake_sync)
        response = _client(_settings()).post("/api/v1/public-apis/refresh")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["added"] == 1
        assert body["total_entries"] == 1


class TestStatsEndpoint:
    def test_never_synced_reports_honest_empty_state(self) -> None:
        response = _client(_settings()).get("/api/v1/public-apis/stats")
        assert response.status_code == 200
        body = response.json()
        assert body["total_entries"] == 0
        assert body["last_sync_at"] is None
        assert body["last_sync_ok"] is None

    def test_synced_catalog_reports_real_counts(self) -> None:
        repo = CatalogRepository()
        repo.replace_all(
            [_entry("A"), _entry("B", status=APIStatus.ENABLED)],
            source_url="https://example.com",
            now=dt.datetime.now(dt.UTC),
        )
        response = _client(_settings(), repository=repo).get("/api/v1/public-apis/stats")
        body = response.json()
        assert body["total_entries"] == 2
        assert body["enabled"] == 1
        assert body["last_sync_ok"] is True


class TestHealthEndpoint:
    def test_no_calls_yet_returns_empty_list_not_fake_100_percent(self) -> None:
        """Hech qanday adapter chaqirilmagan — bo'sh ro'yxat, "sog'lom"
        deb SOXTA da'vo QILINMAYDI (Bo'lim 13)."""
        response = _client(_settings()).get("/api/v1/public-apis/health")
        assert response.status_code == 200
        assert response.json() == []

    def test_recorded_calls_are_reflected(self) -> None:
        tracker = ProviderHealthTracker()
        tracker.record_success("test-provider", latency_ms=120.0, now=dt.datetime.now(dt.UTC))
        tracker.record_failure(
            "test-provider", latency_ms=50.0, now=dt.datetime.now(dt.UTC), rate_limited=True
        )
        response = _client(_settings(), tracker=tracker).get("/api/v1/public-apis/health")
        body = response.json()
        assert len(body) == 1
        assert body[0]["provider"] == "test-provider"
        assert body[0]["total_calls"] == 2
        assert body[0]["rate_limited"] == 1
        assert body[0]["success_rate"] == 0.5


class TestRoutesRequireNoDatabaseAccess:
    """public-apis endpoint'lari DB'ga umuman tegmasligini kafolatlaydi
    — hammasi jarayon-xotirasidagi `CatalogRepository`/
    `ProviderHealthTracker`dan o'qiydi (Bo'lim 3 dizayn qarori)."""

    def test_all_four_endpoints_respond_without_db_dependency_override(self) -> None:
        client = _client(_settings())
        assert client.get("/api/v1/public-apis/stats").status_code == 200
        assert client.get("/api/v1/public-apis/health").status_code == 200
        assert client.get("/api/v1/public-apis/search?q=x").status_code == 200
