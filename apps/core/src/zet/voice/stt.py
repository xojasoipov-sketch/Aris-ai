"""Speech-to-Text — ovozdan matnga o'girish (V-18).

Provider interfeysi:
    STTProvider.transcribe(audio_bytes, format) → STTResult

Implementatsiyalar:
    StubSTT — test/dev uchun (haqiqiy transkripsiya qilmaydi)
    WhisperSTT — faster-whisper bilan lokal transkripsiya (T0, $0)

Bo'lim 5 lean: StubSTT. Keyingi bo'limlarda WhisperSTT qo'shiladi.
"""

from __future__ import annotations

import abc

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class STTResult(BaseModel, frozen=True):
    """Transkripsiya natijasi."""

    text: str
    """Aniqlangan matn."""

    language: str = "uz"
    """Aniqlangan til."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    """Ishonch darajasi (0.0 — 1.0)."""

    duration_s: float = Field(default=0.0, ge=0.0)
    """Audio davomiyligi (soniya)."""


class STTProvider(abc.ABC):
    """Speech-to-Text provayder interfeysi."""

    @abc.abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "ogg",
        language: str | None = None,
    ) -> STTResult:
        """Audio dan matn olish.

        Args:
            audio_data: audio fayl baytlari
            audio_format: format (ogg, wav, mp3, m4a)
            language: til kodi (None = avtomatik aniqlash)

        Returns:
            STTResult — transkripsiya natijasi
        """


class StubSTT(STTProvider):
    """Test/dev uchun stub STT — haqiqiy transkripsiya qilmaydi.

    Bo'lim 5 lean: haqiqiy whisper o'rniga stub.
    Keyingi bo'limlarda faster-whisper bilan almashtiriladi.
    """

    def __init__(self, default_text: str = "Test ovozli xabar") -> None:
        self._default_text = default_text

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: str = "ogg",
        language: str | None = None,
    ) -> STTResult:
        """Stub transkripsiya — doimo default matn qaytaradi."""
        log.info(
            "stt.stub_transcribe",
            audio_size=len(audio_data),
            format=audio_format,
            language=language or "auto",
        )
        return STTResult(
            text=self._default_text,
            language=language or "uz",
            confidence=1.0,
            duration_s=0.0,
        )
