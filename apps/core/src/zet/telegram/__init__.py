"""Telegram bot tizimi — ZET'ning asosiy boshqaruv paneli (Bo'lim 5).

Komponentlar:
    - ZetBot: aiogram 3 bot, long polling, owner allowlist
    - OwnerMiddleware: faqat egasiga ruxsat (A-05)
    - Handlers: text, voice, image, file, callback
    - Keyboards: inline approval tugmalari (V-32)
    - Notifier: push bildirishnomalar (alerts, task results)

Bog'liq qarorlar:
    V-17 — Telegram = asosiy boshqaruv paneli
    V-18 — Ovoz birinchi darajali kirish
    ADR-0007 — long polling (webhook emas)
    R-04 — bot token xavfsizligi (owner allowlist)
"""

from zet.telegram.bot import ZetBot
from zet.telegram.keyboards import ApprovalKeyboard
from zet.telegram.middleware import OwnerMiddleware
from zet.telegram.notifier import Notifier

__all__ = [
    "ApprovalKeyboard",
    "Notifier",
    "OwnerMiddleware",
    "ZetBot",
]
