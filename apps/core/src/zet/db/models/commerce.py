"""Savdo DB modellari — mahsulot va buyurtma (Z51).

`/tasks`/`/projects` uchun Z46'da qurilgan naqshning aynan davomi:
jadval → repozitoriy → tool → route, bitta kod yo'li.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
    Z51 — domain/commerce.py: nega Order CRMDeal'dan ajratilgan
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import (
    Base,
    JSONType,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
    enum_column,
)
from zet.domain.commerce import OrderStatus


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Katalogdagi bitta mahsulot."""

    __tablename__ = "product"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(64), default="")
    """Ixtiyoriy ichki kod — bo'sh qoldirilishi mumkin."""

    description: Mapped[str] = mapped_column(Text, default="")
    """Mijoz botining javob matni shu yerdan olinadi — RAG manbasi."""

    price_uzs: Mapped[float] = mapped_column(default=0.0)
    stock_qty: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    """`False` — vaqtincha sotuvdan olib qo'yilgan, o'chirilmagan."""

    __table_args__ = (Index("ix_product_owner_active", "owner_id", "active"),)


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta buyurtma."""

    # `order` — SQL zaxira so'zi. SQLAlchemy uni avtomatik qo'shtirnoqqa
    # oladi, lekin qo'lda yozilgan har qanday xom SQL (hisobot, migratsiya
    # tuzatishi) buni unutib qolishi mumkin — shuning uchun ATAYIN olib
    # tashlandi.
    __tablename__ = "customer_order"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        # `SET NULL` — kontakt o'chirilsa buyurtma tarixi yo'qolmaydi,
        # xuddi `task.project_id` kabi (Z46 qarori, aynan takrorlanadi).
        ForeignKey("crm_contact.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus), default=OrderStatus.NEW, index=True
    )
    items: Mapped[list[dict[str, object]]] = mapped_column(JSONType, default=list)
    """`OrderItem` ro'yxati (Pydantic JSON rejimida) — narx snapshot."""

    total_uzs: Mapped[float] = mapped_column(default=0.0)
    """Itemlardan HISOBLANGAN summa — qo'lda kiritilmaydi (Z46 progress'dagi
    "qotirilgan foiz" xatosining takrorlanmasligi uchun)."""

    notes: Mapped[str] = mapped_column(Text, default="")
    shipped_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    """Mijozga jo'natish xabari YUBORILGAN payt — `None` bo'lsa hali yo'q.

    Bu maydon IKKI MARTA XABAR YUBORISHNING oldini oladi: agar daemon
    qayta ishga tushsa yoki holat ikki marta yozilsa, xabar faqat BIR
    marta ketishi kerak."""

    __table_args__ = (Index("ix_order_owner_status", "owner_id", "status"),)


__all__ = ["Order", "Product"]
