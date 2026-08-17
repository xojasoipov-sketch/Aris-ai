"""`zet.voice.navoiy_tts.NavoiyTTS` testlari.

GPU serveri BU YERDA YO'Q (haqiqiy CosyVoice2 inference sinalmagan —
`infra/hetzner/navoiy-tts-service/README.md`ga qarang). Testlar HTTP
qatlamini `respx` bilan mock qiladi (xuddi `ElevenLabsSTT`/`AzureTTS`
testlaridagi kabi) va `chunk_text()`ni (sof funksiya, GPU'siz to'liq
sinaladigan) mustaqil tekshiradi.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.voice.navoiy_tts import MAX_CHARS_PER_REQUEST, NavoiyTTS, chunk_text

_BASE_URL = "http://gpu-server:8100"
_SYNTH_URL = f"{_BASE_URL}/synthesize"


class TestIsConfigured:
    def test_no_url_not_configured(self) -> None:
        assert NavoiyTTS(base_url=None).is_configured is False

    def test_url_configured(self) -> None:
        assert NavoiyTTS(base_url=_BASE_URL).is_configured is True


class TestSynthesize:
    async def test_missing_url_raises(self) -> None:
        with pytest.raises(RuntimeError, match="manzil yo'q"):
            await NavoiyTTS(base_url=None).synthesize("Salom")

    @respx.mock
    async def test_synthesize_success(self) -> None:
        fake_ogg = b"OggS\x00\x02" + b"\x00" * 100
        respx.post(_SYNTH_URL).mock(
            return_value=httpx.Response(
                200, content=fake_ogg, headers={"content-type": "audio/ogg"}
            )
        )
        tts = NavoiyTTS(base_url=_BASE_URL)
        result = await tts.synthesize("Salom, dunyo!")

        assert result.audio_data == fake_ogg
        assert result.audio_format == "ogg"
        assert result.text == "Salom, dunyo!"

    @respx.mock
    async def test_text_normalized_before_sending(self) -> None:
        """Raqam/sana/vaqt/kirill matnga uzatishdan OLDIN tozalanadi."""
        route = respx.post(_SYNTH_URL).mock(return_value=httpx.Response(200, content=b"OggS"))
        tts = NavoiyTTS(base_url=_BASE_URL)

        await tts.synthesize("Sizda 3 ta xabar bor")

        import json

        body = json.loads(route.calls.last.request.content)
        assert body["text"] == "Sizda uch ta xabar bor"

    @respx.mock
    async def test_http_error_raises_runtime_error(self) -> None:
        respx.post(_SYNTH_URL).mock(return_value=httpx.Response(500, json={"detail": "GPU xato"}))
        tts = NavoiyTTS(base_url=_BASE_URL)
        with pytest.raises(RuntimeError, match="500"):
            await tts.synthesize("test")

    @respx.mock
    async def test_network_error_raises_runtime_error(self) -> None:
        respx.post(_SYNTH_URL).mock(side_effect=httpx.ConnectError("no route to host"))
        tts = NavoiyTTS(base_url=_BASE_URL)
        with pytest.raises(RuntimeError, match="tarmoq"):
            await tts.synthesize("test")

    @respx.mock
    async def test_long_text_split_into_multiple_requests(self) -> None:
        """Uzun matn bir nechta so'rovga bo'linadi, natijalar birlashtiriladi."""
        route = respx.post(_SYNTH_URL).mock(
            side_effect=[
                httpx.Response(200, content=b"AAA"),
                httpx.Response(200, content=b"BBB"),
            ]
        )
        long_text = ("Bu gap juda uzun. " * 200).strip()
        assert len(long_text) > MAX_CHARS_PER_REQUEST

        tts = NavoiyTTS(base_url=_BASE_URL)
        result = await tts.synthesize(long_text)

        assert route.call_count == 2
        assert result.audio_data == b"AAABBB"

    @respx.mock
    async def test_empty_text_returns_empty_audio_without_request(self) -> None:
        route = respx.post(_SYNTH_URL).mock(return_value=httpx.Response(200, content=b"x"))
        tts = NavoiyTTS(base_url=_BASE_URL)

        result = await tts.synthesize("   ")

        assert result.audio_data == b""
        assert not route.called

    async def test_aclose_owned_client(self) -> None:
        tts = NavoiyTTS(base_url=_BASE_URL)
        _ = tts._get_client()
        await tts.aclose()

    async def test_aclose_external_client_not_closed(self) -> None:
        client = httpx.AsyncClient()
        tts = NavoiyTTS(base_url=_BASE_URL, client=client)
        await tts.aclose()
        assert not client.is_closed
        await client.aclose()


class TestChunkText:
    """Sof funksiya — GPU'siz to'liq sinaladi."""

    def test_short_text_single_chunk(self) -> None:
        assert chunk_text("Salom") == ["Salom"]

    def test_empty_text_no_chunks(self) -> None:
        assert chunk_text("") == []

    def test_splits_at_sentence_boundary(self) -> None:
        text = ("Birinchi gap. " * 200).strip()
        chunks = chunk_text(text, max_chars=100)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)
        # Hech qanday belgi yo'qolmagan — birlashtirilsa asl matn tiklanadi
        # (bo'shliqlar normalizatsiyasidan tashqari).
        assert "".join(chunks).replace(" ", "") == text.replace(" ", "")

    def test_single_word_longer_than_limit_not_lost(self) -> None:
        """Hech qachon matn KESIB TASHLANMAYDI — so'z chegarasida bo'linadi."""
        text = "qisqa " + ("a" * 50) + " davomi shu yerda"
        chunks = chunk_text(text, max_chars=20)
        assert "".join(chunks).replace(" ", "") == text.replace(" ", "")

    def test_nothing_exceeds_max_chars(self) -> None:
        text = "Bu " * 500
        chunks = chunk_text(text, max_chars=50)
        assert all(len(c) <= 50 for c in chunks)
