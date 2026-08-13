"""Savdo repozitoriysi testlari (Z51).

NEGA BU TESTLAR BOR.

`workspace.py`ning "sahifa ortida backend yo'q edi" muammosi bilan bir
xil: mahsulot/buyurtma bo'lmasa mijoz botiga (#42) va kargo xabariga
(#43) tayanadigan hech narsa haqiqiy emas edi. Bu testlar summa
HISOBLANISHINI (qo'lda kiritilmasligini), narx SNAPSHOT bo'lishini va
`shipped_notified_at` IKKI MARTA XABAR yubormasligini qulflaydi.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.commerce.repository import CommerceNotFoundError, CommerceRepository
from zet.db.models import Owner
from zet.domain.commerce import OrderItem, OrderStatus


@pytest.fixture
def repo(session: AsyncSession, owner: Owner) -> CommerceRepository:
    return CommerceRepository(session, owner_id=owner.id)


class TestProducts:
    async def test_created_product_is_persisted(self, repo: CommerceRepository) -> None:
        created = await repo.create_product(name="Krossovka", price_uzs=250_000)

        found = await repo.get_product(created.id)

        assert found.name == "Krossovka"
        assert found.active is True

    async def test_list_excludes_inactive_by_default(self, repo: CommerceRepository) -> None:
        await repo.create_product(name="Faol")
        inactive = await repo.create_product(name="Nofaol")
        await repo.update_product(inactive.id, active=False)

        active = await repo.list_products()

        assert [p.name for p in active] == ["Faol"]

    async def test_update_changes_only_given_fields(self, repo: CommerceRepository) -> None:
        product = await repo.create_product(name="Eski", price_uzs=1000)

        updated = await repo.update_product(product.id, name="Yangi")

        assert updated.name == "Yangi"
        assert updated.price_uzs == 1000

    async def test_missing_product_raises(self, repo: CommerceRepository) -> None:
        with pytest.raises(CommerceNotFoundError):
            await repo.get_product(uuid.uuid4())

    async def test_search_matches_name_or_description(self, repo: CommerceRepository) -> None:
        await repo.create_product(name="Qora futbolka", description="paxta")
        await repo.create_product(name="Shim", description="qora rangli, jinsi")
        await repo.create_product(name="Boshqa narsa", description="hech narsa")

        found = await repo.search_products("qora")

        assert {p.name for p in found} == {"Qora futbolka", "Shim"}


class TestOrders:
    async def test_total_is_computed_from_items(self, repo: CommerceRepository) -> None:
        items = [
            OrderItem(name="A", quantity=2, unit_price_uzs=10_000),
            OrderItem(name="B", quantity=1, unit_price_uzs=5_000),
        ]

        order = await repo.create_order(items=items)

        assert order.total_uzs == 25_000

    async def test_price_is_snapshotted_not_relinked(self, repo: CommerceRepository) -> None:
        """Mahsulot narxi keyin o'zgarsa, eski buyurtma summasi o'zgarmasligi kerak."""
        product = await repo.create_product(name="Ko'ylak", price_uzs=100_000)
        order = await repo.create_order(
            items=[
                OrderItem(
                    product_id=str(product.id),
                    name=product.name,
                    quantity=1,
                    unit_price_uzs=product.price_uzs,
                )
            ]
        )

        await repo.update_product(product.id, price_uzs=200_000)

        unchanged = await repo.get_order(order.id)
        assert unchanged.total_uzs == 100_000

    async def test_default_status_is_new(self, repo: CommerceRepository) -> None:
        order = await repo.create_order(
            items=[OrderItem(name="X", quantity=1, unit_price_uzs=1000)]
        )

        assert order.status is OrderStatus.NEW

    async def test_list_filters_by_status(self, repo: CommerceRepository) -> None:
        item = [OrderItem(name="X", quantity=1, unit_price_uzs=1000)]
        a = await repo.create_order(items=item)
        await repo.create_order(items=item)
        await repo.update_order_status(a.id, OrderStatus.SHIPPED)

        shipped = await repo.list_orders(status=OrderStatus.SHIPPED)

        assert [o.id for o in shipped] == [a.id]

    async def test_missing_order_raises(self, repo: CommerceRepository) -> None:
        with pytest.raises(CommerceNotFoundError):
            await repo.get_order(uuid.uuid4())


class TestShipmentNotification:
    """`shipped_notified_at` — idempotentlikning o'zagi (#43)."""

    async def test_new_shipped_order_awaits_notice(self, repo: CommerceRepository) -> None:
        item = [OrderItem(name="X", quantity=1, unit_price_uzs=1000)]
        order = await repo.create_order(items=item)
        await repo.update_order_status(order.id, OrderStatus.SHIPPED)

        awaiting = await repo.orders_awaiting_shipment_notice()

        assert [o.id for o in awaiting] == [order.id]

    async def test_marking_notified_removes_it_from_queue(self, repo: CommerceRepository) -> None:
        item = [OrderItem(name="X", quantity=1, unit_price_uzs=1000)]
        order = await repo.create_order(items=item)
        await repo.update_order_status(order.id, OrderStatus.SHIPPED)

        await repo.mark_shipment_notified(order.id)

        awaiting = await repo.orders_awaiting_shipment_notice()
        assert awaiting == []

    async def test_non_shipped_orders_never_await_notice(self, repo: CommerceRepository) -> None:
        item = [OrderItem(name="X", quantity=1, unit_price_uzs=1000)]
        await repo.create_order(items=item)  # NEW holatida qoladi

        awaiting = await repo.orders_awaiting_shipment_notice()

        assert awaiting == []


class TestSalesTotal:
    """Faqat YETKAZILGAN buyurtmalar "sotuv" hisoblanadi."""

    async def test_only_delivered_orders_count(self, repo: CommerceRepository) -> None:
        item = [OrderItem(name="X", quantity=1, unit_price_uzs=10_000)]
        delivered = await repo.create_order(items=item)
        await repo.update_order_status(delivered.id, OrderStatus.DELIVERED)
        cancelled = await repo.create_order(items=item)
        await repo.update_order_status(cancelled.id, OrderStatus.CANCELLED)
        await repo.create_order(items=item)  # NEW — hali sotuv emas

        total = await repo.sales_total_uzs(since=datetime.now(UTC) - timedelta(days=1))

        assert total == 10_000


class TestContactByChatId:
    async def test_creates_contact_on_first_message(self, repo: CommerceRepository) -> None:
        contact = await repo.get_or_create_contact_by_chat_id(
            chat_id=555, display_name="Aziz", username="aziz_tg"
        )

        assert contact.telegram_chat_id == 555
        assert contact.name == "Aziz"

    async def test_second_call_returns_same_contact(self, repo: CommerceRepository) -> None:
        first = await repo.get_or_create_contact_by_chat_id(chat_id=555, display_name="Aziz")
        second = await repo.get_or_create_contact_by_chat_id(chat_id=555, display_name="Aziz")

        assert first.id == second.id


class TestOwnerIsolation:
    """Boshqa egaga tegishli yozuv qaytmasligi kerak."""

    async def test_other_owner_cannot_read(self, session: AsyncSession, owner: Owner) -> None:
        mine = CommerceRepository(session, owner_id=owner.id)
        product = await mine.create_product(name="Meniki")

        stranger = CommerceRepository(session, owner_id=uuid.uuid4())

        with pytest.raises(CommerceNotFoundError):
            await stranger.get_product(product.id)
