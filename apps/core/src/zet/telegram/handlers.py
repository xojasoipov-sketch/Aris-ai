"""Telegram xabar handlerlari (V-17).

Kirish turlari:
    1. Text — matnli buyruq → intent → plan → execute
    2. Voice — ovozli xabar → STT → matn → intent → plan → execute
    3. Photo — rasm → vision agent (bo'lim 8)
    4. Document — fayl → kontekst sifatida ishlov
    5. Callback — inline tugma bosildi → approval qayta ishlash

Har bir handler:
    1. Owner tekshiruvi (middleware bilan)
    2. Kirish turini aniqlash
    3. Core ga yuborish
    4. Natijani formatlash va javob qaytarish

Bog'liq qarorlar:
    V-17 — IN: text, voice, images, files
    V-18 — voice → STT → intent
    V-32 — callback → approval
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import structlog

from zet.voice.stt import STTProvider

log = structlog.get_logger(__name__)


class InputType(StrEnum):
    """Kirish turi."""

    TEXT = "text"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"
    CALLBACK = "callback"
    COMMAND = "command"


@dataclass(frozen=True)
class TelegramInput:
    """Telegram xabaridan tuzilgan kirish."""

    input_type: InputType
    """Kirish turi."""

    user_id: int
    """Telegram user ID."""

    chat_id: int
    """Telegram chat ID."""

    text: str | None = None
    """Matn (text, command, callback uchun)."""

    voice_data: bytes | None = None
    """Ovoz ma'lumotlari (voice uchun)."""

    photo_data: bytes | None = None
    """Rasm ma'lumotlari (photo uchun)."""

    document_data: bytes | None = None
    """Hujjat ma'lumotlari (document uchun)."""

    file_name: str | None = None
    """Fayl nomi (document uchun)."""

    callback_data: str | None = None
    """Callback ma'lumoti (callback uchun)."""

    message_id: int | None = None
    """Telegram xabar ID."""


@dataclass(frozen=True)
class TelegramOutput:
    """Telegram javob xabari."""

    text: str
    """Javob matni."""

    voice_data: bytes | None = None
    """Ovozli javob (TTS natijasi)."""

    parse_mode: str | None = "HTML"
    """Matn formati (HTML, Markdown)."""


@dataclass
class HandlerContext:
    """Handler konteksti — kerakli komponentlar."""

    stt: STTProvider | None = None
    """STT provayder (voice uchun)."""

    processed: list[TelegramInput] = field(default_factory=list)
    """Qayta ishlangan kirishlar ro'yxati (test uchun)."""


