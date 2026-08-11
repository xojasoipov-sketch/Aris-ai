"""Ovoz tizimi — STT va TTS (Bo'lim 5).

STT: faster-whisper yoki stub (test/dev uchun)
TTS: Piper (lokal) yoki stub

Bog'liq qarorlar:
    V-18 — Ovoz birinchi darajali kirish
    ADR-0006 — lokal modellar T0 ga kiradi ($0)
    ADR-0007 — lokal birinchi (STT/TTS lokal)
"""

from zet.voice.stt import STTProvider, STTResult, StubSTT
from zet.voice.tts import StubTTS, TTSProvider, TTSResult

__all__ = [
    "STTProvider",
    "STTResult",
    "StubSTT",
    "StubTTS",
    "TTSProvider",
    "TTSResult",
]
