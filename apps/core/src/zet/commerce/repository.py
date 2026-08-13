"""Savdo repozitoriysi — mahsulot va buyurtma CRUD (Z51).

`workspace/repository.py` bilan bir xil naqsh: route'lar SQL yozmaydi,
butun DB mantiqi shu yerda. Shu bilan bir xil amal Telegram do'kon
boti, tool yoki HTTP route tomonidan chaqirilishi mumkin.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
    Z51 — domain/commerce.py: Order CRMDeal'dan nega ajratilgan
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.base import utcnow
from zet.db.models.commerce import Order, Product
from zet.db.models.crm import CRMContact
from zet.domain.commerce import OrderItem, OrderStatus, order_total_uzs


class CommerceNotFoundError(Exception):
    """So'ralgan yozuv topilmadi (yoki boshqa egaga tegishli)."""


def _fresh(stmt: Select[Any]) -> Select[Any]:
    """`workspace/repository.py::_fresh` bilan AYNAN bir xil sabab.

    Buyurtma holati SHU repozitoriyning O'ZI tomonidan ustma-ust
    yozilishi mumkin (masalan mijoz botidan va admin panelidan bir
    vaqtda) — `populate_existing` sessiyadagi eskirgan nusxa emas,
    bazadagi HOZIRGI qatorni qaytarishni kafolatlaydi."""
    return stmt.execution_options(populate_existing=True)


