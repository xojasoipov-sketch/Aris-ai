"""O'zbek ovozi testlari (Z43).

Bu fayl aynan bitta jonli nosozlikni qulflaydi: **ega ovozini tizim
tushunmasdi.**

Sabab ikkita edi:

  1. `_UZBEK_LANG_CODE = "uzn"` — Scribe bu kodni RAD ETADI
     (`Invalid language code received: 'uzn'`). Ya'ni til hech qachon
     o'rnatilmasdi.
  2. Til o'rnatilmagach Scribe avtomatik aniqlashga tushardi va o'zbek
     nutqini **ozarbayjoncha** deb o'qirdi (88% ishonch bilan):

         asl:    "Salom, men Umid. Bugun soat uchda mijoz bilan uchrashuv bor"
         natija: "Salam, mən Ümid. Bugün suatu xədimi göz bilan oxra şuv bor"

Ikkala til lotin yozuvida juda yaqin — shuning uchun avtomatik aniqlash
printsipial ishonchsiz va til MAJBURLANADI.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.api.deps import get_stt, get_tts
from zet.config import Settings
from zet.voice.azure_tts import (
    UZBEK_FEMALE_VOICE,
    UZBEK_MALE_VOICE,
    AzureTTS,
    build_ssml,
)
from zet.voice.elevenlabs import UZBEK_LANG_CODE, ElevenLabsSTT, ElevenLabsTTS
from zet.voice.stt import StubSTT
from zet.voice.tts import StubTTS

STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
AZURE_URL = "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1"

TRANSCRIPT = "Salom men Umid. Bugun soat uchda mijoz bilan uchrashuv bor"


def _stt_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"language_code": "uzb", "language_probability": 1.0, "text": TRANSCRIPT},
    )


def _settings(**kwargs: object) -> Settings:
    """Test Settings — ovoz kalitlari ANIQ boshqariladi (`.env` ta'siri yo'q)."""
    base: dict[str, object] = {
        "elevenlabs_api_key": None,
        "azure_speech_key": None,
        "azure_speech_region": "",
    }
    base.update(kwargs)
    return Settings.model_validate(base)


class TestUzbekLanguageCode:
    """Til kodi Scribe qabul qiladigan qiymat bo'lishi SHART."""

    def test_code_is_uzb_not_uzn(self) -> None:
        """`uzn` Scribe tomonidan rad etiladi — bu regressiya qorovuli."""
        assert UZBEK_LANG_CODE == "uzb"
        assert UZBEK_LANG_CODE != "uzn"


class TestLanguageIsAlwaysSent:
    """Scribe'ga til HAR DOIM uzatiladi — avtomatik aniqlash yo'q."""

    @respx.mock
    async def test_default_language_is_sent_without_being_asked(self) -> None:
        """Chaqiruvchi til bermasa ham `uzb` yuboriladi.

        Telegram handler `transcribe(audio, audio_format="ogg")` deb
        chaqiradi — tilsiz. Ilgari aynan shu yo'l avtomatik aniqlashga
        tushib matnni buzardi.
        """
        route = respx.post(STT_URL).mock(return_value=_stt_response())

        result = await ElevenLabsSTT(api_key="k").transcribe(b"audio")

        assert route.called
        body = route.calls.last.request.content
        assert b"uzb" in body
        assert b"language_code" in body
        assert result.text == TRANSCRIPT

    @respx.mock
    async def test_uz_variants_are_normalised_to_uzb(self) -> None:
        """`uz` va `uzn` ham Scribe kutgan `uzb` ga keltiriladi."""
        for variant in ("uz", "uzn", "UZ", "uzb"):
            route = respx.post(STT_URL).mock(return_value=_stt_response())
            await ElevenLabsSTT(api_key="k").transcribe(b"audio", language=variant)
            assert b"uzb" in route.calls.last.request.content, variant
            respx.reset()

    @respx.mock
    async def test_other_language_passes_through(self) -> None:
        """Boshqa tilni so'rash mumkin — o'zbek qattiq qotirilmagan."""
        route = respx.post(STT_URL).mock(return_value=_stt_response())

        await ElevenLabsSTT(api_key="k").transcribe(b"audio", language="rus")

        assert b"rus" in route.calls.last.request.content

    @respx.mock
    async def test_configured_default_language_is_used(self) -> None:
        """`Settings.stt_language` provayderga o'tadi."""
        route = respx.post(STT_URL).mock(return_value=_stt_response())

        await ElevenLabsSTT(api_key="k", default_language="rus").transcribe(b"audio")

        assert b"rus" in route.calls.last.request.content


class TestSttWiring:
    """`get_stt()` sozlamani provayderga uzatadi."""

    def test_stub_without_key(self) -> None:
        get_stt.cache_clear()
        try:
            assert isinstance(_build_stt(_settings()), StubSTT)
        finally:
            get_stt.cache_clear()

    @respx.mock
    async def test_real_provider_uses_settings_language(self) -> None:
        route = respx.post(STT_URL).mock(return_value=_stt_response())
        stt = _build_stt(_settings(elevenlabs_api_key="k", stt_language="uzb"))

        await stt.transcribe(b"audio")

        assert b"uzb" in route.calls.last.request.content


def _build_stt(settings: Settings) -> StubSTT | ElevenLabsSTT:
    """`get_stt()` mantiqini sozlama bilan takrorlaydi (lru_cache'siz)."""
    if settings.elevenlabs_api_key is not None:
        return ElevenLabsSTT(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            default_language=settings.stt_language,
        )
    return StubSTT()


