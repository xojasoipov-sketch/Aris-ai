"""Telegram Bot API long-polling (V-17, ADR-0007).

Ilgari `ZetBot.start()` faqat holat o'zgartirardi — hech qanday
kiruvchi xabar qabul qilmasdi (docstring: "haqiqiy polling emas").
Ega Telegramga xabar yozsa, ZET javob bermas edi.

Bu modul aiogram'siz sodda `getUpdates` long-polling ilovasi — ZetBot
bilan bir xil arxitektura, faqat kiruvchi tomonini yopadi.

Kirish oqimi:
    getUpdates → Update → ZetBot.process_message() → TelegramOutput
    → sendMessage / sendAudio (voice_data mavjud bo'lsa)

Xavfsizlik:
    - Faqat `ZetBot.owner_middleware` tomonidan ruxsat berilgan
      user'lar javob oladi (ichkarida tekshiriladi)
    - Token log'da paydo bo'lmaydi

Bog'liq qarorlar:
    V-17 — Telegram = asosiy boshqaruv paneli
    ADR-0007 — long polling (webhook shart emas, ommaviy IP shart emas)
    R-04 — bot token xavfsizligi
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from zet.telegram.bot import ZetBot
    from zet.telegram.handlers import TelegramOutput

log = structlog.get_logger(__name__)

_API_BASE = "https://api.telegram.org"
_LONG_POLL_TIMEOUT_S = 30
"""Telegram tomonidan yangi update kutilayotgan vaqt (server-side hold)."""

_HTTP_TIMEOUT_S = 60.0
"""Klient tomonidagi umumiy timeout (long-poll + tarmoq marja)."""


class TelegramPoller:
    """Telegram Bot API long-polling loopi.

    `run_forever()` — asyncio task sifatida ishga tushiriladi
    (`ZetBot.start()` orqali). `stop()` chaqirilganda navbatdagi
    iteratsiyada tugaydi.
    """

    def __init__(
        self,
        *,
        token: str,
        bot: ZetBot,
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
        log.info("polling.started", timeout=_LONG_POLL_TIMEOUT_S)
        while not self._stop_event.is_set():
            try:
                updates = await self._get_updates()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("polling.get_updates_error")
                # Xato tarmoqni to'ldirmasin — qisqa kutamiz
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop_event.wait(), timeout=5)
                continue

            for update in updates:
                if self._stop_event.is_set():
                    break
                try:
                    await self._process_update(update)
                except Exception:
                    # Bitta xabar xatosi butun loopni to'xtatmasin
                    log.exception("polling.process_error", update_id=update.get("update_id"))
        log.info("polling.stopped")

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Telegramdan yangi update'larni oladi (long-poll)."""
        params: dict[str, Any] = {
            "timeout": _LONG_POLL_TIMEOUT_S,
            "allowed_updates": ["message", "callback_query"],
        }
        if self._offset is not None:
            params["offset"] = self._offset

        response = await self._get_client().get(f"/bot{self._token}/getUpdates", params=params)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            log.warning("polling.api_not_ok", description=data.get("description"))
            return []

        updates: list[dict[str, Any]] = data.get("result") or []
        if updates:
            # Keyingi so'rov shu ID'dan boshlab yangilarini oladi
            self._offset = max(u["update_id"] for u in updates) + 1
        return updates

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Bitta update'ni ZetBot'ga uzatadi va javobni yuboradi."""
        message = update.get("message")
        callback = update.get("callback_query")

        if callback is not None:
            await self._handle_callback(callback)
            return
        if message is not None:
            await self._handle_message(message)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = user.get("id")
        message_id = message.get("message_id")
        if chat_id is None or user_id is None:
            return

        text: str | None = message.get("text") or message.get("caption")
        voice_bytes: bytes | None = None
        photo_bytes: bytes | None = None

        # Voice — Telegram OGG/Opus file_id → download
        voice = message.get("voice") or message.get("audio")
        if voice and voice.get("file_id"):
            voice_bytes = await self._download_file(voice["file_id"])

        # Photo — eng katta variantni olamiz
        photos = message.get("photo") or []
        if photos:
            biggest = max(photos, key=lambda p: p.get("file_size", 0))
            photo_bytes = await self._download_file(biggest["file_id"])

        output = await self._bot.process_message(
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            voice_data=voice_bytes,
            photo_data=photo_bytes,
            message_id=message_id,
        )
        if output is None:
            # Owner allowlist rad etdi — jimgina o'tkazamiz
            return
        await self._send_reply(chat_id, output)

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        user = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        user_id = user.get("id")
        chat_id = chat.get("id")
        callback_data = callback.get("data")
        if user_id is None or chat_id is None or callback_data is None:
            return

        output = await self._bot.process_message(
            user_id=user_id,
            chat_id=chat_id,
            callback_data=callback_data,
        )
        # Tugma bosgan foydalanuvchiga darhol javob (loading holatini tugatadi)
        with contextlib.suppress(httpx.HTTPError):
            await self._get_client().post(
                f"/bot{self._token}/answerCallbackQuery",
                json={"callback_query_id": callback["id"]},
            )
        if output is not None:
            await self._send_reply(chat_id, output)

    async def _download_file(self, file_id: str) -> bytes | None:
        """`getFile` + fayl yuklab olish — voice/photo baytlariga."""
        try:
            info = await self._get_client().post(
                f"/bot{self._token}/getFile", json={"file_id": file_id}
            )
            info.raise_for_status()
            info_data = info.json()
            if not info_data.get("ok"):
                log.warning("polling.get_file_failed", desc=info_data.get("description"))
                return None
            file_path = info_data["result"]["file_path"]

            file_resp = await self._get_client().get(f"/file/bot{self._token}/{file_path}")
            file_resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("polling.download_failed", error=str(exc))
            return None
        return file_resp.content

    async def _send_reply(self, chat_id: int, output: TelegramOutput) -> None:
        """`TelegramOutput`ni foydalanuvchiga yuboradi (matn + ixtiyoriy ovoz).

        `voice_data` mavjud bo'lsa `sendVoice` bilan urinadi; foydalanuvchi
        voice messages'ni bloklagan bo'lsa (VOICE_MESSAGES_FORBIDDEN) —
        `sendAudio` orqali audio fayl sifatida yuboradi. Ikkalasi ham
        rad etilsa — faqat matn qoladi.
        """
        # Matnni har doim yuboramiz (audio bo'lsa unga qo'shimcha)
        text_payload: dict[str, Any] = {"chat_id": chat_id, "text": output.text}
        if output.parse_mode:
            text_payload["parse_mode"] = output.parse_mode
        with contextlib.suppress(httpx.HTTPError):
            await self._get_client().post(f"/bot{self._token}/sendMessage", json=text_payload)

        if output.voice_data is None:
            return

        # Voice: avval sendVoice, kerak bo'lsa sendAudio'ga tushish
        sent = await self._try_send_voice(chat_id, output.voice_data)
        if not sent:
            await self._try_send_audio(chat_id, output.voice_data)

    async def _try_send_voice(self, chat_id: int, audio: bytes) -> bool:
        try:
            r = await self._get_client().post(
                f"/bot{self._token}/sendVoice",
                data={"chat_id": chat_id},
                files={"voice": ("zet.ogg", audio, "audio/mpeg")},
            )
        except httpx.HTTPError as exc:
            log.warning("polling.send_voice_failed", error=str(exc))
            return False
        if r.status_code == 200:
            return True
        log.info("polling.send_voice_rejected", status=r.status_code, body=r.text[:200])
        return False

    async def _try_send_audio(self, chat_id: int, audio: bytes) -> None:
        try:
            r = await self._get_client().post(
                f"/bot{self._token}/sendAudio",
                data={"chat_id": chat_id, "title": "ZET", "performer": "ZET"},
                files={"audio": ("zet.mp3", audio, "audio/mpeg")},
            )
        except httpx.HTTPError as exc:
            log.warning("polling.send_audio_failed", error=str(exc))
            return
        if r.status_code != 200:
            log.warning("polling.send_audio_rejected", status=r.status_code, body=r.text[:200])


__all__ = ["TelegramPoller"]
