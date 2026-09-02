"""`zet.voice.whisper_stt.WhisperSTT` testlari.

Haqiqiy `faster_whisper.WhisperModel` OG'IR (yuz MB'lardan GB'gacha model
og'irligi yuklaydi) — shuning uchun testlar DI (`model=` konstruktor
parametri) orqali SOXTA model in'ektsiya qiladi, xuddi `ElevenLabsSTT`ga
`httpx.AsyncClient` in'ektsiya qilingani kabi. Bu naqsh mock HTTP javob
bilan bir xil maqsadga xizmat qiladi: tashqi og'ir bog'liqliksiz, tez va
deterministik tekshirish.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.voice.whisper_stt import WhisperSTT


class _FakeSegment:
    def __init__(self, text: str, avg_logprob: float) -> None:
        self.text = text
        self.avg_logprob = avg_logprob


class _FakeInfo:
    def __init__(self, language: str, duration: float) -> None:
        self.language = language
        self.duration = duration


class _FakeWhisperModel:
    """`faster_whisper.WhisperModel.transcribe()`ning soxta implementatsiyasi."""

    def __init__(
        self, segments: list[_FakeSegment], info: _FakeInfo, *, raise_error: bool = False
    ) -> None:
        self._segments = segments
        self._info = info
        self._raise_error = raise_error
        self.last_call: dict[str, object] = {}

    def transcribe(
        self, audio: object, *, language: str | None = None
    ) -> tuple[list[_FakeSegment], _FakeInfo]:
        self.last_call = {"audio": audio, "language": language}
        if self._raise_error:
            raise RuntimeError("model portlab ketdi")
        return self._segments, self._info


class TestIsConfigured:
    def test_no_path_not_configured(self) -> None:
        assert WhisperSTT(model_path=None).is_configured is False

    def test_missing_local_dir_not_configured(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        assert WhisperSTT(model_path=str(missing)).is_configured is False

    def test_existing_local_dir_configured(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "whisper-uz-ct2"
        model_dir.mkdir()
        assert WhisperSTT(model_path=str(model_dir)).is_configured is True

    def test_hf_hub_repo_id_configured_even_if_not_on_disk(self) -> None:
        """ "/" bor repo ID — HF Hub'dan avtomatik yuklanadi, diskda bo'lishi shart emas."""
        assert WhisperSTT(model_path="islomov/rubaistt_v2_medium").is_configured is True

    def test_injected_model_always_configured(self) -> None:
        fake = _FakeWhisperModel([], _FakeInfo("uz", 0.0))
        assert WhisperSTT(model_path=None, model=fake).is_configured is True


class TestTranscribe:
    async def test_missing_model_path_raises(self) -> None:
        stt = WhisperSTT(model_path=None)
        with pytest.raises(RuntimeError, match="model yo'li yo'q"):
            await stt.transcribe(b"audio")

    async def test_transcribe_success_joins_segments(self) -> None:
        fake = _FakeWhisperModel(
            [_FakeSegment(" Salom, ", -0.1), _FakeSegment("dunyo!", -0.2)],
            _FakeInfo("uz", 2.5),
        )
        stt = WhisperSTT(model_path=None, model=fake)

        result = await stt.transcribe(b"ogg-bytes", audio_format="ogg", language="uz")

        assert result.text == "Salom, dunyo!"
        assert result.language == "uz"
        assert result.duration_s == 2.5
        assert 0.0 < result.confidence <= 1.0

    async def test_default_language_used_when_omitted(self) -> None:
        fake = _FakeWhisperModel([_FakeSegment("test", 0.0)], _FakeInfo("uz", 1.0))
        stt = WhisperSTT(model_path=None, default_language="uz", model=fake)

        await stt.transcribe(b"audio")

        assert fake.last_call["language"] == "uz"

    async def test_explicit_language_overrides_default(self) -> None:
        fake = _FakeWhisperModel([_FakeSegment("test", 0.0)], _FakeInfo("ru", 1.0))
        stt = WhisperSTT(model_path=None, default_language="uz", model=fake)

        await stt.transcribe(b"audio", language="ru")

        assert fake.last_call["language"] == "ru"

    async def test_empty_segments_gives_empty_text_and_zero_confidence(self) -> None:
        fake = _FakeWhisperModel([], _FakeInfo("uz", 0.0))
        stt = WhisperSTT(model_path=None, model=fake)

        result = await stt.transcribe(b"silence")

        assert result.text == ""
        assert result.confidence == 0.0

    async def test_model_transcribe_error_raises_runtime_error(self) -> None:
        fake = _FakeWhisperModel([], _FakeInfo("uz", 0.0), raise_error=True)
        stt = WhisperSTT(model_path=None, model=fake)

        with pytest.raises(RuntimeError, match="transkripsiya xatosi"):
            await stt.transcribe(b"audio")

    async def test_model_loaded_lazily_once(self, tmp_path: Path) -> None:
        """Model FAQAT birinchi `transcribe()`da yuklanadi, keyin qayta ishlatiladi."""
        model_dir = tmp_path / "whisper-uz-ct2"
        model_dir.mkdir()
        load_calls: list[str] = []

        def fake_loader(path: str, *, compute_type: str) -> _FakeWhisperModel:
            load_calls.append(path)
            return _FakeWhisperModel([_FakeSegment("hi", 0.0)], _FakeInfo("uz", 1.0))

        import zet.voice.whisper_stt as whisper_stt_module

        stt = WhisperSTT(model_path=str(model_dir))
        original = whisper_stt_module._load_whisper_model
        whisper_stt_module._load_whisper_model = fake_loader  # type: ignore[assignment]
        try:
            await stt.transcribe(b"audio1")
            await stt.transcribe(b"audio2")
        finally:
            whisper_stt_module._load_whisper_model = original

        assert len(load_calls) == 1  # ikkinchi chaqiruvda QAYTA yuklanmadi
