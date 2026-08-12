"""ElevenLabs STT/TTS testlari — respx bilan real HTTP mock.

Bo'lim 5 (V-18) — telefon orqali ovozli xabar to'liq ishlashi uchun
tekshiriladigan uch narsa:
    1. Kalit yo'q → xato (StubSTT/StubTTS orqaga moslik chaqiruvchida)
    2. Muvaffaqiyatli javob → to'g'ri parse (o'zbek matn/audio)
    3. HTTP xatolari → RuntimeError tarqatiladi (ZetBot ushlab qoladi)
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from zet.voice.elevenlabs import ElevenLabsSTT, ElevenLabsTTS

_API_KEY = "xi-fake-key"
_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
_VOICE_ID = "test-voice"
_TTS_URL = f"https://api.elevenlabs.io/v1/text-to-speech/{_VOICE_ID}"


# ── STT (Scribe) ─────────────────────────────────────────────────────


class TestElevenLabsSTT:
    def test_is_configured_with_key(self) -> None:
        assert ElevenLabsSTT(api_key=_API_KEY).is_configured is True

    def test_is_not_configured_without_key(self) -> None:
        assert ElevenLabsSTT().is_configured is False

    async def test_missing_key_raises(self) -> None:
        stt = ElevenLabsSTT()
        with pytest.raises(RuntimeError, match="kalit"):
            await stt.transcribe(b"audio")

    @respx.mock
    async def test_transcribe_success(self) -> None:
        respx.post(_STT_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "text": "Salom, bugun qanday reja bor?",
                    "language_code": "uzn",
                    "duration_seconds": 2.5,
                    "words": [
                        {"text": "Salom", "logprob": -0.1},
                        {"text": "bugun", "logprob": -0.2},
                    ],
                },
            )
        )
        stt = ElevenLabsSTT(api_key=_API_KEY)
        result = await stt.transcribe(b"ogg-bytes", audio_format="ogg", language="uz")

        assert result.text == "Salom, bugun qanday reja bor?"
        assert result.language == "uzn"
        assert result.duration_s == 2.5
        assert 0.0 < result.confidence <= 1.0

    @respx.mock
    async def test_sends_correct_multipart_and_lang(self) -> None:
        route = respx.post(_STT_URL).mock(return_value=httpx.Response(200, json={"text": "test"}))
        stt = ElevenLabsSTT(api_key=_API_KEY)
        await stt.transcribe(b"data", audio_format="ogg", language="uz")

        request = route.calls[0].request
        assert request.headers["xi-api-key"] == _API_KEY
        # multipart body: model_id va language_code=uzb ('uz' → 'uzb').
        # Ilgari bu yerda 'uzn' kutilardi — lekin Scribe uni RAD ETADI
        # (`Invalid language code received: 'uzn'`), ya'ni test xato
        # xatti-harakatni qulflab turgan edi. Z43 da tuzatildi.
        body = request.content
        assert b"scribe_v1" in body
        assert b"uzb" in body
        assert b"audio.ogg" in body

    @respx.mock
    async def test_uzbek_forced_when_language_omitted(self) -> None:
        """Til berilmasa AVTOMATIK ANIQLASH emas — o'zbek majburlanadi.

        Ilgari bu test aksini talab qilardi ("language_code qo'shilmaydi").
        Jonli sinov ko'rsatdiki, avtomatik rejimda Scribe o'zbek nutqini
        ozarbayjoncha deb o'qiydi va matn butunlay buziladi. Telegram
        handler tilsiz chaqiradi — ya'ni aynan shu yo'l buzuq edi.
        """
        route = respx.post(_STT_URL).mock(
            return_value=httpx.Response(200, json={"text": "hi", "language_code": "uzb"})
        )
        stt = ElevenLabsSTT(api_key=_API_KEY)
        await stt.transcribe(b"data")

        body = route.calls[0].request.content
        assert b"language_code" in body
        assert b"uzb" in body

    @respx.mock
    async def test_http_error_raises_runtime_error(self) -> None:
        respx.post(_STT_URL).mock(return_value=httpx.Response(401, json={"detail": "invalid key"}))
        stt = ElevenLabsSTT(api_key="wrong")
        with pytest.raises(RuntimeError, match="401"):
            await stt.transcribe(b"data")

    @respx.mock
    async def test_network_error_raises_runtime_error(self) -> None:
        respx.post(_STT_URL).mock(side_effect=httpx.ConnectError("no network"))
        stt = ElevenLabsSTT(api_key=_API_KEY)
        with pytest.raises(RuntimeError, match="tarmoq"):
            await stt.transcribe(b"data")

    async def test_aclose_owned_client(self) -> None:
        stt = ElevenLabsSTT(api_key=_API_KEY)
        _ = stt._get_client()  # ichki klient yaratiladi
        await stt.aclose()

    async def test_aclose_external_client_not_closed(self) -> None:
        client = httpx.AsyncClient()
        stt = ElevenLabsSTT(api_key=_API_KEY, client=client)
        await stt.aclose()
        assert not client.is_closed
        await client.aclose()


# ── TTS (Multilingual v2) ────────────────────────────────────────────


class TestElevenLabsTTS:
    def test_is_configured_with_key(self) -> None:
        assert ElevenLabsTTS(api_key=_API_KEY).is_configured is True

    def test_is_not_configured_without_key(self) -> None:
        assert ElevenLabsTTS().is_configured is False

    async def test_missing_key_raises(self) -> None:
        with pytest.raises(RuntimeError, match="kalit"):
            await ElevenLabsTTS().synthesize("Salom")

    @respx.mock
    async def test_synthesize_success(self) -> None:
        fake_mp3 = b"ID3\x04\x00" + b"\x00" * 100
        respx.post(_TTS_URL).mock(
            return_value=httpx.Response(
                200, content=fake_mp3, headers={"content-type": "audio/mpeg"}
            )
        )
        tts = ElevenLabsTTS(api_key=_API_KEY, voice_id=_VOICE_ID)
        result = await tts.synthesize("Salom, dunyo!")

        assert result.audio_data == fake_mp3
        assert result.audio_format == "mp3"
        assert result.text == "Salom, dunyo!"

    @respx.mock
    async def test_sends_correct_body_and_no_language_code(self) -> None:
        """`language_code` ATAYLAB uzatilmaydi — o'zbek uchun API rasmiy
        cheklovini aylanib o'tish (docstring'ga qarang)."""
        import json

        route = respx.post(_TTS_URL).mock(return_value=httpx.Response(200, content=b"mp3"))
        tts = ElevenLabsTTS(api_key=_API_KEY, voice_id=_VOICE_ID)
        await tts.synthesize("Salom", language="uz")

        request = route.calls[0].request
        assert request.headers["xi-api-key"] == _API_KEY
        body = json.loads(request.content)
        assert body["text"] == "Salom"
        assert body["model_id"] == "eleven_multilingual_v2"
        # language_code YO'Q — API 'uz' ni rad etadi, model matnni avtomatik tushunadi
        assert "language_code" not in body

    @respx.mock
    async def test_http_error_raises_runtime_error(self) -> None:
        respx.post(_TTS_URL).mock(return_value=httpx.Response(400, json={"detail": "bad text"}))
        tts = ElevenLabsTTS(api_key=_API_KEY, voice_id=_VOICE_ID)
        with pytest.raises(RuntimeError, match="400"):
            await tts.synthesize("test")

    @respx.mock
    async def test_network_error_raises_runtime_error(self) -> None:
        respx.post(_TTS_URL).mock(side_effect=httpx.ConnectError("no network"))
        tts = ElevenLabsTTS(api_key=_API_KEY, voice_id=_VOICE_ID)
        with pytest.raises(RuntimeError, match="tarmoq"):
            await tts.synthesize("test")

    async def test_aclose_owned_client(self) -> None:
        tts = ElevenLabsTTS(api_key=_API_KEY)
        _ = tts._get_client()
        await tts.aclose()


# ── Deps integratsiyasi ──────────────────────────────────────────────


class TestVoiceDeps:
    """`get_stt`/`get_tts` — kalit bor/yo'q holatida to'g'ri turni tanlaydi."""

    def test_stub_when_key_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from zet.api import deps as api_deps
        from zet.config import get_settings
        from zet.voice.stt import StubSTT
        from zet.voice.tts import StubTTS

        monkeypatch.chdir(tmp_path)  # .env dan sizib chiqmasin
        monkeypatch.delenv("ZET_ELEVENLABS_API_KEY", raising=False)
        get_settings.cache_clear()
        api_deps.get_stt.cache_clear()
        api_deps.get_tts.cache_clear()

        try:
            assert isinstance(api_deps.get_stt(), StubSTT)
            assert isinstance(api_deps.get_tts(), StubTTS)
        finally:
            get_settings.cache_clear()
            api_deps.get_stt.cache_clear()
            api_deps.get_tts.cache_clear()

    def test_real_when_key_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from zet.api import deps as api_deps
        from zet.config import get_settings

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ZET_ELEVENLABS_API_KEY", _API_KEY)
        get_settings.cache_clear()
        api_deps.get_stt.cache_clear()
        api_deps.get_tts.cache_clear()

        try:
            assert isinstance(api_deps.get_stt(), ElevenLabsSTT)
            assert isinstance(api_deps.get_tts(), ElevenLabsTTS)
        finally:
            get_settings.cache_clear()
            api_deps.get_stt.cache_clear()
            api_deps.get_tts.cache_clear()
