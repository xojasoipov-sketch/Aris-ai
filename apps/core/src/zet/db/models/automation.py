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

from sqlalchemy import ForeignKey, String, UniqueConstraint
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


class ScheduledFire(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta `ScheduleRule`ning bitta daqiqadagi ijrosini "da'vo qilish" ledgeri (JB-11).

    MUAMMO: `AutomationDaemon._last_fired_minute` — in-process dict,
    restart'da bo'shaydi (JB-10 `hydrate_last_fired_from_rules` bilan
    QISMAN yumshatilgan — faqat "process restart, boshqa daqiqa"
    holatini yopadi). Ikkita HAQIQIY xavf ochiq qoladi:
        1. Bir xil daqiqada process CRASH bo'lib qayta ko'tarilsa (yoki
           deploy paytida eski/yangi process bir lahza parallel ishlasa)
           — ikkalasi ham bir xil qoidani bir xil daqiqada fire qilishi
           mumkin.
        2. Kelajakda bir nechta worker/pod ishga tushsa — hech qanday
           umumiy holat yo'q, har biri mustaqil fire qiladi.

    YECHIM: `(rule_id, minute_key)` ustida UNIQUE constraint — DAEMON
    fire qilishdan OLDIN shu qatorni yozishga urinadi (`INSERT`). Agar
    qator allaqachon mavjud bo'lsa (`IntegrityError` — unique
    violation) — boshqa process/worker ALLAQACHON da'vo qilgan, bu
    chaqiruv JIMGINA o'tkazib yuboriladi. Bu — Postgres/SQLite'ning
    o'zi ta'minlaydigan ATOMIK "compare-and-set" — qo'shimcha
    tashqi lock xizmati kerak emas.

    Eski qatorlar vaqti-vaqti bilan tozalanishi mumkin (bu JB doirasida
    emas — jadval sekin o'sadi, xavfsizlik uchun tashvishli emas).
    """

    __tablename__ = "scheduled_fire"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    """Ega — kuzatuv/tozalash uchun (uniqueness'ga kirmaydi, chunki
    `rule_id` allaqachon global unikal — bir nechta ega bo'lsa ham
    bitta qoida bitta owner'ga tegishli)."""

    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    """`ScheduleRule.id` (12-hex-belgili identifikator)."""

    minute_key: Mapped[str] = mapped_column(String(20))
    """`'%Y-%m-%d %H:%M'` formatidagi daqiqa kaliti — `AutomationDaemon`
    ning mavjud minute-key naqshi bilan bir xil (`tick()`)."""

    # NEGA nom berilmagan: `Base.metadata`ning `NAMING_CONVENTION`si
    # (`db/base.py`) buni avtomatik `uq_scheduled_fire_rule_id_minute_key`
    # deb formatlaydi — bu migratsiyadagi `op.f(...)` bilan ANIQ mos
    # kelishi kerak (aks holda `test_no_schema_drift` qizarardi).
    __table_args__ = (UniqueConstraint("rule_id", "minute_key"),)


__all__ = ["AutomationState", "ScheduledFire"]
