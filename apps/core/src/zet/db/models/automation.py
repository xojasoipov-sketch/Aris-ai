"""Avtomatlashtirish holati — jadval/trigger/kuzatuv snapshot'i (Z48.2).

NEGA BU JADVAL KERAK BO'LDI.

`AutomationEngine` TO'LIQ XOTIRADA yashaydi (`lru_cache` singleton).
Ega TIZIM retseptini yoqsa — masalan T06 "Kunlik puls" — u ishlaydi,
lekin **birinchi qayta ishga tushishdayoq jimgina yo'qoladi**: Railway
redeploy, konteyner qayta ishga tushishi yoki oddiy restart yetarli.

Bu soxta tugmadan ham yomonroq holat. Soxta tugma darhol ko'rinadi;
bu esa bir necha kun ISHLAYDI, keyin sababsiz to'xtaydi va ega buni
faqat hisobot kelmaganda sezadi — ya'ni aynan ishonch kerak bo'lgan
paytda.

NEGA SNAPSHOT, HAR BIR QOIDA UCHUN QATOR EMAS.

Ega BITTA. Qoidalar soni o'nlab, minglab emas. Har bir qoida turi
uchun alohida jadval + har bir mutatsiyani (qo'shish, pauza, davom
etish, o'chirish, ishga tushdi-belgisi) alohida sinxronlash ko'p kod
va ko'p xato yo'li ochardi. Butun holatni bitta JSON qatoriga yozish
esa "xotiradagi holat = bazadagi holat" invariantini bitta joyda
ushlab turadi.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class AutomationState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Eganing butun avtomatlashtirish holati — bitta qator."""

    __tablename__ = "automation_state"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), unique=True, index=True
    )
    """Ega — UNIQUE: bir egada bitta snapshot."""

    schedules: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    """`ScheduleRule` yozuvlari (Pydantic JSON rejimida)."""

    triggers: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    """`EventTrigger` yozuvlari."""

    watchers: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    """`WatchRule` yozuvlari."""


__all__ = ["AutomationState"]
