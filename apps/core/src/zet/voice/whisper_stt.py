"""WhisperSTT — faster-whisper bilan LOKAL, self-hosted transkripsiya.

NEGA. `stt.py` docstring'i buni allaqachon va'da qilgan edi ("WhisperSTT —
faster-whisper bilan lokal transkripsiya, T0, $0") — ega ElevenLabs/Azure
kabi tashqi API'larga to'liq bog'liq bo'lmasdan, o'zbekcha ovozli
xabarlarni GPU'siz, o'z serverida, $0 xarajat bilan tanib olishni
xohladi ("Uzbek ovozini ozimiz yozolmaymizmi ozimiz TTS, STT
yasay olmaymizmi" so'rovi).

MODEL. Runtime'da `faster-whisper` (CTranslate2 — MIT, GPU'siz, int8
kvantlash bilan CPU'da ~6x realtime) `islomov/rubaistt_v2_medium` (Whisper
Medium fine-tune, Apache-2.0, ~475 soat haqiqiy o'zbekcha audio bilan
o'qitilgan, WER~17%) yoki shunga o'xshash CTranslate2 formatiga
convert qilingan checkpoint'ni ishlatadi. Konvertatsiya BU MODULDA
QILINMAYDI (torch/transformers og'ir, hot path uchun mos emas) —
`scripts/prepare_voice_models.py` bir martalik oldindan tayyorlash
skripti orqali amalga oshiriladi (`Dockerfile`dagi `/data/voice-models`
doimiy hajmga).

Fail-open: model yo'li mavjud bo'lmasa yoki model yuklashda xato bo'lsa —
`is_configured = False` (yoki keyingi chaqiruv `RuntimeError`), chaqiruvchi
(`get_stt()`) navbatdagi provayderga (ElevenLabs → Stub) o'tadi — boshqa
"real-vs-stub" naqshlar bilan bir xil (`elevenlabs.py`, `azure_tts.py`).

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali kirish
    ADR-0007 — lokal birinchi
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import structlog

from zet.voice.stt import STTProvider, STTResult

if TYPE_CHECKING:
    from collections.abc import Iterable

log = structlog.get_logger(__name__)


class _Segment(Protocol):
    """`faster_whisper.WhisperModel.transcribe()` qaytaradigan segment shakli."""

    text: str
    avg_logprob: float


class _TranscribeInfo(Protocol):
    """`transcribe()` ikkinchi elementi — audio haqida metama'lumot."""

    language: str
    duration: float


class _WhisperModelLike(Protocol):
    """`faster_whisper.WhisperModel` interfeysining shu yerda ishlatiladigan qismi.

    Test uchun DI nuqtasi — haqiqiy `WhisperModel` (og'ir, GB'larcha
    og'irlik yuklaydi) o'rniga soxta obyekt in'ektsiya qilinadi, xuddi
    `ElevenLabsSTT`ga `httpx.AsyncClient` in'ektsiya qilingani kabi.
    """

    def transcribe(
        self, audio: object, *, language: str | None = None
    ) -> tuple[Iterable[_Segment], _TranscribeInfo]: ...


def _load_whisper_model(model_path: str, *, compute_type: str) -> _WhisperModelLike:
    """`faster_whisper.WhisperModel`ni lazy import qilib yuklaydi.

    Import funksiya ICHIDA — `faster_whisper`/`ctranslate2` og'ir
    kutubxonalar, modul yuklanganda (masalan `StubSTT` bilan ishlayotgan
    test/dev muhitida) shart emas ularni xotiraga tortish.
    """
    from faster_whisper import WhisperModel

    # `cast()` — `faster_whisper`da to'liq mypy stub yo'q
    # (`ignore_missing_imports`), haqiqiy klass bizning tor Protocol
    # interfeysimizga MOS keladi.
    return cast(
        _WhisperModelLike, WhisperModel(model_path, device="cpu", compute_type=compute_type)
    )


