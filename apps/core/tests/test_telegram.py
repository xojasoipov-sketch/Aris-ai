"""Bo'lim 5 — Telegram + Voice testlari.

Tekshiriladi:
    - STTProvider va StubSTT
    - TTSProvider va StubTTS
    - OwnerMiddleware (A-05, R-04)
    - InlineKeyboard va ApprovalKeyboard (V-32)
    - MessageHandler — text, voice, command, callback, photo, document
    - ZetBot — to'liq oqim (owner tekshiruvi + handler)
    - Notifier va StubNotifier
    - Config — telegram sozlamalari
"""

from __future__ import annotations

import pytest

from zet.config import Settings
from zet.telegram.bot import ZetBot
from zet.telegram.handlers import (
    HandlerContext,
    InputType,
    MessageHandler,
    TelegramInput,
)
from zet.telegram.keyboards import ApprovalKeyboard, InlineKeyboard
from zet.telegram.middleware import OwnerMiddleware
from zet.telegram.notifier import (
    Notification,
    NotificationType,
    StubNotifier,
)
from zet.voice.stt import STTResult, StubSTT
from zet.voice.tts import StubTTS, TTSResult

# ── STT testlari ────────────────────────────────────────────────


class TestSTT:
    def test_stt_result_model(self) -> None:
        """STTResult modeli to'g'ri ishlaydi."""
        result = STTResult(text="salom", language="uz", confidence=0.95, duration_s=2.5)
        assert result.text == "salom"
        assert result.language == "uz"
        assert result.confidence == 0.95
        assert result.duration_s == 2.5

    def test_stt_result_defaults(self) -> None:
        """STTResult default qiymatlari."""
        result = STTResult(text="test")
        assert result.language == "uz"
        assert result.confidence == 1.0
        assert result.duration_s == 0.0

    @pytest.mark.asyncio()
    async def test_stub_stt_transcribe(self) -> None:
        """StubSTT doimo default matn qaytaradi."""
        stt = StubSTT(default_text="Salom dunyo")
        result = await stt.transcribe(b"audio_data", audio_format="ogg")
        assert result.text == "Salom dunyo"
        assert result.language == "uz"
        assert result.confidence == 1.0

    @pytest.mark.asyncio()
    async def test_stub_stt_custom_language(self) -> None:
        """StubSTT tilni qaytaradi."""
        stt = StubSTT()
        result = await stt.transcribe(b"data", language="en")
        assert result.language == "en"


# ── TTS testlari ────────────────────────────────────────────────


class TestTTS:
    def test_tts_result_model(self) -> None:
        """TTSResult modeli to'g'ri ishlaydi."""
        result = TTSResult(audio_data=b"audio", audio_format="ogg", duration_s=1.5, text="test")
        assert result.audio_data == b"audio"
        assert result.audio_format == "ogg"
        assert result.duration_s == 1.5
        assert result.text == "test"

    @pytest.mark.asyncio()
    async def test_stub_tts_synthesize(self) -> None:
        """StubTTS audio qaytaradi."""
        tts = StubTTS()
        result = await tts.synthesize("Salom dunyo")
        assert len(result.audio_data) > 0
        assert result.audio_format == "ogg"
        assert result.text == "Salom dunyo"

    @pytest.mark.asyncio()
    async def test_stub_tts_has_ogg_header(self) -> None:
        """StubTTS OGG header bilan qaytaradi."""
        tts = StubTTS()
        result = await tts.synthesize("test")
        assert result.audio_data[:4] == b"OggS"


# ── Owner Middleware testlari ────────────────────────────────────