class MessageHandler:
    """Telegram xabarlarini qayta ishlash (V-17).

    Barcha kirish turlarini qabul qilib, matnli buyruqqa aylantiradi,
    keyin Core ga yuboradi.

    Bo'lim 5 lean: faqat matn va ovoz. Photo/document — bo'lim 8.
    """

    def __init__(self, context: HandlerContext) -> None:
        self._ctx = context

    async def handle(self, input_: TelegramInput) -> TelegramOutput:
        """Kirishni qayta ishlash va javob qaytarish.

        Args:
            input_: Telegram kirish

        Returns:
            TelegramOutput — javob xabari
        """
        self._ctx.processed.append(input_)

        match input_.input_type:
            case InputType.TEXT:
                return await self._handle_text(input_)
            case InputType.VOICE:
                return await self._handle_voice(input_)
            case InputType.COMMAND:
                return await self._handle_command(input_)
            case InputType.CALLBACK:
                return await self._handle_callback(input_)
            case InputType.PHOTO:
                return await self._handle_photo(input_)
            case InputType.DOCUMENT:
                return await self._handle_document(input_)
            case _:
                log.warning("handler.unknown_type", input_type=input_.input_type)
                return TelegramOutput(text="❓ Bu turdagi kirish hali qo'llab-quvvatlanmaydi.")

    async def _handle_text(self, input_: TelegramInput) -> TelegramOutput:
        """Matnli xabarni qayta ishlash."""
        text = input_.text or ""
        if not text.strip():
            return TelegramOutput(text="❓ Bo'sh xabar.")

        log.info(
            "handler.text",
            user_id=input_.user_id,
            text_length=len(text),
        )

        # Bo'lim 5 lean: Core pipeline chaqiruvi o'rniga echo
        # To'liq integratsiya Bo'lim 7 da
        return TelegramOutput(
            text=(
                f"✅ <b>Qabul qilindi</b>\n\n"
                f"📝 <code>{_escape_html(text[:500])}</code>\n\n"
                f"⏳ Core pipeline ulangan emas (Bo'lim 7)"
            ),
        )

    async def _handle_voice(self, input_: TelegramInput) -> TelegramOutput:
        """Ovozli xabarni qayta ishlash — STT → matn → Core."""
        if input_.voice_data is None:
            return TelegramOutput(text="❌ Ovoz ma'lumoti topilmadi.")

        if self._ctx.stt is None:
            return TelegramOutput(text="❌ STT provayder sozlanmagan.")

        log.info(
            "handler.voice",
            user_id=input_.user_id,
            audio_size=len(input_.voice_data),
        )

        # STT — ovozdan matn
        stt_result = await self._ctx.stt.transcribe(
            input_.voice_data,
            audio_format="ogg",
        )

        # Matnni Core ga yuborish (lean: echo)
        return TelegramOutput(
            text=(
                f"🎤 <b>Ovoz aniqlandi</b>\n\n"
                f"📝 <code>{_escape_html(stt_result.text[:500])}</code>\n"
                f"🌐 Til: {stt_result.language}, "
                f"ishonch: {stt_result.confidence:.0%}\n\n"
                f"⏳ Core pipeline ulangan emas (Bo'lim 7)"
            ),
        )

    async def _handle_command(self, input_: TelegramInput) -> TelegramOutput:
        """Bot buyrug'ini qayta ishlash (/start, /help, /status)."""
        command = (input_.text or "").strip().lower()

        if command in {"/start", "/help"}:
            return TelegramOutput(
                text=(
                    "🤖 <b>ZET — Shaxsiy AI operatsion tizim</b>\n\n"
                    "Buyruqlar:\n"
                    "  /start — boshlash\n"
                    "  /help — yordam\n"
                    "  /status — tizim holati\n"
                    "  /agents — agentlar ro'yxati\n"
                    "  /budget — budjet holati\n"
                    "  /killswitch — emergency stop\n\n"
                    "Matn yoki ovozli xabar yuboring — ZET bajaradi."
                ),
            )

        if command == "/status":
            return TelegramOutput(
                text=(
                    "📊 <b>ZET Status</b>\n\n"
                    "✅ Bot: faol\n"
                    "✅ Core: ulangan\n"
                    "⏳ To'liq pipeline: Bo'lim 7"
                ),
            )

        if command == "/agents":
            return TelegramOutput(
                text="📋 <b>Agentlar</b>\n\n⏳ Agent ro'yxati (Bo'lim 7 da ulanadi)",
            )

        if command == "/budget":
            return TelegramOutput(
                text="💰 <b>Budjet</b>\n\n⏳ Budjet holati (Bo'lim 7 da ulanadi)",
            )

        if command == "/killswitch":
            return TelegramOutput(
                text="🚨 <b>KillSwitch</b>\n\n⏳ KillSwitch boshqaruvi (Bo'lim 7 da ulanadi)",
            )

        return TelegramOutput(
            text=f"❓ Noma'lum buyruq: <code>{_escape_html(command)}</code>",
        )

    async def _handle_callback(self, input_: TelegramInput) -> TelegramOutput:
        """Callback (inline tugma) qayta ishlash — approval."""
        data = input_.callback_data or ""
        if not data:
            return TelegramOutput(text="❌ Callback ma'lumoti bo'sh.")

        log.info(
            "handler.callback",
            user_id=input_.user_id,
            callback_data=data,
        )

        # Callback tahlil qilish
        from zet.telegram.keyboards import ApprovalKeyboard

        try:
            parsed = ApprovalKeyboard.parse_callback(data)
        except ValueError:
            return TelegramOutput(text=f"❌ Noto'g'ri callback: {data}")

        action = parsed["action"]
        run_id = parsed["run_id"]

        if action == "approve":
            return TelegramOutput(
                text=f"✅ Run <code>{run_id}</code> tasdiqlandi.\n⏳ Bajarilmoqda...",
            )

        if action == "reject":
            return TelegramOutput(
                text=f"❌ Run <code>{run_id}</code> rad etildi.",
            )

        if action == "approve_step":
            step = parsed.get("step_position", "?")
            return TelegramOutput(
                text=f"✅ Qadam {step} (run: <code>{run_id}</code>) tasdiqlandi.",
            )

        if action == "approve_all":
            return TelegramOutput(
                text=f"✅✅ Barcha qadamlar (run: <code>{run_id}</code>) tasdiqlandi.",
            )

        return TelegramOutput(text=f"❓ Noma'lum amal: {action}")

    async def _handle_photo(self, input_: TelegramInput) -> TelegramOutput:
        """Rasm qayta ishlash — Bo'lim 8 (Camera/Vision) da to'liq."""
        log.info(
            "handler.photo",
            user_id=input_.user_id,
            has_data=input_.photo_data is not None,
        )
        return TelegramOutput(
            text="📷 Rasm qabul qilindi.\n⏳ Vision Agent (Bo'lim 8 da ulanadi)",
        )

    async def _handle_document(self, input_: TelegramInput) -> TelegramOutput:
        """Hujjat qayta ishlash — kontekst sifatida."""
        log.info(
            "handler.document",
            user_id=input_.user_id,
            file_name=input_.file_name,
        )
        return TelegramOutput(
            text=(
                f"📄 Hujjat qabul qilindi"
                f"{f': {_escape_html(input_.file_name)}' if input_.file_name else ''}\n"
                f"⏳ Hujjat qayta ishlash (Bo'lim 7 da ulanadi)"
            ),
        )


def _escape_html(text: str) -> str:
    """HTML maxsus belgilarni almashtrish."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