class WhisperSTT(STTProvider):
    """faster-whisper orqali LOKAL, self-hosted speech-to-text.

    Model CTranslate2-konvertatsiya qilingan katalog yo'lidan (yoki
    HuggingFace Hub'da CT2 formatida joylashgan repo ID'sidan) yuklanadi.
    Birinchi `transcribe()` chaqiruvida LAZY yuklanadi va keyin xotirada
    saqlanadi (`WhisperModel` konstruktori qimmat — bir marta, so'rov
    boshiga emas).
    """

    def __init__(
        self,
        *,
        model_path: str | None,
        compute_type: str = "int8",
        default_language: str = "uz",
        model: _WhisperModelLike | None = None,
    ) -> None:
        self._model_path = model_path
        self._compute_type = compute_type
        self._default_language = default_language
        self._model = model  # testda DI orqali beriladi

    @property
    def is_configured(self) -> bool:
        """Model yo'li berilgan VA (agar lokal yo'l bo'lsa) diskda mavjudmi.

        HuggingFace Hub repo ID'lari ("/" bor, lekin diskda mavjud emas)
        ham qabul qilinadi — ular runtime'da avtomatik yuklab olinadi.
        Faqat "diskdagi yo'l ko'rinishida-yu lekin yo'q" holat rad etiladi
        (aniq xato konfiguratsiyasi belgisi).
        """
        if self._model is not None:
            return True
        if not self._model_path:
            return False
        path = Path(self._model_path)
        looks_like_local_path = path.is_absolute() or self._model_path.startswith(("./", "../"))
        if looks_like_local_path:
            return path.is_dir()
        return True

    def _get_model(self) -> _WhisperModelLike:
        if self._model is None:
            if not self._model_path:
                raise RuntimeError(
                    "WhisperSTT: model yo'li yo'q — ZET_WHISPER_MODEL_PATH sozlanmagan"
                )
            log.info("whisper_stt.loading_model", model_path=self._model_path)
            self._model = _load_whisper_model(self._model_path, compute_type=self._compute_type)
        return self._model

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "ogg",  # noqa: ARG002 — PyAV konteynerni o'zi aniqlaydi
        language: str | None = None,
    ) -> STTResult:
        """Audio dan matn olish — lokal Whisper modeli orqali (CPU, $0)."""
        try:
            model = self._get_model()
        except RuntimeError:
            raise
        except Exception as exc:
            log.warning("whisper_stt.model_load_failed", error=str(exc))
            raise RuntimeError(f"WhisperSTT: model yuklanmadi: {exc}") from exc

        lang = language or self._default_language
        # PyAV audio bytes'ni fayl sifatida emas, BytesIO orqali qabul
        # qiladi — ffmpeg binar shart emas (faster-whisper ichida bog'liq).
        import io

        audio_stream = io.BytesIO(audio_data)

        try:
            # `WhisperModel.transcribe()` SINXRON (CPU-bound) — event loop'ni
            # bloklamasin uchun alohida threadga o'raladi (ASYNC240).
            segments, info = await asyncio.to_thread(model.transcribe, audio_stream, language=lang)
            segment_list = list(segments)
        except Exception as exc:
            log.warning("whisper_stt.transcribe_failed", error=str(exc))
            raise RuntimeError(f"WhisperSTT transkripsiya xatosi: {exc}") from exc

        text = " ".join(seg.text.strip() for seg in segment_list).strip()
        if segment_list:
            import math

            avg_logprob = sum(seg.avg_logprob for seg in segment_list) / len(segment_list)
            confidence = max(0.0, min(1.0, math.exp(avg_logprob)))
        else:
            confidence = 0.0

        log.info(
            "whisper_stt.transcribed",
            text_length=len(text),
            language=info.language,
            duration_s=round(info.duration, 2),
            confidence=round(confidence, 3),
        )
        return STTResult(
            text=text,
            language=info.language or lang,
            confidence=confidence,
            duration_s=float(info.duration),
        )


__all__ = ["WhisperSTT"]