class TestOwnerMiddleware:
    def test_init_with_ids(self) -> None:
        """Owner ID lar to'g'ri saqlanadi."""
        mw = OwnerMiddleware({123, 456})
        assert mw.owner_ids == frozenset({123, 456})

    def test_init_empty(self) -> None:
        """Bo'sh allowlist — hech kimga ruxsat yo'q."""
        mw = OwnerMiddleware(set())
        assert len(mw.owner_ids) == 0

    def test_is_owner_true(self) -> None:
        """Ro'yxatdagi user_id — ega."""
        mw = OwnerMiddleware({123})
        assert mw.is_owner(123)

    def test_is_owner_false(self) -> None:
        """Ro'yxatda yo'q user_id — ega emas."""
        mw = OwnerMiddleware({123})
        assert not mw.is_owner(999)

    @pytest.mark.asyncio()
    async def test_check_allowed(self) -> None:
        """Owner check — ruxsat berildi."""
        mw = OwnerMiddleware({123})
        assert await mw.check(123, "owner_user")

    @pytest.mark.asyncio()
    async def test_check_denied(self) -> None:
        """Owner check — ruxsat rad etildi."""
        mw = OwnerMiddleware({123})
        assert not await mw.check(999, "unknown_user")

    @pytest.mark.asyncio()
    async def test_check_no_username(self) -> None:
        """Owner check — username None bo'lsa ham ishlaydi."""
        mw = OwnerMiddleware({123})
        assert await mw.check(123)

    def test_frozen_owner_ids(self) -> None:
        """Owner IDs o'zgartirib bo'lmaydi (frozenset)."""
        mw = OwnerMiddleware({123})
        assert isinstance(mw.owner_ids, frozenset)


# ── Keyboard testlari ────────────────────────────────────────────


class TestApprovalKeyboard:
    def test_for_run(self) -> None:
        """Run uchun tasdiq klaviaturasi."""
        kb = ApprovalKeyboard.for_run("run_123")
        assert len(kb.rows) == 1
        assert len(kb.rows[0]) == 2
        assert kb.rows[0][0].text == "✅ Tasdiqlash"
        assert kb.rows[0][0].callback_data == "approve:run_123"
        assert kb.rows[0][1].text == "❌ Rad etish"
        assert kb.rows[0][1].callback_data == "reject:run_123"

    def test_for_step(self) -> None:
        """Qadam uchun tasdiq klaviaturasi."""
        kb = ApprovalKeyboard.for_step("run_123", 2)
        assert len(kb.rows) == 2
        # Birinchi qator: qadam tasdiq/rad
        assert kb.rows[0][0].callback_data == "approve_step:run_123:2"
        assert kb.rows[0][1].callback_data == "reject_step:run_123:2"
        # Ikkinchi qator: barchasini tasdiqlash
        assert kb.rows[1][0].callback_data == "approve_all:run_123"

    def test_parse_approve(self) -> None:
        """Callback data tahlil — approve."""
        result = ApprovalKeyboard.parse_callback("approve:run_123")
        assert result["action"] == "approve"
        assert result["run_id"] == "run_123"

    def test_parse_reject(self) -> None:
        """Callback data tahlil — reject."""
        result = ApprovalKeyboard.parse_callback("reject:run_456")
        assert result["action"] == "reject"
        assert result["run_id"] == "run_456"

    def test_parse_step(self) -> None:
        """Callback data tahlil — step bilan."""
        result = ApprovalKeyboard.parse_callback("approve_step:run_123:5")
        assert result["action"] == "approve_step"
        assert result["run_id"] == "run_123"
        assert result["step_position"] == "5"

    def test_parse_invalid(self) -> None:
        """Noto'g'ri callback data → ValueError."""
        with pytest.raises(ValueError, match="Noto'g'ri"):
            ApprovalKeyboard.parse_callback("invalid")

    def test_confirm_action(self) -> None:
        """Umumiy tasdiqlash klaviaturasi."""
        kb = ApprovalKeyboard.confirm_action("delete_agent")
        assert len(kb.rows) == 1
        assert kb.rows[0][0].callback_data == "confirm:delete_agent"
        assert kb.rows[0][1].callback_data == "cancel:delete_agent"

    def test_inline_keyboard_is_frozen(self) -> None:
        """InlineKeyboard frozen dataclass."""
        kb = InlineKeyboard(rows=[])
        assert kb.rows == []


# ── Handler testlari ─────────────────────────────────────────────


