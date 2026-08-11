"""TelegramNotifier — haqiqiy Telegram Bot API orqali yuborish (V-17).

Ilgari `Notifier`ning yagona implementatsiyasi `StubNotifier` edi —
xabarlar hech qayerga yuborilmasdi, faqat xotirada saqlanardi
(gap-analysis #3, #14). Bu klass `https://api.telegram.org/bot<token>/...`
ga haqiqiy HTTP so'rov yuboradi.

Xavfsizlik:
    - Token hech qachon log qilinmaydi (URL'da bo'lsa ham, log yozuvida yo'q)
    - Faqat egaga (`owner_chat_id`) yuboriladi — boshqa hech kimga emas

Bog'liq qarorlar:
    V-17 — Telegram = asosiy boshqaruv paneli
    V-32 — approval so'rovlari inline tugmalar bilan
"""

from __future__ import annotations

import httpx
import structlog

from zet.telegram.keyboards import InlineKeyboard
from zet.telegram.notifier import Notification, NotificationType, Notifier

log = structlog.get_logger(__name__)

_API_BASE = "https://api.telegram.org"
_DEFAULT_TIMEOUT_S = 15.0


class TelegramNotifierError(Exception):
    """Telegram API xatosi."""


def _to_reply_markup(keyboard: InlineKeyboard) -> dict[str, object]:
    """`InlineKeyboard`ni Telegram Bot API formatiga o'giradi."""
    return {
        "inline_keyboard": [
            [{"text": btn.text, "callback_data": btn.callback_data} for btn in row]
            for row in keyboard.rows
        ]
    }


class TelegramNotifier(Notifier):
    """Telegram Bot API orqali egaga xabar yuboradi.

    Faqat chiqish (outbound) kanali — kiruvchi xabarlarni qabul qilish
    (long-polling/webhook) alohida vazifa (`telegram/bot.py`).
    """

    def __init__(
        self,
        *,
        token: str,
        owner_chat_id: int,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._token = token
        self._owner_chat_id = owner_chat_id
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def is_configured(self) -> bool:
        """Token va chat_id berilganmi."""
        return bool(self._token) and self._owner_chat_id != 0

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=_API_BASE)
        return self._client

    async def aclose(self) -> None:
        """HTTP klientni yopish (agar biz yaratgan bo'lsak)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def send(self, notification: Notification) -> bool:
        """Bildirishnomani Telegram orqali yuboradi.

        Returns:
            True — muvaffaqiyatli yuborildi. False — konfiguratsiya yo'q
            yoki API xato qaytardi (istisno tashlamaydi — chaqiruvchi
            oqimi buzilmasligi kerak, faqat log qilinadi).
        """
        if not self.is_configured:
            log.warning("telegram_notifier.not_configured", type=notification.type.value)
            return False

        payload: dict[str, object] = {
            "chat_id": self._owner_chat_id,
            "text": _format_text(notification),
            "parse_mode": "HTML",
        }
        if notification.keyboard is not None:
            payload["reply_markup"] = _to_reply_markup(notification.keyboard)

        try:
            response = await self._get_client().post(
                f"/bot{self._token}/sendMessage",
                json=payload,
                timeout=self._timeout_s,
            )
        except httpx.TimeoutException:
            log.warning("telegram_notifier.timeout", type=notification.type.value)
            return False
        except httpx.HTTPError as exc:
            log.warning("telegram_notifier.http_error", error=str(exc))
            return False

        if response.status_code != 200:
            log.warning(
                "telegram_notifier.api_error",
                status=response.status_code,
                # javob matni token'ni o'z ichiga olmaydi — xavfsiz log
                body=response.text[:300],
            )
            return False

        log.info("telegram_notifier.sent", type=notification.type.value)
        return True


def _format_text(notification: Notification) -> str:
    """Bildirishnoma turiga qarab prefiks qo'shadi."""
    prefix = {
        NotificationType.MESSAGE: "",
        NotificationType.APPROVAL: "🔐 <b>Tasdiq kerak</b>\n\n",
        NotificationType.TASK_RESULT: "✅ <b>Natija</b>\n\n",
        NotificationType.AGENT_ALERT: "🤖 <b>Agent</b>\n\n",
        NotificationType.SYSTEM_ALERT: "⚠️ <b>Tizim</b>\n\n",
    }.get(notification.type, "")
    return f"{prefix}{notification.text}"


__all__ = ["TelegramNotifier", "TelegramNotifierError"]
