"""Mijoz do'kon boti uchun Telegram long-polling (Z51, #42).

`telegram/polling.py`dagi `TelegramPoller`ning tor nusxasi:
    - Faqat matnli xabarlarni qabul qiladi (ovoz/rasm/callback —
      shop bot uchun kerak emas, MVP doirasidan tashqarida).
    - `ZetBot`ning owner-cheklovidan farqli o'laroq HAR KIMGA javob
      yuboradi — `ShopBot.process_message` hech qachon `None`
      qaytarmaydi (har doim matn bilan javob beradi).

Ikkalasi bitta modulga birlashtirilmadi: mantiqan mustaqil ikki bot
(owner boshqaruv paneli va mijoz savdo boti) — birlashtirish ularni
kelajakda chalkashtirib yuborishi mumkin edi.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from zet.telegram.shop_bot import ShopBot

log = structlog.get_logger(__name__)

_API_BASE = "https://api.telegram.org"
_LONG_POLL_TIMEOUT_S = 30
_HTTP_TIMEOUT_S = 60.0


class ShopBotPoller:
    """Mijoz boti uchun long-polling loopi (`TelegramPoller` bilan bir xil naqsh)."""

    def __init__(
        self,
        *,
        token: str,
        bot: ShopBot,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._bot = bot
        self._client = client
        self._owns_client = client is None
        self._offset: int | None = None
        self._stop_event = asyncio.Event()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=_API_BASE, timeout=_HTTP_TIMEOUT_S)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def stop(self) -> None:
        """Loopni keyingi iteratsiyada to'xtatish."""
        self._stop_event.set()

    async def run_forever(self) -> None:
        """Long-polling loopi — `stop()` chaqirilmaguncha ishlaydi."""
        log.info("shop_polling.started", timeout=_LONG_POLL_TIMEOUT_S)
        while not self._stop_event.is_set():
            try:
                updates = await self._get_updates()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("shop_polling.get_updates_error")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=5)
                continue

            for update in updates:
                if self._stop_event.is_set():
                    break
                try:
                    await self._process_update(update)
                except Exception:
                    log.exception("shop_polling.process_error", update_id=update.get("update_id"))
        log.info("shop_polling.stopped")

    async def _get_updates(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "timeout": _LONG_POLL_TIMEOUT_S,
            "allowed_updates": ["message"],
        }
        if self._offset is not None:
            params["offset"] = self._offset

        response = await self._get_client().get(f"/bot{self._token}/getUpdates", params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            log.warning("shop_polling.api_not_ok", description=data.get("description"))
            return []

        updates: list[dict[str, Any]] = data.get("result") or []
        if updates:
            self._offset = max(u["update_id"] for u in updates) + 1
        return updates

    async def _process_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if message is None:
            return  # callback/edited_message va h.k. — shop bot e'tibor bermaydi

        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = user.get("id")
        text: str | None = message.get("text") or message.get("caption")
        if chat_id is None or user_id is None:
            return

        reply = await self._bot.process_message(
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            username=user.get("username") or "",
            display_name=user.get("first_name") or "",
        )
        with contextlib.suppress(httpx.HTTPError):
            await self._get_client().post(
                f"/bot{self._token}/sendMessage",
                json={"chat_id": chat_id, "text": reply},
            )


__all__ = ["ShopBotPoller"]
