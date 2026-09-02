"""ElevenLabs STT (Scribe) va TTS (Multilingual v2) integratsiyasi (Bo'lim 5, V-18).

Ilgari `StubSTT`/`StubTTS` faqat soxta qiymatlar qaytarardi — Telegram
orqali ovozli xabar yuborilsa ham qotib qolgan matn qaytardi. Ega o'zbek
tilida gapiradi, shuning uchun Uzbek qo'llab-quvvatlashi eng muhim mezon.

**STT (Scribe):** ElevenLabs Speech-to-Text `scribe_v1` modeli 99 tildan
ortiqni qo'llab-quvvatlaydi (`uzn` — o'zbek shimoliy) — hozirgi eng aniq
o'zbek transkripsiyasi. Tarmoq: `POST /v1/speech-to-text`, multipart form.

**TTS (Multilingual v2):** `eleven_multilingual_v2` `language_code`ni
rasman o'zbek uchun rad etadi (2026-08 holati), lekin lotin skript va
turkiy fonetika bilan o'zbek matnini yaxshi o'qiydi (sinab tasdiqlangan).
Shuning uchun `language_code` uzatilmaydi — model matnni avtomatik
tushunadi. Tarmoq: `POST /v1/text-to-speech/{voice_id}`.

**Fail-open:** kalit yoki `voice_id` bo'lmasa — konstruktor `is_configured
= False`, chaqiruvchi `StubSTT`/`StubTTS` orqaga moslik yo'liga o'tadi
(boshqa "real-vs-stub" naqshlar bilan bir xil: `WebSearchTool`,
`TelegramNotifier`).

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali kirish
    Bo'lim 5 — telefon orqali to'liq ish sikli
"""

from __future__ import annotations

import httpx
import structlog

from zet.voice.stt import STTProvider, STTResult
from zet.voice.tts import TTSProvider, TTSResult

log = structlog.get_logger(__name__)

_API_BASE_URL = "https://api.elevenlabs.io"
_STT_MODEL = "scribe_v1"
"""ElevenLabs'ning eng aniq va eng ko'p tilni (99+) qo'llab-quvvatlaydigan STT modeli."""

_TTS_MODEL = "eleven_multilingual_v2"
"""O'zbek matnini yaxshi o'qiydigan ko'p tilli TTS modeli (sinab tasdiqlangan)."""

_TTS_OUTPUT_FORMAT = "opus_48000_64"
"""OGG/OPUS 48 kHz 64 kbit — Telegram `sendVoice` talab qiladigan format.

Ilgari `Accept: audio/mpeg` (MP3) so'ralardi va natija `sendVoice`ga
berilardi — Telegram esa MP3ni voice note deb qabul qilmay, musiqa
pleyeri bubble'ida ko'rsatardi. Azure yo'lidagi bilan bir xil bug edi
(`azure_tts.py::_OUTPUT_FORMAT` izohiga qarang), shuning uchun ikkala
provayder ham NATIVE OPUS beradigan qilindi — ffmpeg orqali qayta
kodlash kerak emas."""

UZBEK_LANG_CODE = "uzb"
"""Scribe qabul qiladigan o'zbek tili kodi.

Ilgari bu `"uzn"` (ISO 639-3 "Northern Uzbek") edi va Scribe uni
**rad etardi**:

    Invalid language code received: 'uzn'.
    Please leave blank ... or use one of: ... uzb ...

Ya'ni til hech qachon o'rnatilmasdi. Natijada Scribe avtomatik
aniqlashga tushib, o'zbek nutqini **ozarbayjoncha** deb o'qirdi
(jonli sinov, 88% ishonch bilan):

    asl:    "Salom, men Umid. Bugun soat uchda mijoz bilan uchrashuv bor"
    'auto': "Salam, mən Ümid. Bugün suatu xədimi göz bilan oxra şuv bor"
    'uzb':  "Salom men Umid. Bugun soat uchda mijoz bilan uchrashuv bor"

Ikkala turkiy til lotin yozuvida yaqin bo'lgani uchun avtomatik
aniqlash ishonchsiz — shuning uchun til ATAYLAB majburlanadi.
"""

DEFAULT_STT_LANGUAGE = UZBEK_LANG_CODE
"""ZET bitta egaga tegishli (V-02) va ega o'zbekcha gapiradi.

Shu sabab default — avtomatik aniqlash EMAS, balki o'zbek tili.
Boshqa tilda gapirish uchun `Settings.stt_language` o'zgartiriladi.
"""

# Default ovoz — Sarah (bepul rejada mavjud, ayol, ko'p tilli, o'zbekcha
# aniq va tabiiy o'qiydi — real hisob bilan tasdiqlangan). Rachel eski
# default edi (voice_id 21m00Tcm4TlvDq8ikWAM) — u bepul rejaviy hisoblarga
# berilmaydi, 402 Payment Required qaytardi. Settings orqali almashtiriladi.
_DEFAULT_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"


