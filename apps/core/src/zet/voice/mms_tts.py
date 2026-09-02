"""MmsTTS — Meta MMS-TTS bilan LOKAL, self-hosted ovoz sintezi.

NEGA. Ega tashqi API'larga (ElevenLabs/Azure) bog'liq bo'lmasdan, o'zbekcha
matnni GPU'siz, o'z serverida, $0 xarajat bilan ovozga aylantirishni
xohladi. GitHub/HuggingFace tadqiqotida CPU'da ishlaydigan, tayyor
o'zbekcha ovoz og'irligi bilan keladigan yagona amaliy variant —
`facebook/mms-tts-uzb-script_cyrillic` (Meta Massively Multilingual
Speech loyihasi, VITS arxitekturasi, 36M parametr).

LITSENZIYA OGOHLANTIRISHI (yashirilmaydi) — `facebook/mms-tts-uzb-*`
**CC-BY-NC-4.0** bilan tarqatiladi, ya'ni **FAQAT NOTIJORAT** foydalanish
uchun ruxsat etilgan. ZET `pyproject.toml`da `LicenseRef-Proprietary`
(mulkiy) — agar ZET kelajakda pullik/tijorat mahsulotga aylansa, bu
haqiqiy yuridik ziddiyat va tekshirilishi/almashtirilishi SHART (masalan
Piper'da shaxsiy o'zbek ovozini o'qitish orqali, `TRAINING.md`). Shaxsiy/
ichki foydalanish uchun bu cheklov odatda muammo emas, lekin bu yuridik
maslahat EMAS. Chaqiruvchi kod (`get_tts()`) buni FAOL ravishda bloklamaydi
(bu biznes/yuridik qaror, kodning ishi emas) — faqat shu yerda va
`config.py`da ochiq hujjatlashtiriladi.

KIRILL TALABI. Model FAQAT kirill skriptni tushunadi — ZET esa lotin
yozuvida ishlaydi. Shuning uchun `synthesize()` matnni avval
`zet.voice.transliterate.to_cyrillic()` orqali o'giradi.

AUDIO FORMAT. VITS chiqishi xom PCM (float32, model sampling rate — MMS-TTS
uchun odatda 16 kHz). Telegram `sendVoice` OGG/OPUS talab qiladi (boshqa
provayderlar bilan bir xil — `elevenlabs.py`/`azure_tts.py`dagi izohga
qarang), shuning uchun PCM `PyAV` (`av` paketi, allaqachon
`faster-whisper`ning tranzitiv bog'liqligi) orqali OGG/Opus konteyneriga
kodlanadi — tashqi `ffmpeg` binari SHART EMAS (PyAV o'zining statik
build'ida libopus bilan keladi, sinovda tasdiqlangan).

Fail-open: model yo'li yo'q/topilmasa — `is_configured = False`, chaqiruvchi
navbatdagi provayderga (Azure → ElevenLabs → Stub) o'tadi.

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali
    ADR-0006 — lokal TTS $0
    ADR-0007 — lokal birinchi
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

import structlog

from zet.voice.transliterate import to_cyrillic
from zet.voice.tts import TTSProvider, TTSResult

if TYPE_CHECKING:
    import numpy as np

log = structlog.get_logger(__name__)

# Opus kodeki faqat ma'lum diskretlash chastotalarini qabul qiladi
# (RFC 6716): 8000/12000/16000/24000/48000 Hz. MMS-TTS VITS modeli
# odatda 16000 Hz'da chiqaradi — bu ro'yxatda bor, ya'ni QAYTA
# DISKRETLASH (resample) SHART EMAS, to'g'ridan-to'g'ri kodlash mumkin.
_OPUS_NATIVE_RATES = frozenset({8000, 12000, 16000, 24000, 48000})


class _VitsOutput(Protocol):
    """`VitsModel.__call__()` qaytaradigan natija shakli (shu yerda kerak qismi)."""

    waveform: Any  # torch.Tensor, shape (1, n_samples) — `transformers` stub'siz


class _TokenizerLike(Protocol):
    def __call__(self, text: str, *, return_tensors: str) -> dict[str, object]: ...


class _VitsModelLike(Protocol):
    """`transformers.VitsModel`ning shu yerda ishlatiladigan qismi.

    Test uchun DI nuqtasi — haqiqiy model (GB'larcha og'irlik) o'rniga
    soxta obyekt in'ektsiya qilinadi.
    """

    config: Any  # .sampling_rate maydoni bor — `transformers` stub'siz

    def __call__(self, **inputs: object) -> _VitsOutput: ...


def _load_mms_model(model_path: str) -> tuple[_VitsModelLike, _TokenizerLike]:
    """`transformers.VitsModel`/`AutoTokenizer`ni lazy import qilib yuklaydi.

    Import funksiya ICHIDA — `transformers`/`torch` og'ir, `StubTTS` bilan
    ishlayotgan test/dev muhitida xotiraga tortish shart emas. `cast()` —
    `transformers`da to'liq mypy stub yo'q (`ignore_missing_imports`),
    haqiqiy klasslar bizning tor Protocol interfeysimizga MOS keladi.
    """
    from transformers import AutoTokenizer, VitsModel

    model = VitsModel.from_pretrained(model_path)
    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model.eval()  # type: ignore[no-untyped-call]  # `transformers` stub'siz
    return cast(_VitsModelLike, model), cast(_TokenizerLike, tokenizer)


def _synthesize_sync(
    model: _VitsModelLike, tokenizer: _TokenizerLike, cyrillic_text: str
) -> tuple[np.ndarray, int]:
    """Sinxron (CPU-bound) VITS forward pass — `asyncio.to_thread()` ichida chaqiriladi."""
    import torch

    inputs = tokenizer(cyrillic_text, return_tensors="pt")
    with torch.no_grad():
        output = model(**inputs)
    waveform = output.waveform.squeeze().cpu().numpy()
    sample_rate = int(model.config.sampling_rate)
    return cast("np.ndarray", waveform), sample_rate


def _pcm_to_ogg_opus(samples: np.ndarray, sample_rate: int) -> bytes:
    """Xom PCM (float32, [-1, 1]) massivini OGG/Opus baytlariga kodlaydi.

    Faqat Opus'ning tabiiy chastotalarida ishlaydi (`_OPUS_NATIVE_RATES`)
    — MMS-TTS 16 kHz bergani uchun amalda resample kerak bo'lmaydi.
    Boshqa chastota kelsa aniq xato bilan to'xtaydi (jimgina buzuq audio
    berish o'rniga — "hech narsa yo'q" xato ekani aniq, "buzuq ovoz"dan
    yaxshiroq).
    """
    import numpy as np

    if sample_rate not in _OPUS_NATIVE_RATES:
        raise RuntimeError(
            f"MmsTTS: model {sample_rate} Hz da chiqardi — Opus buni to'g'ridan-to'g'ri "
            f"qabul qilmaydi (faqat {sorted(_OPUS_NATIVE_RATES)}), resample qo'llab-"
            f"quvvatlanmagan"
        )

    import av

    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=sample_rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(samples.reshape(1, -1), dtype=np.float32),
            format="flt",
            layout="mono",
        )
        frame.sample_rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


class MmsTTS(TTSProvider):
    """Meta MMS-TTS orqali LOKAL, self-hosted text-to-speech (o'zbek, kirill).

    Litsenziya cheklovi (CC-BY-NC-4.0) uchun modul docstring'iga qarang.
    """

    def __init__(
        self,
        *,
        model_path: str | None,
        model: _VitsModelLike | None = None,
        tokenizer: _TokenizerLike | None = None,
    ) -> None:
        self._model_path = model_path
        self._model = model  # testda DI orqali beriladi
        self._tokenizer = tokenizer

    @property
    def is_configured(self) -> bool:
        if self._model is not None:
            return True
        if not self._model_path:
            return False
        path = Path(self._model_path)
        looks_like_local_path = path.is_absolute() or self._model_path.startswith(("./", "../"))
        if looks_like_local_path:
            return path.is_dir()
        return True

    def _get_model(self) -> tuple[_VitsModelLike, _TokenizerLike]:
        if self._model is None or self._tokenizer is None:
            if not self._model_path:
                raise RuntimeError("MmsTTS: model yo'li yo'q — ZET_MMS_TTS_MODEL_PATH sozlanmagan")
            log.info("mms_tts.loading_model", model_path=self._model_path)
            self._model, self._tokenizer = _load_mms_model(self._model_path)
        return self._model, self._tokenizer

    async def synthesize(self, text: str, *, language: str = "uz") -> TTSResult:  # noqa: ARG002
        """Matndan OGG/Opus audio (Telegram voice note) — lokal MMS-TTS orqali."""
        try:
            model, tokenizer = self._get_model()
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("mms_tts.model_load_failed", error=str(exc))
            raise RuntimeError(f"MmsTTS: model yuklanmadi: {exc}") from exc

        cyrillic_text = to_cyrillic(text)

        try:
            waveform, sample_rate = await asyncio.to_thread(
                _synthesize_sync, model, tokenizer, cyrillic_text
            )
            audio_bytes = await asyncio.to_thread(_pcm_to_ogg_opus, waveform, sample_rate)
        except Exception as exc:
            log.warning("mms_tts.synthesize_failed", error=str(exc))
            raise RuntimeError(f"MmsTTS sintez xatosi: {exc}") from exc

        duration_s = float(len(waveform)) / float(sample_rate) if sample_rate else 0.0
        log.info(
            "mms_tts.synthesized",
            text_length=len(text),
            audio_size=len(audio_bytes),
            duration_s=round(duration_s, 2),
        )
        return TTSResult(
            audio_data=audio_bytes,
            audio_format="ogg",
            duration_s=duration_s,
            text=text,
        )


__all__ = ["MmsTTS"]
