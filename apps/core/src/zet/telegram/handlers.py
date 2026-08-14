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

import re as _re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

import structlog

from zet.voice.stt import STTProvider
from zet.voice.tts import TTSProvider

log = structlog.get_logger(__name__)

# Orchestrator har bir so'rov uchun yangi DB sessiyada quriladi — shu tufayli
# HandlerContext'ga tayyor Orchestrator emas, uni yaratuvchi factory beriladi.
# Bu ZetBot va boshqa chaqiruvchilar Orchestrator hayotini kuzatishi kerakligini
# yashiradi (masalan async context manager).
OrchestratorRunner = Callable[[str], Awaitable["OrchestratorRunResult"]]
"""`text` → run natijasi. Muvaffaqiyat/xato — ikkalasi ham `OrchestratorRunResult`da."""

ApprovalRunner = Callable[[str, str], Awaitable["ApprovalRunResult"]]
"""`(action, run_id)` → tasdiq/rad etish natijasi.

`action` — "approve" yoki "reject". Chaqiruvchi (`deps.py`)
`ApprovalService` orqali kutilayotgan tasdiqni topib, `Orchestrator`ni
`approve`+`resume` yoki `reject` chaqiradi va bajarilish natijasini
qaytaradi.
"""

KillSwitchRunner = Callable[[str, str | None], Awaitable["KillSwitchRunResult"]]
"""`(action, reason)` → killswitch amalining natijasi (SR-04).

`action` — "engage", "disengage" yoki "status". `reason` faqat "engage"
uchun ma'noli. Chaqiruvchi (`deps.py`) `KillSwitchState.engage`/
`disengage`ni chaqiradi, `persist_killswitch` bilan DB'ga yozadi,
capability tokenlarni bekor qiladi (SR-06) va audit yozuvi qo'yadi.
"""


@dataclass(frozen=True)
class OrchestratorRunResult:
    """`Orchestrator.start()` natijasining Telegram uchun sodda ko'rinishi.

    Voice/text handler bir xil formatga suyaniladi — javob TTS orqali
    ovozga ham o'girilishi mumkin (`text` — asosiy manba).
    """

    text: str
    """Foydalanuvchiga ko'rsatiladigan matn (ovozga ham beriladi)."""

    ok: bool = True
    """Muvaffaqiyatlimi (True) yoki xato (False)."""

    run_id: str | None = None
    """`RunStore`dagi ID — approval kelsa `resume(run_id)` uchun."""


@dataclass(frozen=True)
class KillSwitchRunResult:
    """Telegram `/killswitch` buyrug'i natijasi (SR-04).

    `MessageHandler` bu qiymatdan foydalanuvchiga qaytariladigan matnni
    yasaydi. `text` — asosiy javob, `ok=False` bo'lsa "❌" prefiksi
    qo'shiladi (masalan disengage'da allaqachon o'chirilgan bo'lsa).
    """

    text: str
    """Ega ko'radigan qisqa holat/xato xabari."""

    ok: bool = True
    """Amal muvaffaqiyatlimi. False bo'lsa handler xatolik prefiksi qo'yadi."""

    engaged: bool = False
    """Amal bajarilgandan keyingi killswitch holati (True — yoqilgan)."""


