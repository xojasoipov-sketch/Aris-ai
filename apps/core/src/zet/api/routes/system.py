"""Tizim o'lchovlari va integratsiya holati (Z46.1).

    GET /api/v1/system        — HAQIQIY CPU/RAM/disk + uptime
    GET /api/v1/integrations  — qaysi tashqi xizmat HAQIQATAN sozlangan

NEGA BU ROUTE'LAR KERAK BO'LDI.

Ikkala ma'lumot ham frontend'da QOTIRILGAN edi va ega ularni haqiqiy
deb o'qirdi:

  · `terminal/page.tsx` — "CPU: 24% · RAM: 41% · GPU: 15%",
    "Uptime: 24:13:22", "Faol agentlar: 4 / 6" — hech biri
    o'lchanmagan. Ustiga har 2.5 soniyada tasodifiy log qatori
    HAQIQIY vaqt tamg'asi bilan chop etilardi, ya'ni jonli tizim
    oqimidan farq qilmasdi.

  · `settings/page.tsx` — `INTEGRATIONS` massivida `configured: true`
    QO'LDA yozilgan edi. Sahifa "Telegram bot — Sozlangan" deb
    ko'rsatardi, hech qanday tekshiruvsiz.

Bog'liq qarorlar:
    V-01 — natija ega uchun; o'lchanmagan sonni ko'rsatish yolg'on
    CLAUDE.md "Halol holatlar" — soxta jonli raqamlar taqiqlanadi
"""

from __future__ import annotations

import time
from typing import Final

import psutil
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from zet.api.deps import get_config
from zet.config import Settings

router = APIRouter(tags=["system"])

_STARTED_AT: Final[float] = time.monotonic()
"""Protsess boshlangan payt — uptime shu asosda hisoblanadi.

Frontend "Sessiya" deb sahifa ochilgan vaqtni ko'rsatardi; bu esa
BACKEND protsessining haqiqiy ishlash muddati."""


class SystemMetrics(BaseModel):
    """O'lchangan tizim ko'rsatkichlari.

    Har biri HAQIQATAN o'lchanadi. O'lchab bo'lmaydigan narsa (GPU)
    umuman qaytarilmaydi — nol yoki taxminiy son yozish yolg'on
    bo'lardi."""

    cpu_percent: float
    memory_percent: float
    memory_used_mb: int
    memory_total_mb: int
    disk_percent: float
    disk_free_gb: float
    uptime_seconds: int
    """Backend protsessining ishlash muddati."""


class IntegrationStatus(BaseModel):
    """Bitta tashqi xizmat holati."""

    key: str
    label: str
    configured: bool
    detail: str = ""
    """Nega sozlanmagan yoki qaysi rejimda ishlayotgani."""


@router.get("/system", response_model=SystemMetrics)
async def system_metrics() -> SystemMetrics:
    """HAQIQIY tizim o'lchovlari.

    `cpu_percent(interval=None)` oldingi chaqiruvdan beri o'rtachani
    qaytaradi — bloklamaydi. Birinchi chaqiruvda 0.0 bo'lishi mumkin,
    bu normal (o'lchov oynasi hali yopilmagan).
    """
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return SystemMetrics(
        cpu_percent=round(psutil.cpu_percent(interval=None), 1),
        memory_percent=round(memory.percent, 1),
        memory_used_mb=round(memory.used / 1024 / 1024),
        memory_total_mb=round(memory.total / 1024 / 1024),
        disk_percent=round(disk.percent, 1),
        disk_free_gb=round(disk.free / 1024 / 1024 / 1024, 1),
        uptime_seconds=int(time.monotonic() - _STARTED_AT),
    )


@router.get("/integrations", response_model=list[IntegrationStatus])
async def integrations(
    settings: Settings = Depends(get_config),
) -> list[IntegrationStatus]:
    """Qaysi tashqi xizmat HAQIQATAN sozlangan.

    Sozlamalar sahifasi buni qo'lda yozilgan `configured: true` bilan
    ko'rsatardi. Endi javob `.env`dagi haqiqiy holatdan keladi.

    Kalitning O'ZI hech qachon qaytarilmaydi — faqat bor/yo'qligi.
    """
    return [
        _status("telegram", "Telegram bot", settings.telegram_bot_token),
        _status("elevenlabs", "ElevenLabs (ovoz)", settings.elevenlabs_api_key),
        _status(
            "azure_speech",
            "Azure Speech (o'zbek TTS)",
            settings.azure_speech_key,
            # Kalit yetarli emas — region ham kerak, aks holda
            # endpoint URL qurilmaydi va TTS jim yiqiladi.
            extra_ok=bool(settings.azure_speech_region),
            missing_detail="kalit bor, lekin region ko'rsatilmagan",
        ),
        _status("google", "Google Gemini", settings.google_api_key),
        _status("mistral", "Mistral", settings.mistral_api_key),
        _status("openrouter", "OpenRouter", settings.openrouter_api_key),
        _status("cohere", "Cohere", settings.cohere_api_key),
        _status("anthropic", "Anthropic", settings.anthropic_api_key),
        _status("github", "GitHub", settings.github_token),
        _status("web_search", "Web qidiruv (Brave)", settings.web_search_api_key),
        _status("youtube", "YouTube Data API", settings.youtube_api_key),
        _status(
            "instagram",
            "Instagram Graph API",
            settings.instagram_access_token,
            extra_ok=bool(settings.instagram_business_account_id),
            missing_detail="token bor, lekin business account ID yo'q",
        ),
        _status(
            "camera",
            "Hikvision kamera",
            settings.hikvision_password,
            extra_ok=bool(settings.hikvision_host and settings.hikvision_username),
            missing_detail="parol bor, lekin host/foydalanuvchi to'liq emas",
        ),
    ]


def _status(
    key: str,
    label: str,
    secret: object,
    *,
    extra_ok: bool = True,
    missing_detail: str = "",
) -> IntegrationStatus:
    """Sirni OCHMASDAN holat qaytaradi."""
    has_secret = secret is not None and bool(secret)
    configured = has_secret and extra_ok
    detail = ""
    if has_secret and not extra_ok:
        detail = missing_detail
    elif not has_secret:
        detail = "kalit kiritilmagan — stub rejim"
    return IntegrationStatus(key=key, label=label, configured=configured, detail=detail)