class CommerceRepository:
    """Mahsulot va buyurtma yozuvlari bilan ishlaydi (ega bo'yicha cheklangan)."""

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    # ── Mahsulotlar ──────────────────────────────────────────────

    async def create_product(
        self,
        *,
        name: str,
        description: str = "",
        price_uzs: float = 0.0,
        stock_qty: int = 0,
        sku: str = "",
    ) -> Product:
        product = Product(
            owner_id=self._owner_id,
            name=name,
            description=description,
            price_uzs=price_uzs,
            stock_qty=stock_qty,
            sku=sku,
        )
        self._session.add(product)
        await self._session.flush()
        return product

    async def list_products(
        self, *, active_only: bool = True, limit: int = 200
    ) -> Sequence[Product]:
        stmt = select(Product).where(Product.owner_id == self._owner_id)
        if active_only:
            stmt = stmt.where(Product.active.is_(True))
        stmt = stmt.order_by(Product.name).limit(limit)
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    async def get_product(self, product_id: uuid.UUID) -> Product:
        stmt = select(Product).where(Product.id == product_id, Product.owner_id == self._owner_id)
        product: Product | None = (await self._session.execute(_fresh(stmt))).scalar_one_or_none()
        if product is None:
            raise CommerceNotFoundError(f"Mahsulot topilmadi: {product_id}")
        return product

    async def update_product(self, product_id: uuid.UUID, **fields: object) -> Product:
        product = await self.get_product(product_id)
        for key, value in fields.items():
            if value is not None:
                setattr(product, key, value)
        await self._session.flush()
        return product

    async def search_products(self, query: str, *, limit: int = 10) -> Sequence[Product]:
        """Nom/tavsifda oddiy qidiruv — mijoz boti shu bilan javob topadi.

        Semantik qidiruv EMAS: katalog odatda kichik (o'nlab-yuzlab
        mahsulot), bu hajmda LIKE yetarli va tezkor — embedding
        infratuzilmasini ishga solish ortiqcha bo'lardi."""
        pattern = f"%{query.strip()}%"
        stmt = (
            select(Product)
            .where(
                Product.owner_id == self._owner_id,
                Product.active.is_(True),
                (Product.name.ilike(pattern) | Product.description.ilike(pattern)),
            )
            .limit(limit)
        )
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    # ── Buyurtmalar ──────────────────────────────────────────────

    async def create_order(
        self,
        *,
        items: list[OrderItem],
        contact_id: uuid.UUID | None = None,
        notes: str = "",
    ) -> Order:
        order = Order(
            owner_id=self._owner_id,
            contact_id=contact_id,
            items=[item.model_dump(mode="json") for item in items],
            total_uzs=order_total_uzs(items),
            notes=notes,
        )
        self._session.add(order)
        await self._session.flush()
        return order

    async def list_orders(
        self,
        *,
        status: OrderStatus | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> Sequence[Order]:
        stmt = select(Order).where(Order.owner_id == self._owner_id)
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if since is not None:
            stmt = stmt.where(Order.created_at >= since)
        stmt = stmt.order_by(Order.created_at.desc()).limit(limit)
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    async def get_order(self, order_id: uuid.UUID) -> Order:
        stmt = select(Order).where(Order.id == order_id, Order.owner_id == self._owner_id)
        order: Order | None = (await self._session.execute(_fresh(stmt))).scalar_one_or_none()
        if order is None:
            raise CommerceNotFoundError(f"Buyurtma topilmadi: {order_id}")
        return order

    async def update_order_status(self, order_id: uuid.UUID, status: OrderStatus) -> Order:
        order = await self.get_order(order_id)
        order.status = status
        await self._session.flush()
        return order

    async def mark_shipment_notified(self, order_id: uuid.UUID) -> Order:
        """Mijozga jo'natish xabari yuborilganini QAYD ETADI.

        Bu — idempotentlikning o'zagi: `daemon` ushbu maydonni
        tekshirib, faqat `None` bo'lgan buyurtmalarga xabar yuboradi.
        Ikki marta ishga tushish ikki marta xabar yubormasligi shart."""
        order = await self.get_order(order_id)
        order.shipped_notified_at = utcnow()
        await self._session.flush()
        return order

    async def orders_awaiting_shipment_notice(self) -> Sequence[Order]:
        """`SHIPPED` bo'lgan, lekin hali xabar yuborilmagan buyurtmalar."""
        stmt = select(Order).where(
            Order.owner_id == self._owner_id,
            Order.status == OrderStatus.SHIPPED,
            Order.shipped_notified_at.is_(None),
        )
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    async def sales_total_uzs(self, *, since: datetime) -> float:
        """Berilgan vaqtdan buyon YETKAZILGAN buyurtmalar summasi.

        Nega faqat `DELIVERED`. "Sotuv" — pul HAQIQATAN qo'lga
        tekkanda hisoblanadi, bekor qilinishi mumkin bo'lgan `NEW`/
        `CONFIRMED` buyurtmalarni qo'shish hisobotni shishirib
        ko'rsatardi."""
        orders = await self.list_orders(status=OrderStatus.DELIVERED, since=since)
        return sum(o.total_uzs for o in orders)

    # ── Kontakt (mijoz) qidirish — do'kon boti uchun ───────────────

    async def get_contact(self, contact_id: uuid.UUID) -> CRMContact | None:
        """`Order.contact_id`dan kontaktni topadi — kargo xabari daemon uchun (#43).

        Boshqa `get_*` metodlaridan farqli o'laroq topilmasa xato
        ko'tarmaydi (`None` qaytaradi): chaqiruvchi (daemon) buni
        "hozircha xabar yubora olmaymiz, keyingi tick'da urinamiz"
        deb talqin qiladi — butun tsiklni to'xtatmaydi."""
        stmt = select(CRMContact).where(
            CRMContact.id == contact_id, CRMContact.owner_id == self._owner_id
        )
        return (await self._session.execute(_fresh(stmt))).scalar_one_or_none()

    async def find_contact_by_chat_id(self, chat_id: int) -> CRMContact | None:
        stmt = select(CRMContact).where(
            CRMContact.owner_id == self._owner_id, CRMContact.telegram_chat_id == chat_id
        )
        return (await self._session.execute(_fresh(stmt))).scalar_one_or_none()

    async def get_or_create_contact_by_chat_id(
        self, *, chat_id: int, display_name: str, username: str = ""
    ) -> CRMContact:
        """Mijoz botiga yozgan kishi uchun kontakt topadi yoki yaratadi.

        Nega kerak. Mijoz DM yozganda uni CRM'da IZLASH kerak — aks
        holda har safar bir xil odam bilan qaytadan tanishgandek
        bo'lardi va buyurtma unga bog'lanmasdi."""
        existing = await self.find_contact_by_chat_id(chat_id)
        if existing is not None:
            return existing

        contact = CRMContact(
            owner_id=self._owner_id,
            name=display_name or f"Telegram {chat_id}",
            telegram=username,
            telegram_chat_id=chat_id,
        )
        self._session.add(contact)
        await self._session.flush()
        return contact


__all__ = ["CommerceNotFoundError", "CommerceRepository"]
