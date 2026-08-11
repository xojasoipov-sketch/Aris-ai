"""ZetBot — aiogram 3 Telegram bot (V-17, ADR-0007).

Asosiy xususiyatlar:
    1. Long polling (webhook emas — ommaviy IP kerak emas)
    2. Owner allowlist (A-05, R-04)
    3. Text / voice / image / file kirish (V-17)
    4. Inline approval tugmalari (V-32)
    5. Push bildirishnomalar (alerts, task results)

Arxitektura:
    ZetBot
    ├── OwnerMiddleware — faqat egasiga ruxsat
    ├── MessageHandler — xabarlarni qayta ishlash
    ├── Notifier — push bildirishnomalar
    └── STTProvider — ovozdan matn

Bo'lim 5 lean: aiogram ixtiyoriy dependency. Test da stub ishlaydi.
Haqiqiy aiogram integratsiyasi faqat prod da.

Bog'liq qarorlar:
    V-17 — Telegram = asosiy boshqaruv paneli
    ADR-0007 — long polling
    R-04 — bot token xavfsizligi
"""

from __future__ import annotations

import structlog

from zet.telegram.handlers import (
    HandlerContext,
    InputType,
    MessageHandler,
    TelegramInput,
    TelegramOutput,
)
from zet.telegram.middleware import OwnerMiddleware
from zet.telegram.notifier import Notifier, StubNotifier
from zet.voice.stt import STTProvider, StubSTT

log = structlog.get_logger(__name__)


class ZetBot:
    """ZET Telegram bot — asosiy boshqaruv paneli (V-17).

    Ikki rejimda ishlaydi:
        1. Stub rejim (test/dev) — aiogram yuklanmaydi
        2. Live rejim (prod) — aiogram 3 bilan haqiqiy bot

    Bo'lim 5 lean: faqat stub rejim.
    """

    def __init__(
        self,
        *,
        token: str = "",
        owner_ids: set[int] | None = None,
        stt: STTProvider | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        """
        Args:
            token: Telegram bot token (prod uchun kerak)
            owner_ids: ruxsat etilgan Telegram user_id lar
            stt: STT provayder (None = StubSTT)
            notifier: bildirishnoma yuboruvchi (None = StubNotifier)
        """
        self._token = token
        self._owner_middleware = OwnerMiddleware(owner_ids or set())
        self._stt = stt or StubSTT()
        self._notifier = notifier or StubNotifier()
        self._handler = MessageHandler(HandlerContext(stt=self._stt))
        self._running = False

        log.info(
            "bot.init",
            owner_count=len(self._owner_middleware.owner_ids),
            has_token=bool(token),
        )

    @property
    def owner_middleware(self) -> OwnerMiddleware:
        """Owner middleware."""
        return self._owner_middleware

    @property
    def handler(self) -> MessageHandler:
        """Xabar handleri."""
        return self._handler

    @property
    def notifier(self) -> Notifier:
        """Bildirishnoma yuboruvchi."""
        return self._notifier

    @property
    def is_running(self) -> bool:
        """Bot ishlamoqdami."""
        return self._running

    async def process_message(
        self,
        *,
        user_id: int,
        chat_id: int,
        text: str | None = None,
        voice_data: bytes | None = None,
        photo_data: bytes | None = None,
        document_data: bytes | None = None,
        file_name: str | None = None,
        callback_data: str | None = None,
        message_id: int | None = None,
    ) -> TelegramOutput | None:
        """Xabarni qayta ishlash (owner tekshiruvi bilan).

        Args:
            user_id: Telegram user ID
            chat_id: Telegram chat ID
            text: matn (text/command uchun)
            voice_data: ovoz (voice uchun)
            photo_data: rasm (photo uchun)
            document_data: hujjat (document uchun)
            file_name: fayl nomi (document uchun)
            callback_data: callback (inline tugma uchun)
            message_id: xabar ID

        Returns:
            TelegramOutput agar ruxsat berilsa, None aks holda
        """
        # Owner tekshiruvi
        if not await self._owner_middleware.check(user_id):
            log.warning("bot.access_denied", user_id=user_id)
            return None

        # Kirish turini aniqlash
        input_type = self._detect_input_type(
            text=text,
            voice_data=voice_data,
            photo_data=photo_data,
            document_data=document_data,
            callback_data=callback_data,
        )

        # TelegramInput yaratish
        telegram_input = TelegramInput(
            input_type=input_type,
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            voice_data=voice_data,
            photo_data=photo_data,
            document_data=document_data,
            file_name=file_name,
            callback_data=callback_data,
            message_id=message_id,
        )

        # Handleni chaqirish
        return await self._handler.handle(telegram_input)

    def _detect_input_type(
        self,
        *,
        text: str | None,
        voice_data: bytes | None,
        photo_data: bytes | None,
        document_data: bytes | None,
        callback_data: str | None,
    ) -> InputType:
        """Kirish turini aniqlash."""
        if callback_data is not None:
            return InputType.CALLBACK
        if voice_data is not None:
            return InputType.VOICE
        if photo_data is not None:
            return InputType.PHOTO
        if document_data is not None:
            return InputType.DOCUMENT
        if text and text.startswith("/"):
            return InputType.COMMAND
        return InputType.TEXT

    async def start(self) -> None:
        """Botni ishga tushirish (stub — haqiqiy polling emas).

        Bo'lim 5 lean: faqat holat o'zgarishi.
        Haqiqiy aiogram polling prod da qo'shiladi.
        """
        if self._running:
            log.warning("bot.already_running")
            return

        if not self._token:
            log.warning("bot.no_token", msg="Token berilmagan — stub rejimda ishlaydi")

        self._running = True
        log.info("bot.started", mode="stub" if not self._token else "ready")

    async def stop(self) -> None:
        """Botni to'xtatish."""
        if not self._running:
            return

        self._running = False
        log.info("bot.stopped")