class TestAzureUzbekVoice:
    """Azure — yagona HAQIQIY o'zbek neyron ovozi."""

    def test_voice_names_are_uzbek_neural(self) -> None:
        assert UZBEK_MALE_VOICE == "uz-UZ-SardorNeural"
        assert UZBEK_FEMALE_VOICE == "uz-UZ-MadinaNeural"

    def test_requires_both_key_and_region(self) -> None:
        """Region endpoint URL'ining qismi — kalit yolg'iz yetmaydi."""
        assert AzureTTS(api_key="k", region="").is_configured is False
        assert AzureTTS(api_key=None, region="westeurope").is_configured is False
        assert AzureTTS(api_key="k", region="westeurope").is_configured is True

    def test_ssml_escapes_xml_characters(self) -> None:
        """Javobdagi `&` yoki `<` SSML'ni buzmasligi kerak.

        Aks holda Azure 400 qaytaradi va ovoz javobi jimgina yo'qoladi.
        """
        ssml = build_ssml('Narx < 100 so\'m & "arzon"', voice=UZBEK_MALE_VOICE)

        assert "&lt;" in ssml
        assert "&amp;" in ssml
        assert "< 100" not in ssml

    def test_ssml_carries_uzbek_locale_and_voice(self) -> None:
        ssml = build_ssml("Salom", voice=UZBEK_MALE_VOICE)
        assert "uz-UZ" in ssml
        assert UZBEK_MALE_VOICE in ssml

    @respx.mock
    async def test_synthesize_returns_ogg_opus(self) -> None:
        """Telegram voice note bug fix: Azure endi OGG/OPUS qaytaradi.

        Ilgari bu test `audio_format == "mp3"` ni qulflardi — ya'ni
        bug'ning O'ZINI. Telegram `sendVoice` faqat OPUS bilan kodlangan
        OGG'ni voice note deb qabul qiladi; MP3 musiqa pleyeri bubble'ida
        chiqardi (ega ko'rgan xatti-harakat)."""
        respx.post(AZURE_URL).mock(return_value=httpx.Response(200, content=b"OggSfake"))

        result = await AzureTTS(api_key="k", region="westeurope").synthesize("Salom")

        assert result.audio_format == "ogg"
        assert result.audio_data == b"OggSfake"

    @respx.mock
    async def test_requests_opus_output_format_from_azure(self) -> None:
        """Azure'ga AYNAN OPUS so'rovi ketishini qulflaydi.

        Bu `audio_format` yorlig'idan alohida tekshiruv: yorliq "ogg"
        bo'lib, so'rov esa MP3 so'rasa — baytlar baribir MP3 bo'lardi va
        Telegram yana musiqa ko'rsatardi."""
        route = respx.post(AZURE_URL).mock(return_value=httpx.Response(200, content=b"OggS"))

        await AzureTTS(api_key="k", region="westeurope").synthesize("Salom")

        fmt = route.calls[0].request.headers["X-Microsoft-OutputFormat"]
        assert "opus" in fmt, f"OPUS so'ralmadi: {fmt}"
        assert "mp3" not in fmt

    @respx.mock
    async def test_http_error_is_reported_not_swallowed(self) -> None:
        """Ovoz jimgina yo'qolmaydi — chaqiruvchi xabar bera olsin."""
        respx.post(AZURE_URL).mock(return_value=httpx.Response(401))

        with pytest.raises(RuntimeError, match="401"):
            await AzureTTS(api_key="k", region="westeurope").synthesize("Salom")

    async def test_unconfigured_raises_clear_message(self) -> None:
        with pytest.raises(RuntimeError, match="ZET_AZURE_SPEECH"):
            await AzureTTS().synthesize("Salom")


class TestTtsSelection:
    """Tanlov tartibi: Azure → ElevenLabs → Stub."""

    def _build(self, settings: Settings) -> object:
        if settings.azure_speech_key is not None and settings.azure_speech_region:
            return AzureTTS(
                api_key=settings.azure_speech_key.get_secret_value(),
                region=settings.azure_speech_region,
                voice=settings.azure_voice,
            )
        if settings.elevenlabs_api_key is not None:
            return ElevenLabsTTS(api_key=settings.elevenlabs_api_key.get_secret_value())
        return StubTTS()

    def test_azure_preferred_over_elevenlabs(self) -> None:
        """Azure'da native o'zbek bor — u aksentli ElevenLabs'dan ustun."""
        tts = self._build(
            _settings(
                azure_speech_key="a",
                azure_speech_region="westeurope",
                elevenlabs_api_key="e",
            )
        )
        assert isinstance(tts, AzureTTS)

    def test_elevenlabs_is_the_fallback(self) -> None:
        """Azure yo'q — ovoz butunlay yo'qolgandan ko'ra aksentli bo'lgani ma'qul."""
        assert isinstance(self._build(_settings(elevenlabs_api_key="e")), ElevenLabsTTS)

    def test_azure_key_without_region_falls_back(self) -> None:
        """Yarim sozlangan Azure ishlatilmaydi — u chaqiruvda yiqilardi."""
        tts = self._build(_settings(azure_speech_key="a", elevenlabs_api_key="e"))
        assert isinstance(tts, ElevenLabsTTS)

    def test_stub_when_nothing_configured(self) -> None:
        assert isinstance(self._build(_settings()), StubTTS)

    def test_get_tts_is_cached_singleton(self) -> None:
        get_tts.cache_clear()
        try:
            assert get_tts() is get_tts()
        finally:
            get_tts.cache_clear()