class TestMessageHandler:
    @pytest.fixture()
    def handler(self) -> MessageHandler:
        stt = StubSTT(default_text="Aniqlangan matn")
        ctx = HandlerContext(stt=stt)
        return MessageHandler(ctx)

    @pytest.mark.asyncio()
    async def test_handle_text(self, handler: MessageHandler) -> None:
        """Text xabar qayta ishlash."""
        input_ = TelegramInput(
            input_type=InputType.TEXT,
            user_id=123,
            chat_id=123,
            text="Havo qanday?",
        )
        result = await handler.handle(input_)
        assert "Qabul qilindi" in result.text
        assert "Havo qanday?" in result.text

    @pytest.mark.asyncio()
    async def test_handle_empty_text(self, handler: MessageHandler) -> None:
        """Bo'sh matn — xato xabari."""
        input_ = TelegramInput(
            input_type=InputType.TEXT,
            user_id=123,
            chat_id=123,
            text="",
        )
        result = await handler.handle(input_)
        assert "Bo'sh xabar" in result.text

    @pytest.mark.asyncio()
    async def test_handle_voice(self, handler: MessageHandler) -> None:
        """Ovozli xabar — STT natijasi ko'rsatiladi."""
        input_ = TelegramInput(
            input_type=InputType.VOICE,
            user_id=123,
            chat_id=123,
            voice_data=b"fake_audio_data",
        )
        result = await handler.handle(input_)
        assert "Ovoz aniqlandi" in result.text
        assert "Aniqlangan matn" in result.text

    @pytest.mark.asyncio()
    async def test_handle_voice_no_data(self, handler: MessageHandler) -> None:
        """Ovozli xabar — ma'lumot yo'q."""
        input_ = TelegramInput(
            input_type=InputType.VOICE,
            user_id=123,
            chat_id=123,
        )
        result = await handler.handle(input_)
        assert "topilmadi" in result.text

    @pytest.mark.asyncio()
    async def test_handle_voice_no_stt(self) -> None:
        """Ovozli xabar — STT provayder yo'q."""
        handler = MessageHandler(HandlerContext(stt=None))
        input_ = TelegramInput(
            input_type=InputType.VOICE,
            user_id=123,
            chat_id=123,
            voice_data=b"audio",
        )
        result = await handler.handle(input_)
        assert "STT provayder" in result.text

    @pytest.mark.asyncio()
    async def test_handle_command_start(self, handler: MessageHandler) -> None:
        """Bot /start buyrug'i."""
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=123,
            chat_id=123,
            text="/start",
        )
        result = await handler.handle(input_)
        assert "ZET" in result.text
        assert "/help" in result.text

    @pytest.mark.asyncio()
    async def test_handle_command_help(self, handler: MessageHandler) -> None:
        """Bot /help buyrug'i."""
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=123,
            chat_id=123,
            text="/help",
        )
        result = await handler.handle(input_)
        assert "Buyruqlar" in result.text

    @pytest.mark.asyncio()
    async def test_handle_command_status(self, handler: MessageHandler) -> None:
        """Bot /status buyrug'i."""
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=123,
            chat_id=123,
            text="/status",
        )
        result = await handler.handle(input_)
        assert "Status" in result.text

    @pytest.mark.asyncio()
    async def test_handle_command_unknown(self, handler: MessageHandler) -> None:
        """Noma'lum buyruq."""
        input_ = TelegramInput(
            input_type=InputType.COMMAND,
            user_id=123,
            chat_id=123,
            text="/unknown",
        )
        result = await handler.handle(input_)
        assert "Noma'lum buyruq" in result.text

    @pytest.mark.asyncio()
    async def test_handle_callback_approve(self, handler: MessageHandler) -> None:
        """Callback — approve."""
        input_ = TelegramInput(
            input_type=InputType.CALLBACK,
            user_id=123,
            chat_id=123,
            callback_data="approve:run_123",
        )
        result = await handler.handle(input_)
        assert "tasdiqlandi" in result.text
        assert "run_123" in result.text

    @pytest.mark.asyncio()
    async def test_handle_callback_reject(self, handler: MessageHandler) -> None:
        """Callback — reject."""
        input_ = TelegramInput(
            input_type=InputType.CALLBACK,
            user_id=123,
            chat_id=123,
            callback_data="reject:run_456",
        )
        result = await handler.handle(input_)
        assert "rad etildi" in result.text

    @pytest.mark.asyncio()
    async def test_handle_callback_approve_step(self, handler: MessageHandler) -> None:
        """Callback — step approve."""
        input_ = TelegramInput(
            input_type=InputType.CALLBACK,
            user_id=123,
            chat_id=123,
            callback_data="approve_step:run_123:3",
        )
        result = await handler.handle(input_)
        assert "Qadam 3" in result.text
        assert "tasdiqlandi" in result.text

    @pytest.mark.asyncio()
    async def test_handle_callback_approve_all(self, handler: MessageHandler) -> None:
        """Callback — approve all."""
        input_ = TelegramInput(
            input_type=InputType.CALLBACK,
            user_id=123,
            chat_id=123,
            callback_data="approve_all:run_123",
        )
        result = await handler.handle(input_)
        assert "Barcha qadamlar" in result.text

    @pytest.mark.asyncio()
    async def test_handle_callback_invalid(self, handler: MessageHandler) -> None:
        """Callback — noto'g'ri format."""
        input_ = TelegramInput(
            input_type=InputType.CALLBACK,
            user_id=123,
            chat_id=123,
            callback_data="invalid",
        )
        result = await handler.handle(input_)
        assert "Noto'g'ri" in result.text

    @pytest.mark.asyncio()
    async def test_handle_callback_empty(self, handler: MessageHandler) -> None:
        """Callback — bo'sh data."""
        input_ = TelegramInput(
            input_type=InputType.CALLBACK,
            user_id=123,
            chat_id=123,
            callback_data="",
        )
        result = await handler.handle(input_)
        assert "bo'sh" in result.text

    @pytest.mark.asyncio()
    async def test_handle_photo(self, handler: MessageHandler) -> None:
        """Rasm — Bo'lim 8 ga yo'naltirish."""
        input_ = TelegramInput(
            input_type=InputType.PHOTO,
            user_id=123,
            chat_id=123,
            photo_data=b"fake_photo",
        )
        result = await handler.handle(input_)
        assert "Rasm qabul qilindi" in result.text

    @pytest.mark.asyncio()
    async def test_handle_document(self, handler: MessageHandler) -> None:
        """Hujjat qayta ishlash."""
        input_ = TelegramInput(
            input_type=InputType.DOCUMENT,
            user_id=123,
            chat_id=123,
            document_data=b"file_content",
            file_name="report.pdf",
        )
        result = await handler.handle(input_)
        assert "Hujjat qabul qilindi" in result.text
        assert "report.pdf" in result.text

    @pytest.mark.asyncio()
    async def test_handle_document_no_name(self, handler: MessageHandler) -> None:
        """Hujjat — fayl nomi yo'q."""
        input_ = TelegramInput(
            input_type=InputType.DOCUMENT,
            user_id=123,
            chat_id=123,
            document_data=b"file_content",
        )
        result = await handler.handle(input_)
        assert "Hujjat qabul qilindi" in result.text

    @pytest.mark.asyncio()
    async def test_processed_list(self, handler: MessageHandler) -> None:
        """Handler qayta ishlangan kirishlarni saqlaydi."""
        input_ = TelegramInput(
            input_type=InputType.TEXT,
            user_id=123,
            chat_id=123,
            text="test",
        )
        await handler.handle(input_)
        assert len(handler._ctx.processed) == 1
        assert handler._ctx.processed[0] is input_

    @pytest.mark.asyncio()
    async def test_html_escape(self, handler: MessageHandler) -> None:
        """HTML maxsus belgilar almashtiriladi."""
        input_ = TelegramInput(
            input_type=InputType.TEXT,
            user_id=123,
            chat_id=123,
            text="<script>alert('xss')</script>",
        )
        result = await handler.handle(input_)
        assert "<script>" not in result.text
        assert "&lt;script&gt;" in result.text


