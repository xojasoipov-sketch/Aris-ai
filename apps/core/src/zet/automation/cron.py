"""Soddalashtirilgan cron mos kelish tekshiruvi (Bo'lim 9).

`ScheduleRule.cron_expr` — 5-field cron (yoki `@hourly`/`@daily`/...
shortcut). Bu modul joriy vaqt shu ifodaga mos kelayotganini tekshiradi —
`AutomationDaemon` har tikda shu orqali "vaqti keldimi?" deb so'raydi.

Diqqat — standart `croniter`dan ataylab soddalashtirilgan ikkita joy:
    1. Kun-oy (DOM) va hafta-kun (DOW) maydonlari AND bilan birlashtiriladi
       (an'anaviy cron'da ikkalasi ham cheklangan bo'lsa OR ishlatiladi).
    2. `/N` qadam butun (ro'yxat/oraliq) to'plamiga nisbatan qo'llanadi —
       to'plamning eng kichik a'zosidan hisoblanadi.
Bu loyihaning o'ziga xos ehtiyoji uchun yetarli (yagona eganing shaxsiy
jadvallari — murakkab enterprise cron ifodalari kutilmaydi).
"""

from __future__ import annotations

from datetime import datetime

CRON_SHORTCUTS: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
}
"""`ScheduleRule.normalized_cron` va `is_due()` ikkalasi ham shu jadvaldan foydalanadi."""


def _expand_field(field: str, *, min_v: int, max_v: int) -> set[int]:
    """Bitta cron maydonini ruxsat etilgan butun sonlar to'plamiga o'giradi."""
    body = field
    step = 1
    if "/" in field:
        body, step_str = field.rsplit("/", 1)
        step = int(step_str)

    if body == "*":
        values = set(range(min_v, max_v + 1))
    else:
        values = set()
        for part in body.split(","):
            if "-" in part:
                lo, hi = part.split("-", 1)
                values.update(range(int(lo), int(hi) + 1))
            else:
                values.add(int(part))

    if step > 1 and values:
        base = min(values)
        values = {v for v in values if (v - base) % step == 0}
    return values


def is_due(cron_expr: str, at: datetime) -> bool:
    """Joriy vaqt cron ifodasiga mos keladimi (minut aniqligida).

    Args:
        cron_expr: 5-field cron ('minute hour dom month dow') yoki shortcut.
        at: Tekshiriladigan vaqt (mahalliy timezone'ga o'tkazilgan bo'lishi kerak).

    Returns:
        True — mos kelsa. Noto'g'ri formatdagi ifoda uchun ham False
        qaytaradi (fail-closed — hech qachon ishga tushmaydi, xato ko'tarmaydi).
    """
    normalized = CRON_SHORTCUTS.get(cron_expr, cron_expr)
    parts = normalized.split()
    if len(parts) != 5:
        return False

    minute, hour, dom, month, dow = parts
    try:
        if at.minute not in _expand_field(minute, min_v=0, max_v=59):
            return False
        if at.hour not in _expand_field(hour, min_v=0, max_v=23):
            return False
        if at.day not in _expand_field(dom, min_v=1, max_v=31):
            return False
        if at.month not in _expand_field(month, min_v=1, max_v=12):
            return False
        weekday = at.isoweekday() % 7  # Yakshanba(7)->0, Dushanba(1)->1, ... Shanba->6
        if weekday not in _expand_field(dow, min_v=0, max_v=6):
            return False
    except ValueError:
        return False
    return True


__all__ = ["CRON_SHORTCUTS", "is_due"]
