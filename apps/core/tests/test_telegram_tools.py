"""Telegram Bot API tool testlari (respx bilan real HTTP mock).

`YouTubeSearchTool` va `WebSearchTool` bilan bir xil naqsh:
    1. Token yo'q → stub rejim (barqaror, tarmoqqa chiqmaydi)
    2. Muvaffaqiyatli javob → to'g'ri parse
    3. Xatolar (403 admin emas, timeout) → ToolError
    4. WRITE tool idempotent emas — approval kerak
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.builtin.telegram_tools import (
    TelegramChannelPostTool,
    TelegramChannelStatsTool,
)

_TOKEN = "123456:FAKE_TOKEN_FOR_TESTS"
_BASE = f"https://api.telegram.org/bot{_TOKEN}"


# ── Channel stats ──────────────────────────────────────────────────


class TestTelegramChannelStatsTool:
    async def test_stub_when_no_token(self) -> None:
        tool = TelegramChannelStatsTool()
        assert tool.is_real is False

        result = await tool.execute({"chat_id": "@testchannel"})
        assert result.success is True
        assert result.output["member_count"] == 0
        assert "stub" in result.output["source"]
        assert result.output["chat_id"] == "@testchannel"

    def test_is_real_with_token(self) -> None:
        assert TelegramChannelStatsTool(token=_TOKEN).is_real is True

    def test_permission_and_trust(self) -> None:
        tool = TelegramChannelStatsTool()
        assert tool.permission_level == PermissionLevel.READ
        assert tool.output_trust_level == TrustLevel.UNTRUSTED

    @respx.mock
    async def test_real_channel_stats(self) -> None:
        respx.post(f"{_BASE}/getChat").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "id": -1001234567890,
                        "type": "channel",
                        "title": "ZET Test Kanal",
                        "username": "zettest",
                        "description": "Sinov kanali",
                        "invite_link": "https://t.me/+abc",
                    },
                },
            )
        )
        respx.post(f"{_BASE}/getChatMemberCount").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": 42})
        )

        tool = TelegramChannelStatsTool(token=_TOKEN)
        result = await tool.execute({"chat_id": "@zettest"})

        assert result.success is True
        out = result.output
        assert out["chat_id"] == -1001234567890
        assert out["type"] == "channel"
        assert out["title"] == "ZET Test Kanal"
        assert out["username"] == "zettest"
        assert out["member_count"] == 42
        assert out["invite_link"] == "https://t.me/+abc"

    @respx.mock
    async def test_not_admin_returns_error(self) -> None:
        respx.post(f"{_BASE}/getChat").mock(
            return_value=httpx.Response(
                403,
                json={
                    "ok": False,
                    "error_code": 403,
                    "description": "Forbidden: bot is not a member of the channel chat",
                },
            )
        )
        tool = TelegramChannelStatsTool(token=_TOKEN)
        result = await tool.execute({"chat_id": "@private"})
        assert result.success is False
        assert "forbidden" in (result.error or "").lower()

    @respx.mock
    async def test_network_timeout(self) -> None:
        respx.post(f"{_BASE}/getChat").mock(side_effect=httpx.TimeoutException("timeout"))
        tool = TelegramChannelStatsTool(token=_TOKEN)
        result = await tool.execute({"chat_id": "@x"})
        assert result.success is False
        assert "timeout" in (result.error or "").lower()

    @respx.mock
    async def test_non_json_response(self) -> None:
        respx.post(f"{_BASE}/getChat").mock(
            return_value=httpx.Response(502, content=b"<html>Bad Gateway</html>")
        )
        tool = TelegramChannelStatsTool(token=_TOKEN)
        result = await tool.execute({"chat_id": "@x"})
        assert result.success is False
        assert "nojson" in (result.error or "").lower() or "502" in (result.error or "")


# ── Channel post (WRITE) ───────────────────────────────────────────


class TestTelegramChannelPostTool:
    async def test_stub_when_no_token(self) -> None:
        tool = TelegramChannelPostTool()
        assert tool.is_real is False

        result = await tool.execute({"chat_id": "@testchannel", "text": "Salom"})
        assert result.success is True
        assert result.output["posted"] is False
        assert "stub" in result.output["source"]

    def test_permission_write(self) -> None:
        assert TelegramChannelPostTool().permission_level == PermissionLevel.WRITE

    def test_not_idempotent(self) -> None:
        """Kanalga xabar yuborish idempotent emas — dublikat bo'ladi."""
        assert TelegramChannelPostTool().idempotent is False

    @respx.mock
    async def test_real_post_success(self) -> None:
        route = respx.post(f"{_BASE}/sendMessage").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": 777,
                        "chat": {"id": -1001234567890, "type": "channel", "title": "Test"},
                        "date": 1700000000,
                        "text": "Salom",
                    },
                },
            )
        )
        tool = TelegramChannelPostTool(token=_TOKEN)
        result = await tool.execute(
            {"chat_id": "@zettest", "text": "<b>Salom</b>", "disable_notification": True}
        )

        assert result.success is True
        assert result.output["message_id"] == 777
        assert result.output["chat_id"] == -1001234567890
        assert result.output["posted"] is True

        # HTML parse_mode va disable_notification uzatildimi
        request = route.calls[0].request
        body = request.content.decode("utf-8")
        assert '"parse_mode":"HTML"' in body
        assert '"disable_notification":true' in body

    @respx.mock
    async def test_post_forbidden(self) -> None:
        """Bot administrator emas — 403."""
        respx.post(f"{_BASE}/sendMessage").mock(
            return_value=httpx.Response(
                403,
                json={
                    "ok": False,
                    "error_code": 403,
                    "description": "Forbidden: bot is not a member of the channel chat",
                },
            )
        )
        tool = TelegramChannelPostTool(token=_TOKEN)
        result = await tool.execute({"chat_id": "@x", "text": "salom"})
        assert result.success is False
        assert "forbidden" in (result.error or "").lower()

    @respx.mock
    async def test_network_error(self) -> None:
        respx.post(f"{_BASE}/sendMessage").mock(side_effect=httpx.ConnectError("dns"))
        tool = TelegramChannelPostTool(token=_TOKEN)
        result = await tool.execute({"chat_id": "@x", "text": "s"})
        assert result.success is False
        assert "tarmoq" in (result.error or "").lower() or "dns" in (result.error or "").lower()