# ── ZetBot testlari ──────────────────────────────────────────────


class TestZetBot:
    @pytest.fixture()
    def bot(self) -> ZetBot:
        return ZetBot(
            owner_ids={123, 456},
            stt=StubSTT(default_text="Ovozli buyruq"),
        )

    @pytest.mark.asyncio()
    async def test_process_text_owner(self, bot: ZetBot) -> None:
        """Ega matnli xabar yuboradi — javob qaytaradi."""
        result = await bot.process_message(
            user_id=123,
            chat_id=123,
            text="Havo qanday?",
        )
        assert result is not None
        assert "Qabul qilindi" in result.text

    @pytest.mark.asyncio()
    async def test_process_text_non_owner(self, bot: ZetBot) -> None:
        """Notanish foydalanuvchi — None qaytaradi."""
        result = await bot.process_message(
            user_id=999,
            chat_id=999,
            text="Hack attempt",
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_process_voice_owner(self, bot: ZetBot) -> None:
        """Ega ovozli xabar yuboradi — STT natijasi."""
        result = await bot.process_message(
            user_id=123,
            chat_id=123,
            voice_data=b"fake_audio",
        )
        assert result is not None
        assert "Ovozli buyruq" in result.text

    @pytest.mark.asyncio()
    async def test_process_callback(self, bot: ZetBot) -> None:
        """Ega callback (inline tugma) bosadi."""
        result = await bot.process_message(
            user_id=456,
            chat_id=456,
            callback_data="approve:run_test",
        )
        assert result is not None
        assert "tasdiqlandi" in result.text

    @pytest.mark.asyncio()
    async def test_process_command(self, bot: ZetBot) -> None:
        """Ega /start buyrug'i yuboradi."""
        result = await bot.process_message(
            user_id=123,
            chat_id=123,
            text="/start",
        )
        assert result is not None
        assert "ZET" in result.text

    @pytest.mark.asyncio()
    async def test_process_photo(self, bot: ZetBot) -> None:
        """Ega rasm yuboradi."""
        result = await bot.process_message(
            user_id=123,
            chat_id=123,
            photo_data=b"photo_bytes",
        )
        assert result is not None
        assert "Rasm" in result.text

    @pytest.mark.asyncio()
    async def test_process_document(self, bot: ZetBot) -> None:
        """Ega hujjat yuboradi."""
        result = await bot.process_message(
            user_id=123,
            chat_id=123,
            document_data=b"doc_bytes",
            file_name="test.pdf",
        )
        assert result is not None
        assert "Hujjat" in result.text

    @pytest.mark.asyncio()
    async def test_detect_input_type_callback(self, bot: ZetBot) -> None:
        """Callback aniqlash — ustuvorlik."""
        assert (
            bot._detect_input_type(
                text=None,
                voice_data=None,
                photo_data=None,
                document_data=None,
                callback_data="test",
            )
            == InputType.CALLBACK
        )

    @pytest.mark.asyncio()
    async def test_detect_input_type_voice(self, bot: ZetBot) -> None:
        """Voice aniqlash."""
        assert (
            bot._detect_input_type(
                text=None,
                voice_data=b"audio",
                photo_data=None,
                document_data=None,
                callback_data=None,
            )
            == InputType.VOICE
        )

    @pytest.mark.asyncio()
    async def test_detect_input_type_command(self, bot: ZetBot) -> None:
        """Command aniqlash."""
        assert (
            bot._detect_input_type(
                text="/help",
                voice_data=None,
                photo_data=None,
                document_data=None,
                callback_data=None,
            )
            == InputType.COMMAND
        )

    @pytest.mark.asyncio()
    async def test_detect_input_type_text(self, bot: ZetBot) -> None:
        """Text aniqlash."""
        assert (
            bot._detect_input_type(
                text="salom",
                voice_data=None,
                photo_data=None,
                document_data=None,
                callback_data=None,
            )
            == InputType.TEXT
        )

    @pytest.mark.asyncio()
    async def test_start_stop(self, bot: ZetBot) -> None:
        """Bot start/stop."""
        assert not bot.is_running
        await bot.start()
        assert bot.is_running
        await bot.stop()
        assert not bot.is_running

    @pytest.mark.asyncio()
    async def test_double_start(self, bot: ZetBot) -> None:
        """Ikki marta start — xatolik yo'q."""
        await bot.start()
        await bot.start()  # ikkinchi marta — skip
        assert bot.is_running
        await bot.stop()

    def test_bot_properties(self, bot: ZetBot) -> None:
        """Bot property lari."""
        assert bot.owner_middleware is not None
        assert bot.handler is not None
        assert bot.notifier is not None

    def test_bot_default_init(self) -> None:
        """Bot default sozlamalar bilan yaratiladi."""
        bot = ZetBot()
        assert len(bot.owner_middleware.owner_ids) == 0
        assert not bot.is_running


# ── Notifier testlari ────────────────────────────────────────────


class TestNotifier:
    @pytest.fixture()
    def notifier(self) -> StubNotifier:
        return StubNotifier()

    @pytest.mark.asyncio()
    async def test_send_text(self, notifier: StubNotifier) -> None:
        """Oddiy matnli xabar yuborish."""
        ok = await notifier.send_text("Salom!")
        assert ok
        assert notifier.count == 1
        assert notifier.sent[0].type == NotificationType.MESSAGE
        assert notifier.sent[0].text == "Salom!"

    @pytest.mark.asyncio()
    async def test_send_approval(self, notifier: StubNotifier) -> None:
        """Approval so'rovi yuborish."""
        from zet.telegram.keyboards import InlineButton

        kb = InlineKeyboard(rows=[[InlineButton(text="✅", callback_data="approve:run_1")]])
        ok = await notifier.send_approval("Tasdiqlaysizmi?", kb, run_id="run_1")
        assert ok
        assert notifier.sent[0].type == NotificationType.APPROVAL
        assert notifier.sent[0].keyboard is not None
        assert notifier.sent[0].run_id == "run_1"

    @pytest.mark.asyncio()
    async def test_send_task_result(self, notifier: StubNotifier) -> None:
        """Task natijasi yuborish."""
        ok = await notifier.send_task_result(
            "Task bajarildi",
            run_id="run_2",
            agent_name="researcher",
        )
        assert ok
        assert notifier.sent[0].type == NotificationType.TASK_RESULT
        assert notifier.sent[0].agent_name == "researcher"

    @pytest.mark.asyncio()
    async def test_send_alert(self, notifier: StubNotifier) -> None:
        """Tizim ogohlantirishi yuborish."""
        ok = await notifier.send_alert("Budjet 80% sarflandi!")
        assert ok
        assert notifier.sent[0].type == NotificationType.SYSTEM_ALERT

    @pytest.mark.asyncio()
    async def test_send_multiple(self, notifier: StubNotifier) -> None:
        """Ko'p xabar yuborish."""
        await notifier.send_text("1")
        await notifier.send_text("2")
        await notifier.send_text("3")
        assert notifier.count == 3

    @pytest.mark.asyncio()
    async def test_clear(self, notifier: StubNotifier) -> None:
        """Ro'yxatni tozalash."""
        await notifier.send_text("test")
        notifier.clear()
        assert notifier.count == 0

    def test_notification_model(self) -> None:
        """Notification modeli to'g'ri ishlaydi."""
        n = Notification(type=NotificationType.MESSAGE, text="Test")
        assert n.type == NotificationType.MESSAGE
        assert n.text == "Test"
        assert n.keyboard is None
        assert n.run_id is None
        assert n.agent_name is None
        assert n.created_at is not None


# ── Config testlari ──────────────────────────────────────────────


class TestTelegramConfig:
    def test_telegram_owner_ids_parsing(self) -> None:
        """Telegram owner ID larni tahlil qilish."""
        s = Settings(
            telegram_owner_ids="123,456,789",
            _env_file=None,  # type: ignore[call-arg]
        )
        ids = s.telegram_owner_id_set
        assert ids == {123, 456, 789}

    def test_telegram_owner_ids_empty(self) -> None:
        """Bo'sh owner ID lar — bo'sh to'plam."""
        s = Settings(
            telegram_owner_ids="",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.telegram_owner_id_set == set()

    def test_telegram_owner_ids_whitespace(self) -> None:
        """Bo'shliqli owner ID lar."""
        s = Settings(
            telegram_owner_ids=" 123 , 456 ",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.telegram_owner_id_set == {123, 456}

    def test_telegram_bot_token_default(self) -> None:
        """Bot token default None."""
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.telegram_bot_token is None

    def test_telegram_owner_ids_single(self) -> None:
        """Bitta owner ID."""
        s = Settings(
            telegram_owner_ids="123456789",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.telegram_owner_id_set == {123456789}