@dataclass(frozen=True)
class ApprovalRunResult:
    """Telegram inline approve/reject natijasi.

    NEGA ALOHIDA TIP. `OrchestratorRunResult`dan ajratildi — approval
    natijasi (masalan "tasdiqlandi, run 6-qadamda davom etmoqda")
    matn-run natijasidan boshqacha kontekstga ega. Bo'lmasa handler
    ikkalasini chalkashtirib yuborar edi."""

    text: str
    """Egaga qaytariladigan matn (agent chiqishi yoki holat xabari)."""

    ok: bool = True
    """`True` — Orchestrator xato bermadi. `False` — tasdiq eskirgan,
    run topilmadi, yoki bajarilish davom etsa xato oldi."""

    run_status: str | None = None
    """`RunStatus` qiymati (DONE/FAILED/CANCELLED/AWAITING_APPROVAL) —
    ega ko'radigan qisqa yorliq uchun."""


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

    text_parts: tuple[str, ...] | None = None
    """`text`ni bir nechta ketma-ket Telegram xabariga bo'lib yuborish.

    NEGA KERAK: odam Telegram'da bitta uzun, hammasi qamrab olingan
    blok emas, ketma-ket qisqa xabarlar bilan yozadi. `ANSWER_SYSTEM`
    javobni tabiiy fikr chegaralarida bo'sh qator bilan ajratadi
    (`_split_into_messages()`), shu qismlar shu yerda saqlanadi.

    FAQAT oddiy suhbat javoblarida ishlatiladi — approval tugmalari,
    `/status`, xato xabarlari bitta xabar bo'lib qoladi (tugma qaysi
    xabarga tegishli ekani chalkashmasin). `None` — `text` bitta
    xabar sifatida yuboriladi (eski xatti-harakat, o'zgarishsiz).
    TTS uchun `text` (bo'laklar BIRLASHTIRILGAN, to'liq matn)
    ishlatiladi — ovoz javobga mos, bitta uzluksiz oqim bo'lib qoladi."""

    voice_data: bytes | None = None
    """Ovozli javob (TTS natijasi)."""

    voice_format: str = "ogg"
    """`voice_data` formati — `TTSResult.audio_format` dan olinadi.

    NEGA KERAK: ilgari bu maydon yo'q edi va `polling.py` formatni
    QAT'IY `.ogg`/`audio/mpeg` deb faraz qilardi — TTS esa MP3 qaytarardi.
    Telegram `sendVoice` faqat OGG/OPUS qabul qiladi, MP3ni esa musiqa
    pleyeri bubble'ida ko'rsatardi. Endi haqiqiy format uzatiladi va
    `polling.py` unga qarab to'g'ri metodni tanlaydi."""

    parse_mode: str | None = "HTML"
    """Matn formati (HTML, Markdown)."""