# ── build_default_registry integratsiyasi ──────────────────────────


class TestDefaultRegistryWiring:
    """Deps → build_default_registry → Telegram tool'lar mavjud."""

    def test_telegram_tools_registered(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        names = set(registry.tool_names())
        assert "telegram.channel_stats" in names
        assert "telegram.channel_post" in names

    def test_telegram_tools_stub_without_token(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        assert registry.get("telegram.channel_stats").is_real is False  # type: ignore[attr-defined]
        assert registry.get("telegram.channel_post").is_real is False  # type: ignore[attr-defined]

    def test_telegram_tools_real_with_token(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(
            notes_dir=tmp_path,  # type: ignore[arg-type]
            telegram_bot_token=_TOKEN,
        )
        assert registry.get("telegram.channel_stats").is_real is True  # type: ignore[attr-defined]
        assert registry.get("telegram.channel_post").is_real is True  # type: ignore[attr-defined]


# ── SMM agent — telegram tool'lar allowlist'da ─────────────────────


class TestSmmAgentAllowlist:
    def test_smm_agent_has_telegram_tools(self) -> None:
        from zet.agents.builtin.smm import SMM_AGENT_SPEC

        assert "telegram.channel_stats" in SMM_AGENT_SPEC.tool_allowlist
        assert "telegram.channel_post" in SMM_AGENT_SPEC.tool_allowlist


# ── EvalRunner — telegram tool ruxsat darajalari to'g'ri ───────────


class TestEvalToolPermissions:
    def test_telegram_permissions_registered_in_eval(self) -> None:
        from zet.agents.eval import TOOL_PERMISSIONS

        assert TOOL_PERMISSIONS["telegram.channel_stats"] == PermissionLevel.READ
        assert TOOL_PERMISSIONS["telegram.channel_post"] == PermissionLevel.WRITE
