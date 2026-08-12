"""Ovoz sintezi endpoint'i (Z47).

    POST /api/v1/voice/speak — matndan audio

NEGA KERAK BO'LDI.

ZET'da TTS provayderlari bor edi (Azure — haqiqiy o'zbek neyron
ovozi, ElevenLabs — zaxira), lekin ular FAQAT Telegram oqimida
ishlatilardi. Brauzerdagi interfeys ovozsiz edi: "ikki marta qarsak
chalsam ZET javob bersin" talabini bajarish uchun veb ham TTS'ga
yeta olishi kerak.

Brauzerning o'z `speechSynthesis`i o'zbek tilini deyarli qo'llamaydi
(inglizcha ovoz bilan taxminan o'qiydi), shuning uchun serverdagi
Azure ovozi ustunroq. TTS sozlanmagan bo'lsa 503 qaytadi va frontend
brauzer ovoziga tushadi — jim qolmaydi.

Bog'liq qarorlar:
    V-18 — ovoz birinchi darajali
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from zet.api.deps import get_tts
from zet.voice.tts import StubTTS, TTSProvider

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_TEXT_LENGTH = 500
"""Uzun matn TTS kvotasini tez yeydi va javobni sekinlashtiradi."""


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LENGTH)
    language: str = "uz"


@router.post(
    "/speak",
    responses={
        200: {"content": {"audio/*": {}}, "description": "Sintez qilingan audio"},
        503: {"description": "TTS provayderi sozlanmagan"},
    },
)
async def speak(
    request: SpeakRequest,
    tts: TTSProvider = Depends(get_tts),
) -> Response:
    """Matnni audio baytlarga o'giradi.

    `StubTTS` — sozlanmagan holat. U bo'sh audio qaytaradi, ya'ni
    brauzer jim qolardi. Shuning uchun ochiq 503: frontend buni
    ko'rib o'z ovoziga o'tadi.
    """
    if isinstance(tts, StubTTS):
        raise HTTPException(
            status_code=503,
            detail="TTS sozlanmagan (Azure yoki ElevenLabs kaliti kerak)",
        )

    result = await tts.synthesize(request.text, language=request.language)
    if not result.audio_data:
        raise HTTPException(status_code=503, detail="TTS bo'sh audio qaytardi")

    return Response(
        content=result.audio_data,
        media_type=f"audio/{result.audio_format}",
        headers={"Cache-Control": "no-store"},
    )
