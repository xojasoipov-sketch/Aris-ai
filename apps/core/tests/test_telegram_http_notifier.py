"""TelegramNotifier testlari — respx bilan, haqiqiy tarmoqqa chiqmasdan.

gap-analysis #3/#14: ilgari Telegram Bot API'ga bironta HTTP so'rov yo'q edi.
"""

from __future__ import annotations

import httpx
import respx

from zet.telegram.http_notifier import TelegramNotifier
from zet.telegram.keyboards import ApprovalKeyboard
from zet.telegram.notifier import Notification, NotificationType

_TOKEN = "123456:FAKE-TOKEN-FOR-TESTS"
_CHAT_ID = 987654321
_API = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"


class TestIsConfigured:
    def test_configured_with_token_and_chat_id(self) -> None:
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)
        assert notifier.is_configured is True

    def test_not_configured_without_token(self) -> None:
        notifier = TelegramNotifier(token="", owner_chat_id=_CHAT_ID)
        assert notifier.is_configured is False

    def test_not_configured_without_chat_id(self) -> None:
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=0)
        assert notifier.is_configured is False


class TestSend:
    @respx.mock
    async def test_send_text_success(self) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        sent = await notifier.send_text("Salom, ega!")

        assert sent is True
        assert route.called
        body = route.calls[0].request.content
        assert b"Salom" in body

    @respx.mock
    async def test_send_includes_chat_id(self) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        await notifier.send_text("test")

        import json

        payload = json.loads(route.calls[0].request.content)
        assert payload["chat_id"] == _CHAT_ID

    @respx.mock
    async def test_send_alert_has_prefix(self) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        await notifier.send_alert("Diqqat kerak")

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "Tizim" in payload["text"]
        assert "Diqqat kerak" in payload["text"]

    @respx.mock
    async def test_send_approval_includes_keyboard(self) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        keyboard = ApprovalKeyboard.for_run("run-123")
        await notifier.send_approval("Tasdiqlaysizmi?", keyboard, run_id="run-123")

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "reply_markup" in payload
        buttons = payload["reply_markup"]["inline_keyboard"][0]
        assert any(b["callback_data"] == "approve:run-123" for b in buttons)

    async def test_send_unconfigured_returns_false(self) -> None:
        notifier = TelegramNotifier(token="", owner_chat_id=0)
        sent = await notifier.send_text("x")
        assert sent is False

    @respx.mock
    async def test_send_api_error_returns_false(self) -> None:
        respx.post(_API).mock(return_value=httpx.Response(401, json={"ok": False}))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        sent = await notifier.send_text("x")
        assert sent is False

    @respx.mock
    async def test_send_timeout_returns_false(self) -> None:
        respx.post(_API).mock(side_effect=httpx.ConnectTimeout("timeout"))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        sent = await notifier.send_text("x")
        assert sent is False

    @respx.mock
    async def test_send_network_error_returns_false(self) -> None:
        respx.post(_API).mock(side_effect=httpx.ConnectError("no route"))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        sent = await notifier.send_text("x")
        assert sent is False


class TestNotificationTypePrefixes:
    @respx.mock
    async def test_task_result_prefix(self) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)

        await notifier.send(Notification(type=NotificationType.TASK_RESULT, text="bajarildi"))

        import json

        payload = json.loads(route.calls[0].request.content)
        assert "Natija" in payload["text"]


class TestAclose:
    async def test_aclose_own_client(self) -> None:
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID)
        notifier._get_client()  # klientni yaratish
        await notifier.aclose()  # xato bermasligi kerak

    async def test_aclose_external_client_not_closed(self) -> None:
        client = httpx.AsyncClient()
        notifier = TelegramNotifier(token=_TOKEN, owner_chat_id=_CHAT_ID, client=client)
        await notifier.aclose()
        assert client.is_closed is False
        await client.aclose()
