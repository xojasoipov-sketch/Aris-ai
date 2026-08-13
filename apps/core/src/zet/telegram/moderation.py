"""Kanal/guruhdagi begona xabarlarni aniqlash — sof, deterministik (Z51, #44).

NEGA FAQAT QOIDA ASOSIDA (LLM EMAS).

Guruh xabarini o'chirish QAYTARIB BO'LMAYDIGAN amal — LLM
gallyutsinatsiyasi yoki noaniq "ehtimol spam" bahosi haqiqiy mijoz
xabarini yo'q qilib yuborishi mumkin. MVP shu sabab IKKI DETERMINISTIK
qoidaga tayanadi:

    1. Yuboruvchi BOSHQA BOT (`from.is_bot=True`, o'zimizniki emas) —
       "ortiqcha bot" talabining aynan o'zi (#44 birinchi jumlasi).
    2. Matn ANIQ spam naqshiga mos keladi (havola + "pul ishlash"/
       "bepul"/kripto turkumidagi so'zlar birgalikda) — "ehtimol"ga
       emas, ANIQ moslikka asoslangan.

Ikkalasi ham mos kelmasa — XABARGA TEGILMAYDI. Noaniq holatda
o'chirmaslik xato o'chirishdan har doim arzonroq — mijoz haqiqiy
savoli spam bilan aralashib ketmasligi kerak.

Bu modul FAQAT aniqlaydi (`classify`) — o'chirish HARAKATINI
`zet/telegram/polling.py`dagi chaqiruvchi bajaradi (Bot API chaqiruvi
bilan bog'liq I/O shu yerda emas — test qilish osonroq bo'lishi
uchun)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_URL_PATTERN = re.compile(r"https?://|t\.me/|@\w{5,}", re.IGNORECASE)

_SPAM_KEYWORDS = (
    "заработ",  # zarabotok — "ishlash/pul topish" (ruscha spam klassikasi)
    "crypto",
    "kripto",
    "bepul pul",
    "click here",
    "bosing va yutib oling",
    "airdrop",
    "invest",
    "investitsiya kiriting",
)
"""Bitta so'z YETARLI EMAS — havola bilan BIRGALIKDA (`_URL_PATTERN`)
kelgandagina spam deb hisoblanadi (`classify` ichidagi mantiqqa qarang)."""


@dataclass(frozen=True, slots=True)
class ModerationVerdict:
    """Bitta xabar bo'yicha qaror."""

    should_delete: bool
    reason: str = ""
    """Nima uchun o'chirilishi kerak — ega uchun tushunarli, log/audit uchun."""


def classify(
    message: dict[str, Any], *, own_bot_ids: frozenset[int] = frozenset()
) -> ModerationVerdict:
    """Bitta Telegram `message` obyektini tekshiradi.

    Args:
        message: Bot API `message` obyekti (getUpdates natijasidan).
        own_bot_ids: ZET botlarining O'Z user_id'lari — ular hech qachon
            o'chirilmasligi kerak (masalan ega `ShopBot` orqali javob
            yozganda, o'sha xabar `from.is_bot=True` bo'ladi, lekin bu
            "begona bot" emas).
    """
    sender = message.get("from") or {}
    sender_id = sender.get("id")

    if sender.get("is_bot") and sender_id not in own_bot_ids:
        username = sender.get("username", "noma'lum")
        return ModerationVerdict(should_delete=True, reason=f"begona bot xabari (@{username})")

    text = (message.get("text") or message.get("caption") or "").strip()
    if not text:
        return ModerationVerdict(should_delete=False)

    has_link = bool(_URL_PATTERN.search(text))
    lowered = text.lower()
    matched_keyword = next((kw for kw in _SPAM_KEYWORDS if kw in lowered), None)

    if has_link and matched_keyword is not None:
        return ModerationVerdict(
            should_delete=True, reason=f"spam naqshi: havola + '{matched_keyword}'"
        )

    return ModerationVerdict(should_delete=False)


__all__ = ["ModerationVerdict", "classify"]