@dataclass
class HandlerContext:
    """Handler konteksti — kerakli komponentlar."""

    stt: STTProvider | None = None
    """STT provayder (voice uchun)."""

    tts: TTSProvider | None = None
    """TTS provayder — ovozli javob uchun (yo'q bo'lsa faqat matn qaytadi)."""

    orchestrator_runner: OrchestratorRunner | None = None
    """Matn/ovozdan olingan buyruqni real Orchestrator orqali bajaruvchi factory."""

    approval_runner: ApprovalRunner | None = None
    """Inline ✅/❌ tugmalarini haqiqiy `ApprovalService`+`Orchestrator.resume()`ga
    ulaydigan factory. `None` bo'lsa handler avvalgi kosmetik javobga tushadi
    (test/lean rejim uchun orqaga mos)."""

    killswitch_runner: KillSwitchRunner | None = None
    """`/killswitch` buyrug'ini haqiqiy `KillSwitchState`ga ulaydigan factory
    (SR-04). `None` bo'lsa handler avvalgi kosmetik "ulanmagan" matnini
    qaytaradi (test/lean rejim uchun orqaga mos)."""

    reply_with_voice: bool = False
    """`True` bo'lsa har matn javobga TTS qo'shiladi (voice kirish uchun avtomatik)."""

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
            case _:  # pragma: no cover — mypy: barcha InputType qamrab olingan
                log.warning(  # type: ignore[unreachable]
                    "handler.unknown_type", input_type=input_.input_type
                )
                return TelegramOutput(text="❓ Bu turdagi kirish hali qo'llab-quvvatlanmaydi.")

    async def _handle_text(self, input_: TelegramInput) -> TelegramOutput:
        """Matnli xabarni qayta ishlash — Orchestrator orqali."""
        text = input_.text or ""
        if not text.strip():
            return TelegramOutput(text="❓ Bo'sh xabar.")

        log.info("handler.text", user_id=input_.user_id, text_length=len(text))
        return await self._run_and_reply(text, voice_reply=self._ctx.reply_with_voice)

    async def _handle_voice(self, input_: TelegramInput) -> TelegramOutput:
        """Ovozli xabarni qayta ishlash — STT → Orchestrator → TTS (agar mavjud bo'lsa)."""
        if input_.voice_data is None:
            return TelegramOutput(text="❌ Ovoz ma'lumoti topilmadi.")

        if self._ctx.stt is None:
            return TelegramOutput(text="❌ STT provayder sozlanmagan.")

        log.info("handler.voice", user_id=input_.user_id, audio_size=len(input_.voice_data))

        try:
            stt_result = await self._ctx.stt.transcribe(input_.voice_data, audio_format="ogg")
        except Exception as exc:
            log.warning("handler.voice_stt_failed", error=str(exc))
            return TelegramOutput(text=f"❌ Ovozni transkripsiya qilib bo'lmadi: {exc}")

        if not stt_result.text.strip():
            return TelegramOutput(
                text=f"❌ Ovozdan matn ajratib bo'lmadi (til={stt_result.language})."
            )

        # Voice kirish → default javob ham voice (agent gapiradi, ega gapirdi-ku)
        return await self._run_and_reply(stt_result.text, voice_reply=True)

    async def _run_and_reply(self, text: str, *, voice_reply: bool) -> TelegramOutput:
        """Buyruqni Orchestrator orqali bajaradi va (kerak bo'lsa) TTS qo'shadi.

        Orchestrator ulanmagan bo'lsa (test/lean rejim) — echo qaytaradi
        (avvalgi Bo'lim 5 lean xatti-harakati bilan orqaga mos).
        """
        if self._ctx.orchestrator_runner is None:
            reply_text = (
                f"✅ <b>Qabul qilindi</b>\n\n"
                f"📝 <code>{_escape_html(text[:500])}</code>\n\n"
                f"⏳ Core pipeline ulangan emas"
            )
            return await self._maybe_add_voice(reply_text, voice_reply=voice_reply)

        try:
            result = await self._ctx.orchestrator_runner(text)
        except Exception as exc:
            log.warning("handler.orchestrator_failed", error=str(exc))
            return TelegramOutput(text=f"⚠️ Xato: {_escape_html(str(exc)[:400])}")

        if not result.ok:
            # Xatoga yaqin holat (masalan verifikatsiya o'tmadi) — signal
            # sifatida ⚠️ qoladi, bitta xabar (bo'lish shart emas).
            reply_text = f"⚠️ {_escape_html(result.text[:3500])}"
            return await self._maybe_add_voice(reply_text, voice_reply=voice_reply)

        # Muvaffaqiyatli javob — robotcha "✅" prefiksi YO'Q. Agent javobi
        # tabiiy ravishda bir nechta qisqa xabarga bo'linishi mumkin
        # (ANSWER_SYSTEM'ning bo'sh-qator ajratish qoidasiga mos).
        raw_text = result.text[:3500]
        parts = _split_into_messages(raw_text)
        full_text = "\n\n".join(parts)
        text_parts = tuple(_escape_html(p) for p in parts) if len(parts) > 1 else None
        return await self._maybe_add_voice(
            _escape_html(full_text), voice_reply=voice_reply, text_parts=text_parts
        )

    async def _maybe_add_voice(
        self, text: str, *, voice_reply: bool, text_parts: tuple[str, ...] | None = None
    ) -> TelegramOutput:
        """TTS sozlangan va `voice_reply=True` bo'lsa — audio ham qo'shadi.

        Matnni TTSga uzatishdan oldin HTML teglarini olib tashlaymiz —
        ovoz "<b>" ni o'qib berishi ma'nisiz. Ovoz `text` (barcha
        qismlar BIRLASHTIRILGAN, to'liq matn)dan yasaladi — bo'laklarga
        bo'linmagan, bitta uzluksiz audio (javobga mos)."""
        if not voice_reply or self._ctx.tts is None:
            return TelegramOutput(text=text, text_parts=text_parts)

        clean_for_speech = _strip_html(text)
        if not clean_for_speech.strip():
            return TelegramOutput(text=text, text_parts=text_parts)

        try:
            tts_result = await self._ctx.tts.synthesize(clean_for_speech)
            voice_bytes: bytes | None = tts_result.audio_data
            # Format metadata'si YO'QOTILMAYDI — `polling.py` unga qarab
            # `sendVoice` (ogg/opus) yoki `sendAudio` (mp3) tanlaydi.
            voice_format = tts_result.audio_format
        except Exception as exc:
            log.warning("handler.tts_failed", error=str(exc))
            voice_bytes = None
            voice_format = "ogg"

        return TelegramOutput(
            text=text,
            text_parts=text_parts,
            voice_data=voice_bytes,
            voice_format=voice_format,
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
                    "  /killswitch [on|off|status] — emergency stop\n\n"
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

        if command.startswith("/killswitch"):
            return await self._handle_killswitch_command(input_.text or "")

        return TelegramOutput(
            text=f"❓ Noma'lum buyruq: <code>{_escape_html(command)}</code>",
        )

    async def _handle_killswitch_command(self, raw_text: str) -> TelegramOutput:
        """`/killswitch [engage|on|disengage|off|status] [reason]` (SR-04).

        Sinonim jufliklar:
            - `engage`, `on`, `yoq`  → yoqish
            - `disengage`, `off`, `ochir` → o'chirish
            - `status` yoki argumentsiz → joriy holat

        `killswitch_runner` ulanmagan bo'lsa (lean/test) — eski stub matnini
        qaytaradi, back-compat uchun.
        """
        parts = raw_text.strip().split(maxsplit=2)
        # parts[0] — "/killswitch". Argumentlar 1-dan boshlanadi.
        sub = parts[1].lower() if len(parts) > 1 else "status"
        reason = parts[2] if len(parts) > 2 else None

        engage_words = {"engage", "on", "yoq", "yoqish"}
        disengage_words = {"disengage", "off", "ochir", "ochirish", "o'chir"}
        status_words = {"status", "holat"}

        if sub in engage_words:
            action = "engage"
        elif sub in disengage_words:
            action = "disengage"
        elif sub in status_words:
            action = "status"
        else:
            # Noma'lum subcommand — status kabi qarab beramiz + eslatma.
            return TelegramOutput(
                text=(
                    "❓ Noma'lum killswitch amali: "
                    f"<code>{_escape_html(sub)}</code>\n\n"
                    "Ishlatish: <code>/killswitch on [sabab]</code>, "
                    "<code>/killswitch off</code>, "
                    "<code>/killswitch status</code>"
                ),
            )

        if self._ctx.killswitch_runner is None:
            # Lean/test rejim — avvalgi kosmetik javobga tushamiz.
            return TelegramOutput(
                text="🚨 <b>KillSwitch</b>\n\n⏳ KillSwitch boshqaruvi (Bo'lim 7 da ulanadi)",
            )

        try:
            result = await self._ctx.killswitch_runner(action, reason)
        except Exception as exc:
            log.warning("handler.killswitch_failed", error=str(exc), action=action)
            return TelegramOutput(text=f"❌ Xato: {_escape_html(str(exc)[:400])}")

        prefix = "🚨" if result.engaged else ("✅" if result.ok else "⚠️")
        return TelegramOutput(text=f"{prefix} {_escape_html(result.text[:3500])}")

    async def _handle_callback(self, input_: TelegramInput) -> TelegramOutput:
        """Inline ✅/❌ tugma — HAQIQIY approve/resume (GAP_ANALYSIS BROKEN #2).

        Ilgari bu yer faqat "✅ tasdiqlandi" degan chiroyli matn qaytarardi,
        `ApprovalService.approve()` va `Orchestrator.resume()`ni HECH QACHON
        chaqirmasdi. Endi `approval_runner` orqali ular haqiqatan chaqiriladi
        va bajarilish natijasi (yoki xato) ega ko'radigan matn sifatida
        qaytariladi."""
        data = input_.callback_data or ""
        if not data:
            return TelegramOutput(text="❌ Callback ma'lumoti bo'sh.")

        log.info("handler.callback", user_id=input_.user_id, callback_data=data)

        from zet.telegram.keyboards import ApprovalKeyboard

        try:
            parsed = ApprovalKeyboard.parse_callback(data)
        except ValueError:
            return TelegramOutput(text=f"❌ Noto'g'ri callback: {data}")

        action = parsed["action"]
        run_id = parsed["run_id"]

        # `approve_step`/`approve_all` — hozircha soddaligicha `approve`
        # kabi ishlaydi: keyingi kutilayotgan tasdiq bekor qilinadi.
        # (Kelajakda step-position bo'yicha selektiv approval kerak bo'lsa,
        # `parsed["step_position"]`ni `approval_runner`ga uzatib bo'ladi.)
        canonical_action = "reject" if action == "reject" else "approve"

        if self._ctx.approval_runner is None:
            # Lean/test rejim — kosmetik javob (avvalgi xatti-harakat)
            if action == "approve_step":
                step = parsed.get("step_position", "?")
                return TelegramOutput(
                    text=f"✅ Qadam {step} (run: <code>{run_id}</code>) tasdiqlandi.",
                )
            if action == "approve_all":
                return TelegramOutput(
                    text=f"✅✅ Barcha qadamlar (run: <code>{run_id}</code>) tasdiqlandi.",
                )
            return TelegramOutput(
                text=(
                    f"✅ Run <code>{run_id}</code> tasdiqlandi.\n⏳ Bajarilmoqda..."
                    if canonical_action == "approve"
                    else f"❌ Run <code>{run_id}</code> rad etildi."
                ),
            )

        try:
            result = await self._ctx.approval_runner(canonical_action, run_id)
        except Exception as exc:
            log.warning("handler.approval_failed", error=str(exc), run_id=run_id)
            return TelegramOutput(text=f"❌ Xato: {_escape_html(str(exc)[:400])}")

        emoji = "✅" if result.ok else "⚠️"
        status_line = f" · <code>{result.run_status}</code>" if result.run_status else ""
        return TelegramOutput(
            text=f"{emoji} <code>{run_id[:8]}</code>{status_line}\n\n{_escape_html(result.text[:3500])}",
        )

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


_MAX_MESSAGE_PARTS: Final = 3
"""Ketma-ket yuboriladigan xabarlar cheklovi — Telegram'ni to'ldirmaslik uchun."""

_MIN_PART_LEN: Final = 20
"""Bundan qisqa parcha qo'shni xabarga birlashtiriladi.

MUHIM: bu chegara PAST bo'lishi kerak. Maqsad — ketma-ket QISQA
xabarlar (odam yozganidek), ya'ni 30-50 belgilik jumlalar ODATIY
holat, birlashtirish emas. `_MIN_PART_LEN` faqat haqiqatan tirband
parchalarni (masalan "Ha.", "Ok.") qo'shni xabarga qo'shish uchun —
30+ belgilik to'liq jumla mustaqil xabar bo'lib qolishi kerak."""

_BLANK_LINE_RE: Final = _re.compile(r"\n\s*\n+")


def _split_into_messages(
    text: str, *, max_parts: int = _MAX_MESSAGE_PARTS, min_len: int = _MIN_PART_LEN
) -> list[str]:
    """Javobni tabiiy bo'sh-qator chegaralarida bir nechta xabarga ajratadi.

    `ANSWER_SYSTEM` javobni FAQAT haqiqatan alohida fikrlar bo'lganda
    bo'sh qator bilan ajratishni so'raydi — bu funksiya shu chegaralarni
    ketma-ket Telegram xabarlariga aylantiradi (odam yozganidek, bitta
    uzun blok emas). Bitta fikr bo'lsa (bo'sh qator yo'q) — o'zgarishsiz
    bitta elementli ro'yxat qaytadi.
    """
    raw_parts = [p.strip() for p in _BLANK_LINE_RE.split(text.strip()) if p.strip()]
    if len(raw_parts) <= 1:
        return raw_parts or [text.strip()]

    merged: list[str] = []
    for part in raw_parts:
        if merged and len(part) < min_len:
            merged[-1] = f"{merged[-1]}\n\n{part}"
        else:
            merged.append(part)

    if len(merged) > max_parts:
        head, tail = merged[: max_parts - 1], merged[max_parts - 1 :]
        merged = [*head, "\n\n".join(tail)]

    return merged


def _escape_html(text: str) -> str:
    """HTML maxsus belgilarni almashtrish."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_TAG_RE: Final = _re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """HTML teglarni olib tashlaydi va entity'larni ochadi — TTS uchun toza matn."""
    without_tags: str = _TAG_RE.sub("", text)
    return without_tags.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()
