"""Azure Speech TTS — HAQIQIY o'zbek neyron ovozi (V-18).

NEGA AZURE, ELEVENLABS EMAS.

ElevenLabs'da o'zbek TTS **yo'q** — jonli tekshirilgan (2026-08-12):

    eleven_v3               74 til, o'zbek YO'Q (az, kk, ky, tr bor)
    eleven_multilingual_v2  29 til, o'zbek YO'Q
    ovoz kutubxonasi        "uzbek" qidiruvi 0 natija

Ya'ni ElevenLabs o'zbek matnini **chet el aksenti** bilan o'qiydi:
inglizcha ovoz lotin harflarini taxmin qiladi. Tushunarli, lekin
"haqiqiy o'zbek gapirayotgandek" emas.

Azure Speech'da esa **native o'zbek neyron ovozlari** bor:

    uz-UZ-SardorNeural   erkak
    uz-UZ-MadinaNeural   ayol

Ular o'zbek fonetikasiga o'rgatilgan — "soat", "o'g'il", "qishloq"
kabi so'zlarni to'g'ri talaffuz qiladi.

BEPUL QATLAM: oyiga 500 000 belgi (F0 tarif). Ega uchun bu amalda
cheksiz — kunlik 20-30 javob ovozga aylantirilsa ham yetadi.

Fail-open: kalit yoki region bo'lmasa `is_configured = False` va
chaqiruvchi ElevenLabs/`StubTTS` yo'liga qaytadi — repo'dagi boshqa
"real-vs-stub" naqshlar bilan bir xil.

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali kirish/chiqish
    Bo'lim 5 — telefon orqali to'liq ish sikli
"""

from __future__ import annotations

from xml.sax.saxutils import escape

import httpx
import structlog

from zet.voice.tts import TTSProvider, TTSResult

log = structlog.get_logger(__name__)

UZBEK_MALE_VOICE = "uz-UZ-SardorNeural"
"""O'zbek erkak neyron ovozi (default)."""

UZBEK_FEMALE_VOICE = "uz-UZ-MadinaNeural"
"""O'zbek ayol neyron ovozi."""

UZBEK_LOCALE = "uz-UZ"
"""SSML `xml:lang` qiymati."""

_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
"""MP3 — Telegram `sendVoice`/`sendAudio` uchun to'g'ridan-to'g'ri mos."""


def build_ssml(text: str, *, voice: str, locale: str = UZBEK_LOCALE) -> str:
    """Matndan SSML hujjat yasash.

    Matn **XML sifatida ekranlanadi**. Bu shunchaki formallik emas:
    agent javobida `&`, `<` yoki `"` bo'lsa (masalan "Narx < 100 so'm"
    yoki HTML parcha), ekranlanmagan matn SSML'ni buzadi va Azure 400
    qaytaradi — ya'ni ovoz javobi jimgina yo'qoladi.
    """
    return (
        f"<speak version='1.0' xml:lang='{locale}'>"
        f"<voice xml:lang='{locale}' name='{voice}'>{escape(text)}</voice>"
        f"</speak>"
    )


class AzureTTS(TTSProvider):
    """Azure Speech orqali o'zbek neyron ovozi.

    Endpoint: `POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1`
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        region: str = "",
        voice: str = UZBEK_MALE_VOICE,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._region = region.strip()
        self._voice = voice
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def is_configured(self) -> bool:
        """Kalit VA region bor bo'lsagina ishlaydi.

        Region majburiy — endpoint URL'ining bir qismi. Kalit bor-u
        region yo'q bo'lsa chaqiruv o'zi yiqilardi, shuning uchun bu
        yerda ochiq "sozlanmagan" deb hisoblanadi.
        """
        return bool(self._api_key) and bool(self._region)

    @property
    def voice(self) -> str:
        """Ishlatilayotgan ovoz nomi."""
        return self._voice

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def synthesize(self, text: str, *, language: str = "uz") -> TTSResult:
        """Matndan MP3 audio. Xato bo'lsa `RuntimeError`."""
        if not self.is_configured:
            raise RuntimeError(
                "AzureTTS: ZET_AZURE_SPEECH_KEY va ZET_AZURE_SPEECH_REGION sozlanmagan"
            )

        locale = UZBEK_LOCALE if language.lower().startswith("uz") else language
        ssml = build_ssml(text, voice=self._voice, locale=locale)

        try:
            response = await self._get_client().post(
                f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1",
                headers={
                    "Ocp-Apim-Subscription-Key": self._api_key or "",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": _OUTPUT_FORMAT,
                    "User-Agent": "zet",
                },
                content=ssml.encode("utf-8"),
            )
            response.raise_for_status()
            audio_bytes = response.content
        except httpx.HTTPStatusError as exc:
            log.warning("azure_tts.http_error", status=exc.response.status_code)
            raise RuntimeError(f"Azure TTS xatosi: HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            log.warning("azure_tts.network_error", error=str(exc))
            raise RuntimeError(f"Azure TTS tarmoq xatosi: {exc}") from exc

        log.info(
            "azure_tts.synthesized",
            text_length=len(text),
            audio_size=len(audio_bytes),
            voice=self._voice,
        )
        return TTSResult(
            audio_data=audio_bytes,
            audio_format="mp3",
            duration_s=0.0,
            text=text,
        )

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


__all__ = [
    "UZBEK_FEMALE_VOICE",
    "UZBEK_LOCALE",
    "UZBEK_MALE_VOICE",
    "AzureTTS",
    "build_ssml",
]
