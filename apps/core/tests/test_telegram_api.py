"""Bo'lim 5 — Telegram API va CLI testlari.

Tekshiriladi:
    - POST /api/v1/telegram/message — xabar qayta ishlash
    - GET /api/v1/telegram/status — bot holati
    - z telegram status — CLI bot holati
    - z telegram test — CLI bot testi
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zet.api.app import create_app
from zet.api.deps import get_telegram_bot
from zet.cli import app as cli_app
from zet.telegram.bot import ZetBot
from zet.voice.stt import StubSTT

runner = CliRunner()


# ── API testlari ─────────────────────────────────────────────────


@pytest.fixture()
def test_bot() -> ZetBot:
    return ZetBot(
        owner_ids={123, 456},
        stt=StubSTT(default_text="Test ovoz"),
    )


@pytest.fixture()
def api_client(test_bot: ZetBot) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_telegram_bot] = lambda: test_bot
    return TestClient(app, raise_server_exceptions=False)


class TestTelegramAPI:
    def test_message_text_owner(self, api_client: TestClient) -> None:
        """Owner matnli xabar yuboradi — muvaffaqiyatli."""
        resp = api_client.post(
            "/api/v1/telegram/message",
            json={"user_id": 123, "chat_id": 123, "text": "Salom!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert data["text"] is not None
        assert "Qabul qilindi" in data["text"]

    def test_message_text_non_owner(self, api_client: TestClient) -> None:
        """Notanish foydalanuvchi — ruxsat rad etiladi."""
        resp = api_client.post(
            "/api/v1/telegram/message",
            json={"user_id": 999, "chat_id": 999, "text": "Hack!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert not data["success"]
        assert data["text"] is None

    def test_message_command(self, api_client: TestClient) -> None:
        """Owner /start buyrug'i."""
        resp = api_client.post(
            "/api/v1/telegram/message",
            json={"user_id": 456, "chat_id": 456, "text": "/start"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert "ZET" in data["text"]

    def test_message_callback(self, api_client: TestClient) -> None:
        """Owner callback (inline tugma)."""
        resp = api_client.post(
            "/api/v1/telegram/message",
            json={
                "user_id": 123,
                "chat_id": 123,
                "callback_data": "approve:run_test",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        assert "tasdiqlandi" in data["text"]

    def test_bot_status(self, api_client: TestClient) -> None:
        """Bot holati."""
        resp = api_client.get("/api/v1/telegram/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_count"] == 2
        assert not data["running"]
        assert not data["has_token"]

    def test_message_empty_text(self, api_client: TestClient) -> None:
        """Bo'sh matn."""
        resp = api_client.post(
            "/api/v1/telegram/message",
            json={"user_id": 123, "chat_id": 123, "text": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"]
        # Bo'sh matn ham qayta ishlanadi

    def test_message_html_escape(self, api_client: TestClient) -> None:
        """HTML maxsus belgilar almashtiriladi."""
        resp = api_client.post(
            "/api/v1/telegram/message",
            json={
                "user_id": 123,
                "chat_id": 123,
                "text": "<script>alert('xss')</script>",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "<script>" not in data["text"]


# ── CLI testlari ─────────────────────────────────────────────────


class TestTelegramCLI:
    def test_status(self) -> None:
        """z telegram status."""
        result = runner.invoke(cli_app, ["telegram", "status"])
        assert result.exit_code == 0
        assert "Telegram Bot" in result.output

    def test_test_message(self) -> None:
        """z telegram test — default xabar."""
        result = runner.invoke(cli_app, ["telegram", "test"])
        assert result.exit_code == 0
        assert "Bot javobi" in result.output

    def test_test_custom_message(self) -> None:
        """z telegram test — maxsus xabar."""
        result = runner.invoke(cli_app, ["telegram", "test", "Havo qanday?"])
        assert result.exit_code == 0
        assert "Bot javobi" in result.output
        assert "Havo qanday?" in result.output

    def test_test_command(self) -> None:
        """z telegram test — /start buyrug'i."""
        result = runner.invoke(cli_app, ["telegram", "test", "/start"])
        assert result.exit_code == 0
        assert "ZET" in result.output
