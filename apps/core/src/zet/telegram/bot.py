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
    ApprovalRunner,
    HandlerContext,
    InputType,
    MessageHandler,
    OrchestratorRunner,
    TelegramInput,
    TelegramOutput,
)
from zet.telegram.middleware import OwnerMiddleware
from zet.telegram.notifier import Notifier, StubNotifier
from zet.voice.stt import STTProvider, StubSTT
from zet.voice.tts import TTSProvider

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
        tts: TTSProvider | None = None,
        notifier: Notifier | None = None,
        orchestrator_runner: OrchestratorRunner | None = None,
        approval_runner: ApprovalRunner | None = None,
        moderated_chat_ids: frozenset[int] = frozenset(),
    ) -> None:
        """
        Args:
            token: Telegram bot token (prod uchun kerak)
            owner_ids: ruxsat etilgan Telegram user_id lar
            stt: STT provayder (None = StubSTT)
            tts: TTS provayder — ovozli javob uchun (None → faqat matn)
            notifier: bildirishnoma yuboruvchi (None = StubNotifier)
            orchestrator_runner: matn/ovoz → real agent bajarilishi. None
                bo'lsa handler avvalgi Bo'lim 5 lean echo qaytaradi.
            moderated_chat_ids: shu chat'lardagi xabarlar moderatsiya
                qilinadi (Z51, #44) — bo'sh bo'lsa hech narsa o'chirilmaydi.
        """
        self._token = token
        self._owner_middleware = OwnerMiddleware(owner_ids or set())
        self._moderated_chat_ids = moderated_chat_ids
        self._stt = stt or StubSTT()
        self._tts = tts
        self._notifier = notifier or StubNotifier()
        self._handler = MessageHandler(
            HandlerContext(
                stt=self._stt,
                tts=tts,
                orchestrator_runner=orchestrator_runner,
                approval_runner=approval_runner,
            )
        )
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
    def moderated_chat_ids(self) -> frozenset[int]:
        """Moderatsiya qilinadigan chat ID'lar (Z51, #44)."""
        return self._moderated_chat_ids

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
        """Botni ishga tushirish.

        Token bo'lsa — haqiqiy long-polling loopini (TelegramPoller) fon
        task sifatida ishga tushiradi va darhol qaytadi (chaqiruvchi kutmaydi).
        Tokensiz — stub rejimda ishlaydi (test/dev).
        """
        if self._running:
            log.warning("bot.already_running")
            return

        if not self._token:
            log.warning("bot.no_token", msg="Token berilmagan — stub rejimda ishlaydi")
            self._running = True
            log.info("bot.started", mode="stub")
            return

        # Kech (deferred) import — polling.py ZetBot'ga bog'liq (TYPE_CHECKING)
        from zet.telegram.polling import TelegramPoller

        self._poller = TelegramPoller(
            token=self._token, bot=self, moderated_chat_ids=self._moderated_chat_ids
        )
        self._poller_task = __import__("asyncio").create_task(self._poller.run_forever())
        self._running = True
        log.info("bot.started", mode="polling")

    async def stop(self) -> None:
        """Botni to'xtatish — polling loopini yopadi va HTTP klientni tozalaydi."""
        if not self._running:
            return

        poller = getattr(self, "_poller", None)
        poller_task = getattr(self, "_poller_task", None)
        if poller is not None:
            poller.stop()
        if poller_task is not None:
            poller_task.cancel()
            import asyncio
            import contextlib

            with contextlib.suppress(asyncio.CancelledError, Exception):
                await poller_task
        if poller is not None:
            await poller.aclose()

        self._running = False
        log.info("bot.stopped")