class ElevenLabsSTT(STTProvider):
    """ElevenLabs Scribe orqali haqiqiy speech-to-text.

    O'zbek shimoliy (`uzn`) sifatida transkripsiya qiladi (agar `language`
    berilmasa — avtomatik aniqlash). Xato bo'lsa `RuntimeError` — chaqiruvchi
    (`ZetBot`) buni ushlab, foydalanuvchiga tushunarli xabar yuborishi kerak.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        default_language: str = DEFAULT_STT_LANGUAGE,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._default_language = default_language
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def is_configured(self) -> bool:
        """Kalit mavjudmi — chaqiruvchi haqiqiy STT tanlashi mumkinmi."""
        return bool(self._api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "ogg",
        language: str | None = None,
    ) -> STTResult:
        """Audio dan matn olish — ElevenLabs Scribe orqali."""
        if not self._api_key:
            raise RuntimeError("ElevenLabsSTT: kalit yo'q — ZET_ELEVENLABS_API_KEY sozlanmagan")

        # Til BERILMASA ham avtomatik aniqlashga tushmaymiz — `_default_language`
        # ishlatiladi. Sabab UZBEK_LANG_CODE docstring'ida: avtomatik aniqlash
        # o'zbekni ozarbayjoncha deb o'qiydi va matn butunlay buziladi.
        requested = language or self._default_language
        # `uz`/`uzn` kabi variantlar Scribe qabul qiladigan `uzb` ga keltiriladi.
        lang_code = UZBEK_LANG_CODE if requested.lower() in {"uz", "uzn", "uzb"} else requested

        files: dict[str, tuple[str, bytes, str]] = {
            "file": (f"audio.{audio_format}", audio_data, f"audio/{audio_format}"),
        }
        data: dict[str, str] = {"model_id": _STT_MODEL, "language_code": lang_code}

        try:
            response = await self._get_client().post(
                f"{_API_BASE_URL}/v1/speech-to-text",
                headers={"xi-api-key": self._api_key},
                files=files,
                data=data,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            log.warning("elevenlabs_stt.http_error", status=exc.response.status_code)
            raise RuntimeError(f"ElevenLabs STT xatosi: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            log.warning("elevenlabs_stt.network_error", error=str(exc))
            raise RuntimeError(f"ElevenLabs STT tarmoq xatosi: {exc}") from exc

        text: str = payload.get("text", "")
        detected_lang: str = payload.get("language_code") or lang_code
        # Scribe har bir so'z uchun ehtimol qaytaradi — o'rtacha olamiz
        words = payload.get("words") or []
        if words:
            probs = [w.get("logprob", 0.0) for w in words if "logprob" in w]
            # logprob → probability (juda taxminiy)
            import math

            confidence = float(sum(math.exp(p) for p in probs) / len(probs)) if probs else 1.0
            confidence = max(0.0, min(1.0, confidence))
        else:
            confidence = float(payload.get("language_probability", 1.0))

        log.info(
            "elevenlabs_stt.transcribed",
            text_length=len(text),
            language=detected_lang,
            confidence=round(confidence, 3),
        )
        return STTResult(
            text=text,
            language=detected_lang,
            confidence=confidence,
            duration_s=float(payload.get("duration_seconds", 0.0) or 0.0),
        )

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


class ElevenLabsTTS(TTSProvider):
    """ElevenLabs Multilingual v2 orqali haqiqiy text-to-speech.

    O'zbek matnini `language_code`siz uzatadi — `eleven_multilingual_v2`
    ni rasman `uz` bilan chaqirib bo'lmaydi (2026-08 holati), lekin
    matnni avtomatik tushunadi va yaxshi o'qiydi.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice_id: str = _DEFAULT_VOICE_ID,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def synthesize(
        self,
        text: str,
        *,
        language: str = "uz",  # noqa: ARG002 — model avtomatik tushunadi (docstring)
    ) -> TTSResult:
        """Matndan OGG/OPUS audio — ElevenLabs Multilingual v2 orqali (Telegram voice note)."""
        if not self._api_key:
            raise RuntimeError("ElevenLabsTTS: kalit yo'q — ZET_ELEVENLABS_API_KEY sozlanmagan")

        try:
            response = await self._get_client().post(
                f"{_API_BASE_URL}/v1/text-to-speech/{self._voice_id}",
                headers={
                    "xi-api-key": self._api_key,
                    "Accept": "audio/ogg",
                    "Content-Type": "application/json",
                },
                params={"output_format": _TTS_OUTPUT_FORMAT},
                json={
                    "text": text,
                    "model_id": _TTS_MODEL,
                    # language_code ataylab uzatilmaydi — modul-level docstring'ga qarang
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
            )
            response.raise_for_status()
            audio_bytes = response.content
        except httpx.HTTPStatusError as exc:
            log.warning("elevenlabs_tts.http_error", status=exc.response.status_code)
            raise RuntimeError(f"ElevenLabs TTS xatosi: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            log.warning("elevenlabs_tts.network_error", error=str(exc))
            raise RuntimeError(f"ElevenLabs TTS tarmoq xatosi: {exc}") from exc

        log.info(
            "elevenlabs_tts.synthesized",
            text_length=len(text),
            audio_size=len(audio_bytes),
            voice_id=self._voice_id,
        )
        return TTSResult(
            audio_data=audio_bytes,
            audio_format="ogg",
            duration_s=0.0,  # ElevenLabs javobda uzunlik qaytarmaydi
            text=text,
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()


__all__ = ["ElevenLabsSTT", "ElevenLabsTTS"]
