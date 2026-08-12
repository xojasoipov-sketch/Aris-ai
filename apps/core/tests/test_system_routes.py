"""Tizim o'lchovlari va integratsiya holati testlari (Z46.1).

NEGA BU TESTLAR BOR.

Ikkala ma'lumot ham frontend'da QOTIRILGAN edi:

  · terminal sahifasi "CPU: 24% · RAM: 41% · GPU: 15%" deb yozardi —
    hech biri o'lchanmagan;
  · sozlamalar sahifasi "Telegram bot — Sozlangan" deb ko'rsatardi,
    hech qanday tekshiruvsiz.

Bu testlar javob HAQIQATAN o'lchanishini va SIR OCHILMASLIGINI
qulflaydi.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_config
from zet.config import Settings


def _client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_config] = lambda: settings
    return TestClient(app)


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


class TestSystemMetricsAreMeasured:
    """Sonlar o'lchanadi — qotirilgan emas."""

    def test_returns_plausible_values(self) -> None:
        response = _client(_settings()).get("/api/v1/system")

        assert response.status_code == 200
        body = response.json()
        assert 0.0 <= body["cpu_percent"] <= 100.0
        assert 0.0 < body["memory_percent"] <= 100.0
        assert body["memory_total_mb"] > 0
        assert body["memory_used_mb"] > 0

    def test_uptime_is_not_negative(self) -> None:
        body = _client(_settings()).get("/api/v1/system").json()

        assert body["uptime_seconds"] >= 0

    def test_gpu_is_absent(self) -> None:
        """O'lchab bo'lmaydigan narsa QAYTARILMAYDI.

        Terminal sahifasi "GPU: 15%" deb yozardi — serverda GPU
        umuman yo'q. Nol yoki taxminiy son yozish ham yolg'on."""
        body = _client(_settings()).get("/api/v1/system").json()

        assert "gpu" not in str(body).lower()


class TestIntegrationsReflectRealConfig:
    def test_missing_key_is_reported_unconfigured(self) -> None:
        body = _client(_settings()).get("/api/v1/integrations").json()

        telegram = next(i for i in body if i["key"] == "telegram")
        assert telegram["configured"] is False
        assert "stub" in telegram["detail"]

    def test_present_key_is_reported_configured(self) -> None:
        body = _client(_settings(telegram_bot_token="123:abc")).get("/api/v1/integrations").json()

        telegram = next(i for i in body if i["key"] == "telegram")
        assert telegram["configured"] is True

    def test_azure_needs_both_key_and_region(self) -> None:
        """Kalit yolg'iz yetarli emas — regionsiz endpoint qurilmaydi."""
        body = (
            _client(_settings(azure_speech_key="k", azure_speech_region=""))
            .get("/api/v1/integrations")
            .json()
        )

        azure = next(i for i in body if i["key"] == "azure_speech")
        assert azure["configured"] is False
        assert "region" in azure["detail"]

    def test_azure_configured_with_region(self) -> None:
        body = (
            _client(_settings(azure_speech_key="k", azure_speech_region="westeurope"))
            .get("/api/v1/integrations")
            .json()
        )

        azure = next(i for i in body if i["key"] == "azure_speech")
        assert azure["configured"] is True

    def test_instagram_needs_business_account_id(self) -> None:
        body = _client(_settings(instagram_access_token="t")).get("/api/v1/integrations").json()

        instagram = next(i for i in body if i["key"] == "instagram")
        assert instagram["configured"] is False

    def test_secret_values_are_never_returned(self) -> None:
        """Javobda kalitning O'ZI bo'lmasligi shart."""
        secret = "super-maxfiy-kalit-12345"
        body = _client(_settings(telegram_bot_token=secret)).get("/api/v1/integrations").text

        assert secret not in body
