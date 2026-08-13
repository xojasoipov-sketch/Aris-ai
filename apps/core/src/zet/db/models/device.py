"""Qurilma DB modellari — ro'yxat va capability tokenlar (Bo'lim 8, A-06).

Ilgari `devices/registry.py`dagi `DeviceRegistry` faqat in-memory edi —
protsess qayta ishga tushishi bilan barcha qurilmalar va ularning
tokenlari yo'qolardi (GAP_ANALYSIS #12). Bu jadvallar `DeviceDBRepository`
orqali haqiqiy saqlashni ta'minlaydi.

Xavfsizlik qarori — TOKEN XESH:
    `capability_token` jadvalida faqat SHA-256 **xesh** saqlanadi, xom
    token emas. Xom qiymat faqat yaratish paytida QAYTARILADI va boshqa
    hech qayerda qayta olinmaydi. Sabab: baza zaxira nusxasi (backup,
    dump, replika) yoki DBA huquqi ochilib qolsa ham faol tokenlar
    "qora ro'yxat"ga chiqib ketmasin. Xesh — bir tomonlama; egasi
    tokenni yo'qotsa yangisini yaratishga majbur (bilib turib).

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar (iPhone/Mac boshqaruvi shu orqali)
    A-06 — capability token asosida ruxsat
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, enum_column
from zet.devices.registry import DeviceType


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ro'yxatga olingan qurilma — telefon, desktop, kamera, IoT."""

    __tablename__ = "device"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    """Ko'rinadigan nom (masalan `iPhone 15`, `MacBook Pro`)."""

    device_type: Mapped[DeviceType] = mapped_column(
        enum_column(DeviceType), default=DeviceType.IOT, index=True
    )
    platform: Mapped[str] = mapped_column(String(32), default="")
    """Operatsion tizim yoki vendor (`ios`, `macos`, `windows`, `hikvision`)."""

    model: Mapped[str] = mapped_column(String(128), default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    online: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Qo'shimcha ma'lumotlar (JSON) — OS versiyasi, seriya raqami, va h.k.

    `metadata` nomi SA `DeclarativeBase`da band bo'lgani uchun `meta`
    ishlatiladi (`Message.meta` bilan bir xil naqsh)."""

    __table_args__ = (Index("ix_device_owner_type", "owner_id", "device_type"),)


class CapabilityToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Qurilma capability tokeni (A-06) — SHA-256 XESH sifatida saqlanadi.

    Xom token faqat yaratish javobida bir marta ko'rinadi (uni egasi
    qurilmaga o'zi ko'chirishi kerak). Keyingi tekshiruvlarda validator
    kelgan qiymatni xeshlab shu ustun bilan solishtiradi.
    """

    __tablename__ = "capability_token"

    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("device.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    """SHA-256 xesh (hex-64 belgi). XOM token emas — yuqoridagi izohga qarang."""

    capabilities: Mapped[list[str]] = mapped_column(default=list)
    """Ruxsat etilgan imkoniyatlar (masalan `["camera.snapshot", "notify"]`)."""

    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    """`None` — cheksiz. Aks holda `validate_token` shu vaqtdan keyin rad etadi."""

    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    """Bekor qilingan vaqt. `None` — faol. Yozuv o'chirilmaydi (audit izi qolsin)."""

    label: Mapped[str] = mapped_column(Text, default="")
    """Ixtiyoriy sharh (`iPhone shaxsiy`, `Zaxira token`)."""

    __table_args__ = (Index("ix_capability_token_device_revoked", "device_id", "revoked_at"),)


__all__ = ["CapabilityToken", "Device"]
