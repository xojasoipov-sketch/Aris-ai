"""`zet.voice.mms_tts.MmsTTS` testlari.

Haqiqiy `transformers.VitsModel` OG'IR — testlar DI (`model=`/`tokenizer=`
konstruktor parametrlari) orqali soxta obyekt in'ektsiya qiladi, xuddi
`WhisperSTT`/`ElevenLabsTTS` testlaridagi kabi.

`_pcm_to_ogg_opus()` ESA REAL sinaladi — `av` (PyAV) yengil va tez, xom
PCM'dan haqiqiy OGG/Opus baytlarini ishlab chiqarishi to'g'ridan-to'g'ri
tekshiriladi (mock emas — bu funksiyaning butun vazifasi audio
kodlash, uni soxtalashtirish hech narsani sinamas edi).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from zet.voice.mms_tts import MmsTTS, _pcm_to_ogg_opus


class _FakeConfig:
    def __init__(self, sampling_rate: int) -> None:
        self.sampling_rate = sampling_rate


class _FakeOutput:
    def __init__(self, waveform: object) -> None:
        self.waveform = waveform


class _FakeTorchTensor:
    """`torch.Tensor`ning `.squeeze().cpu().numpy()` zanjiri uchun soxta obyekt."""

    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def squeeze(self) -> _FakeTorchTensor:
        return _FakeTorchTensor(np.squeeze(self._array))

    def cpu(self) -> _FakeTorchTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self._array


class _FakeVitsModel:
    def __init__(self, sample_rate: int = 16000, n_samples: int = 8000) -> None:
        self.config = _FakeConfig(sample_rate)
        self._n_samples = n_samples
        self.last_inputs: dict[str, object] = {}

    def __call__(self, **inputs: object) -> _FakeOutput:
        self.last_inputs = inputs
        silence = np.zeros(self._n_samples, dtype=np.float32)
        return _FakeOutput(_FakeTorchTensor(silence))


class _FakeTokenizer:
    def __init__(self) -> None:
        self.last_text: str | None = None

    def __call__(self, text: str, *, return_tensors: str) -> dict[str, object]:
        self.last_text = text
        return {"input_ids": [1, 2, 3]}


class TestIsConfigured:
    def test_no_path_not_configured(self) -> None:
        assert MmsTTS(model_path=None).is_configured is False

    def test_missing_local_dir_not_configured(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        assert MmsTTS(model_path=str(missing)).is_configured is False

    def test_existing_local_dir_configured(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "mms-tts-uz"
        model_dir.mkdir()
        assert MmsTTS(model_path=str(model_dir)).is_configured is True

    def test_injected_model_always_configured(self) -> None:
        tts = MmsTTS(model_path=None, model=_FakeVitsModel(), tokenizer=_FakeTokenizer())
        assert tts.is_configured is True


class TestSynthesize:
    async def test_missing_model_path_raises(self) -> None:
        tts = MmsTTS(model_path=None)
        with pytest.raises(RuntimeError, match="model yo'li yo'q"):
            await tts.synthesize("Salom")

    async def test_synthesize_success_returns_ogg_opus(self) -> None:
        model = _FakeVitsModel(sample_rate=16000, n_samples=16000)
        tts = MmsTTS(model_path=None, model=model, tokenizer=_FakeTokenizer())

        result = await tts.synthesize("Salom, dunyo!")

        assert result.audio_format == "ogg"
        assert result.audio_data[:4] == b"OggS"  # haqiqiy OGG konteyner sarlavhasi
        assert result.duration_s == pytest.approx(1.0)  # 16000 namuna / 16000 Hz
        assert result.text == "Salom, dunyo!"

    async def test_text_is_transliterated_before_tokenizing(self) -> None:
        """MMS-TTS faqat kirill tushunadi — lotin matn kirillga o'girilgan holda tokenizerga ketadi."""
        model = _FakeVitsModel()
        tokenizer = _FakeTokenizer()
        tts = MmsTTS(model_path=None, model=model, tokenizer=tokenizer)

        await tts.synthesize("salom")

        assert tokenizer.last_text == "салом"

    async def test_unsupported_sample_rate_raises(self) -> None:
        """Opus tabiiy chastotalaridan biri bo'lmasa — aniq xato (jimgina buzuq audio emas)."""
        model = _FakeVitsModel(sample_rate=22050, n_samples=1000)
        tts = MmsTTS(model_path=None, model=model, tokenizer=_FakeTokenizer())

        with pytest.raises(RuntimeError, match="sintez xatosi"):
            await tts.synthesize("test")

    async def test_model_loaded_lazily_once(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "mms-tts-uz"
        model_dir.mkdir()
        load_calls: list[str] = []

        def fake_loader(path: str) -> tuple[_FakeVitsModel, _FakeTokenizer]:
            load_calls.append(path)
            return _FakeVitsModel(), _FakeTokenizer()

        import zet.voice.mms_tts as mms_tts_module

        tts = MmsTTS(model_path=str(model_dir))
        original = mms_tts_module._load_mms_model
        mms_tts_module._load_mms_model = fake_loader  # type: ignore[assignment]
        try:
            await tts.synthesize("bir")
            await tts.synthesize("ikki")
        finally:
            mms_tts_module._load_mms_model = original

        assert len(load_calls) == 1


class TestPcmToOggOpus:
    """Real PyAV kodlash — mock emas."""

    def test_produces_valid_ogg_container(self) -> None:
        samples = np.zeros(16000, dtype=np.float32)
        data = _pcm_to_ogg_opus(samples, 16000)
        assert data[:4] == b"OggS"
        assert len(data) > 0

    def test_sine_wave_roundtrips_via_av(self) -> None:
        """Kodlangan audio HAQIQIY dekodlanadigan Opus ekanini tasdiqlaydi."""
        import av

        t = np.linspace(0, 1.0, 16000, endpoint=False, dtype=np.float32)
        samples = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        data = _pcm_to_ogg_opus(samples, 16000)

        import io

        with av.open(io.BytesIO(data), mode="r") as container:
            assert container.streams.audio[0].codec_context.name == "opus"
            total_samples = sum(frame.samples for frame in container.decode(audio=0))
        assert total_samples > 0

    @pytest.mark.parametrize("rate", [8000, 12000, 16000, 24000, 48000])
    def test_all_opus_native_rates_accepted(self, rate: int) -> None:
        samples = np.zeros(rate // 10, dtype=np.float32)
        data = _pcm_to_ogg_opus(samples, rate)
        assert data[:4] == b"OggS"

    def test_unsupported_rate_raises_clear_error(self) -> None:
        with pytest.raises(RuntimeError, match="Opus"):
            _pcm_to_ogg_opus(np.zeros(100, dtype=np.float32), 22050)
