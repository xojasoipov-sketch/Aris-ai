"""Savdo domeni — mahsulot va buyurtma (Z51).

NEGA `CRMDeal`GA QO'SHILMADI.

`CRMDeal`/`DealStage` (proposal → negotiation → won/lost) — B2B sotuv
VORONKASI: "bitim tuzilyaptimi". `Order` esa BUTUNLAY BOSHQA hayot
sikli — bitim tuzilgandan KEYIN boshlanadi: "mahsulot qadoqlanyaptimi,
jo'natildimi, yetib bordimi". Ikkalasini bitta enumga sig'dirish
ularni chalkashtirar edi — "won" holatidagi bitim hali qadoqlanmagan
bo'lishi, "shipped" buyurtma esa hali to'liq to'lanmagan bo'lishi
mumkin.

NEGA ITEMLAR JSON, ALOHIDA JADVAL EMAS.

Kichik do'kon uchun buyurtma — bir necha mahsulot nomi + soni + narxi.
Alohida `order_item` jadvali (FK, join) shu hajmdagi biznes uchun
ortiqcha murakkablik qo'shardi. Narx BUYURTMA PAYTIDA "suratga
olinadi" (snapshot) — mahsulot narxi keyin o'zgarsa, eski
buyurtmalarning summasi orqaga qarab o'zgarib ketmasligi uchun.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class OrderStatus(StrEnum):
    """Buyurtmaning yetkazib berish holati (bitim holati EMAS)."""

    NEW = "new"
    """Endi tushdi — hali tasdiqlanmagan."""

    CONFIRMED = "confirmed"
    """Mijoz bilan kelishildi, qadoqlash kutilmoqda."""

    SHIPPED = "shipped"
    """Kargo chiqdi. Shu holatga o'tganda mijozga AVTOMATIK xabar boradi."""

    DELIVERED = "delivered"
    """Mijozga yetib bordi."""

    CANCELLED = "cancelled"
    """Bekor qilindi."""


TERMINAL_ORDER_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.DELIVERED, OrderStatus.CANCELLED}
)
"""Yakuniy holatlar — bu yerdan boshqa holatga o'tish yo'q."""


class OrderItem(BaseModel, frozen=True):
    """Buyurtmadagi bitta qator — narx SNAPSHOT qilingan.

    `product_id` ixtiyoriy: agar mahsulot keyin katalogdan o'chirilsa
    ham, eski buyurtma o'zining yozuvini yo'qotmasligi kerak."""

    product_id: str | None = None
    name: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    unit_price_uzs: float = Field(ge=0)

    @property
    def subtotal_uzs(self) -> float:
        return self.quantity * self.unit_price_uzs


def order_total_uzs(items: list[OrderItem]) -> float:
    """Buyurtma summasi — itemlardan hisoblanadi, qo'lda kiritilmaydi."""
    return sum(item.subtotal_uzs for item in items)


__all__ = [
    "TERMINAL_ORDER_STATUSES",
    "OrderItem",
    "OrderStatus",
    "order_total_uzs",
]
