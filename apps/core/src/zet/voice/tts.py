"""Text-to-Speech — matndan ovozga o'girish.

Provider interfeysi:
    TTSProvider.synthesize(text, language) → TTSResult

Implementatsiyalar:
    StubTTS — test/dev uchun (bo'sh audio qaytaradi)
    PiperTTS — Piper bilan lokal TTS (T0, $0)

Bo'lim 5 lean: StubTTS. Keyingi bo'limlarda PiperTTS qo'shiladi.

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali
    ADR-0006 — lokal TTS $0
    ADR-0007 — lokal birinchi
"""

from __future__ import annotations

import abc

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class TTSResult(BaseModel, frozen=True):
    """TTS natijasi."""

    audio_data: bytes
    """Generatsiya qilingan audio baytlari."""

    audio_format: str = "ogg"
    """Audio formati."""

    duration_s: float = Field(default=0.0, ge=0.0)
    """Audio davomiyligi (soniya)."""

    text: str = ""
    """Asl matn."""


class TTSProvider(abc.ABC):
    """Text-to-Speech provayder interfeysi."""

    @abc.abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        language: str = "uz",
    ) -> TTSResult:
        """Matndan ovoz generatsiya qilish.

        Args:
            text: o'qiladigan matn
            language: til kodi

        Returns:
            TTSResult — audio natijasi
        """


class StubTTS(TTSProvider):
    """Test/dev uchun stub TTS — bo'sh audio qaytaradi.

    Bo'lim 5 lean: haqiqiy TTS o'rniga stub.
    """

    async def synthesize(
        self,
        text: str,
        *,
        language: str = "uz",
    ) -> TTSResult:
        """Stub TTS — bo'sh audio qaytaradi."""
        log.info(
            "tts.stub_synthesize",
            text_length=len(text),
            language=language,
        )
        # Minimal OGG header (test uchun)
        stub_audio = b"OggS" + b"\x00" * 28
        return TTSResult(
            audio_data=stub_audio,
            audio_format="ogg",
            duration_s=0.0,
            text=text,
        )
