"""Tabiiy tildan cron ifodasini ajratib olish (JB-9).

MUAMMO: JB-8 `ExecutionModeClassifier` "Har kuni soat 9 da telegramimni
tekshir" so'rovini BACKGROUND_WORKFLOW deb to'g'ri aniqladi, lekin
Brain'da undan haqiqiy `ScheduleRule` yaratish uchun cron ifodasini
so'rov matnidan ajratib olish kerak edi.

YECHIM: ODDIY, DETERMINISTIK naqsh mos ustuvorligi (LLM chaqiruvi YO'Q —
ExecutionModeClassifier bilan bir xil falsafa: qaror tushuntiriladigan
va kuzatiladigan bo'lishi kerak, "sirli LLM" bo'lmasligi kerak).

QAMROV: eng ko'p uchraydigan uzbek + inglizcha iboralar:
    "har kuni soat 9 da"    → 0 9 * * *
    "har hafta dushanba"    → 0 9 * * 1
    "har oy 1-kuni"         → 0 9 1 * *
    "har soat"              → 0 * * * *
    "har 30 daqiqa"         → */30 * * * *

TALAB QILINMAYDIGAN NARSA: tabiiy tildagi HAR QANDAY vaqt ifodasini
qamrab olish — bu maqsad LLM'gagina to'g'ri keladi. Bu yerda faqat
"aniq va tez-tez ishlatiladigan" qismi. Ajratib bo'lmasa `None` —
Brain uni oddiy Mission yo'liga (bir martalik) yuboradi va foydalanuvchiga
so'rovni aniqroq qilib yozishni taklif qiladi.

HALOL DOIRA (JB-9, ochiq kamchilik):
    Bu parser ATAYLAB CHEKLANGAN. Murakkab holatlar ("har juma va
    yakshanba 14:30 dan 18:00 gacha yarim soatda") uchun bu yerda LLM
    ishlatilmaydi (V-15 xavfsizlik chegarasi: LLM avtomatik takrorlanuvchi
    jadval yaratsa — foydalanuvchi kutmagan xarajat/ta'sirni keltirib
    chiqarishi mumkin). Murakkab ifodalar uchun foydalanuvchi
    `POST /api/v1/automation/schedules` orqali to'g'ridan-to'g'ri cron
    kiritishi kerak.

Bog'liq qarorlar:
    JB-8 — ExecutionModeClassifier (BACKGROUND_WORKFLOW aniqlash)
    JB-9 — Brain → AutomationEngine.Scheduler integratsiyasi
    Bo'lim 9 — cron formatlari va Scheduler
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Yordamchi naqshlar ───────────────────────────────────────────────
#
# NEGA aniq raqamlarga qarshi so'zlarni qidiramiz: uzbek tilida
# "soat 9 da" / "soat 09:00 da" / "soat to'qqizda" — hammasi tabiiy.
# Bu yerda faqat RAQAMLI variantlarni qamrab olamiz — so'z sonlar
# ("to'qqiz", "yigirma") uchun keyingi bosqichda alohida jadval kerak
# bo'ladi (bu JB doirasida emas).

_HOUR_RE = re.compile(
    r"\bsoat\s*(\d{1,2})(?:\s*[:.]?\s*(\d{2}))?\s*(?:da|larda)?\b",
    re.IGNORECASE,
)
"""'soat 9 da', 'soat 09:30 da', 'soat 21:00' — Uzbek."""

_AT_TIME_RE = re.compile(
    r"\bat\s+(\d{1,2})(?:[:.](\d{2}))?\s*(?:am|pm)?\b",
    re.IGNORECASE,
)
"""'at 9', 'at 9:30', 'at 9am' — English."""

_INTERVAL_MINUTES_RE = re.compile(
    r"\bhar\s+(\d{1,2})\s*(?:daqiqa|minut)\b",
    re.IGNORECASE,
)
"""'har 30 daqiqa'."""

_INTERVAL_HOURS_RE = re.compile(
    r"\bhar\s+(\d{1,2})\s*(?:soat|hour)\b",
    re.IGNORECASE,
)
"""'har 4 soat'."""

_WEEKDAYS_UZ: dict[str, int] = {
    "dushanba": 1,
    "seshanba": 2,
    "chorshanba": 3,
    "payshanba": 4,
    "juma": 5,
    "shanba": 6,
    "yakshanba": 0,
}

_WEEKDAYS_EN: dict[str, int] = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
    "sun": 0,
}


@dataclass(frozen=True, slots=True)
class ScheduleExpression:
    """Tabiiy tildan ajratilgan cron ifodasi + tushuntirish."""

    cron: str
    """5-field cron ifodasi (masalan `'0 9 * * *'`)."""

    reason: str
    """Qanday ibora topilgani (audit/log/UX uchun)."""


# ── Standart soatlar ────────────────────────────────────────────────
_DEFAULT_HOUR = 9  # "har kuni" (soat aniq berilmasa) — ish kunining boshi
_DEFAULT_MINUTE = 0


def _extract_time(text: str) -> tuple[int, int] | None:
    """Buyruq matnidan (soat, daqiqa) topadi; topolmasa None."""
    match = _HOUR_RE.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    match = _AT_TIME_RE.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        # "at 9pm" → 21; oddiylik uchun am/pm ni to'liq qamrab olmaymiz,
        # faqat aniq raqamli (0-23) variant.
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    return None


def _extract_weekday(text: str) -> int | None:
    """Matndan hafta kunini topadi (0=yakshanba, 1=dushanba, ...); yo'q bo'lsa None."""
    lowered = text.lower()
    for name, dow in _WEEKDAYS_UZ.items():
        # bo'lakli qidiruv (bo'shliq bilan) — 'shanba' 'yakshanba' ichida
        # noto'g'ri topilmasin.
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return dow
    for name, dow in _WEEKDAYS_EN.items():
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return dow
    return None


def _extract_day_of_month(text: str) -> int | None:
    """Matndan oy kunini topadi ('1-kuni', '15 kuni'); yo'q bo'lsa None."""
    match = re.search(r"\b(\d{1,2})\s*[-\s]?\s*kuni\b", text.lower())
    if match:
        day = int(match.group(1))
        if 1 <= day <= 31:
            return day
    return None


def parse_schedule(text: str) -> ScheduleExpression | None:
    """Buyruq matnidan cron ifodasini chiqaradi (topilmasa `None`).

    Ustuvorlik tartibi (birinchi mos kelgani g'olib — eng ANIQ
    ifodalar birinchi):

    1. `har N daqiqa` / `har N soat` — interval (yaqinlashuv).
    2. `har oy X-kuni` — oy kuni + (topilsa) soat.
    3. `har hafta <kun>` — hafta kuni + (topilsa) soat.
    4. `har kuni` — kunlik + (topilsa) soat, default 09:00.
    5. `har soat` — soatlik.

    Aniqlik uchun ODDIY qoidalar bilan cheklangan (yuqoridagi modul
    docstring'iga qarang) — murakkab holatlar `None` qaytaradi.
    """
    if not text:
        return None
    lowered = text.lower()

    # 1) Interval (daqiqa/soat) — eng aniq
    match = _INTERVAL_MINUTES_RE.search(lowered)
    if match:
        minutes = int(match.group(1))
        if 1 <= minutes <= 59:
            return ScheduleExpression(
                cron=f"*/{minutes} * * * *",
                reason=f"'har {minutes} daqiqa' — daqiqa oralig'ida takrorlanadi",
            )
    match = _INTERVAL_HOURS_RE.search(lowered)
    if match:
        hours = int(match.group(1))
        if 1 <= hours <= 23:
            return ScheduleExpression(
                cron=f"0 */{hours} * * *",
                reason=f"'har {hours} soat' — soat oralig'ida takrorlanadi",
            )

    time_hint = _extract_time(text)
    hour, minute = time_hint if time_hint else (_DEFAULT_HOUR, _DEFAULT_MINUTE)

    # 2) Oy kuni — "har oy N-kuni"
    if "har oy" in lowered:
        day = _extract_day_of_month(text) or 1
        return ScheduleExpression(
            cron=f"{minute} {hour} {day} * *",
            reason=(
                f"'har oy {day}-kuni' — oyning {day}-kunida "
                f"soat {hour:02d}:{minute:02d} da"
            ),
        )

    # 3) Hafta kuni — "har hafta <kun>"
    if "har hafta" in lowered:
        dow = _extract_weekday(text)
        if dow is not None:
            return ScheduleExpression(
                cron=f"{minute} {hour} * * {dow}",
                reason=(
                    f"'har hafta' + hafta kuni topildi — "
                    f"soat {hour:02d}:{minute:02d} da"
                ),
            )
        # Kun ko'rsatilmagan — dushanba default (ish haftasi boshi).
        return ScheduleExpression(
            cron=f"{minute} {hour} * * 1",
            reason=(
                f"'har hafta' — dushanba (default) soat {hour:02d}:{minute:02d} da"
            ),
        )

    # 4) Kunlik — "har kuni" (yoki "daily" / "every day")
    if "har kuni" in lowered or "every day" in lowered or "daily" in lowered:
        return ScheduleExpression(
            cron=f"{minute} {hour} * * *",
            reason=f"'har kuni' — kunlik soat {hour:02d}:{minute:02d} da",
        )

    # 5) Soatlik — "har soat"
    if re.search(r"\bhar\s+soat\b", lowered) or "hourly" in lowered:
        return ScheduleExpression(
            cron="0 * * * *",
            reason="'har soat' — soatlik",
        )

    # Boshqa hech narsa mos kelmadi.
    return None


__all__ = ["ScheduleExpression", "parse_schedule"]
