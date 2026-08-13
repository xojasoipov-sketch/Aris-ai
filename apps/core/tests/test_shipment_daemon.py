"""ShipmentNotifyDaemon testlari (Z51, #43).

respx bilan — haqiqiy Telegram API'ga chiqmasdan (`test_telegram_http_
notifier.py` bilan bir xil naqsh).

Tekshiriladi:
    - SHIPPED + kontaktli buyurtmaga xabar boradi va shipped_notified_at
      YOZILADI (idempotentlik)
    - Telegram xato bersa notified_at YOZILMAYDI (keyingi tick qayta urinadi)
    - kontaktsiz/chat_id'siz buyurtma o'tkazib yuboriladi (xato emas)
    - token yo'q bo'lsa hech narsa yubormaydi, lekin qulamaydi
"""

from __future__ import annotations

import httpx
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.commerce.repository import CommerceRepository
from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.deploy.shipment_daemon import ShipmentNotifyDaemon
from zet.domain.commerce import OrderItem, OrderStatus

_TOKEN = "123456:SHOP-BOT-FAKE-TOKEN"
_API = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
_OWNER_EXTERNAL_ID = "shipment-daemon-test-owner"


def _settings(*, with_token: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        owner_id=_OWNER_EXTERNAL_ID,
        shop_bot_token=SecretStr(_TOKEN) if with_token else None,
    )


async def _make_shipped_order_with_contact(
    session_factory: async_sessionmaker[AsyncSession], *, chat_id: int | None = 555
) -> None:
    async with session_factory() as session:
        owner = await get_or_create_owner(session, external_id=_OWNER_EXTERNAL_ID)
        commerce = CommerceRepository(session, owner_id=owner.id)
        contact = await commerce.get_or_create_contact_by_chat_id(
            chat_id=chat_id or 0, display_name="Mijoz"
        )
        if chat_id is None:
            contact.telegram_chat_id = None
        order = await commerce.create_order(
            items=[OrderItem(name="Krossovka", quantity=1, unit_price_uzs=250_000)],
            contact_id=contact.id,
        )
        await commerce.update_order_status(order.id, OrderStatus.SHIPPED)
        await session.commit()


class TestSuccessfulNotification:
    @respx.mock
    async def test_shipped_order_gets_notified_and_marked(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        await _make_shipped_order_with_contact(session_factory)
        daemon = ShipmentNotifyDaemon(session_factory=session_factory, settings=_settings())

        notified = await daemon.tick()

        assert len(notified) == 1
        assert route.called
        await daemon.aclose()

    @respx.mock
    async def test_second_tick_does_not_resend(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        await _make_shipped_order_with_contact(session_factory)
        daemon = ShipmentNotifyDaemon(session_factory=session_factory, settings=_settings())

        await daemon.tick()
        second = await daemon.tick()

        assert second == []
        assert route.call_count == 1
        await daemon.aclose()


class TestSkippedWithoutError:
    @respx.mock
    async def test_contact_without_chat_id_is_skipped(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        route = respx.post(_API).mock(return_value=httpx.Response(200, json={"ok": True}))
        await _make_shipped_order_with_contact(session_factory, chat_id=None)
        daemon = ShipmentNotifyDaemon(session_factory=session_factory, settings=_settings())

        notified = await daemon.tick()

        assert notified == []
        assert not route.called
        await daemon.aclose()

    async def test_missing_token_does_not_crash(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _make_shipped_order_with_contact(session_factory)
        daemon = ShipmentNotifyDaemon(
            session_factory=session_factory, settings=_settings(with_token=False)
        )

        notified = await daemon.tick()

        assert notified == []
        await daemon.aclose()


class TestTelegramFailureRetries:
    @respx.mock
    async def test_failed_send_leaves_order_awaiting(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        respx.post(_API).mock(return_value=httpx.Response(500))
        await _make_shipped_order_with_contact(session_factory)
        daemon = ShipmentNotifyDaemon(session_factory=session_factory, settings=_settings())

        notified = await daemon.tick()

        assert notified == []
        async with session_factory() as session:
            owner = await get_or_create_owner(session, external_id=_OWNER_EXTERNAL_ID)
            commerce = CommerceRepository(session, owner_id=owner.id)
            still_awaiting = await commerce.orders_awaiting_shipment_notice()
            assert len(still_awaiting) == 1
        await daemon.aclose()


class TestNoShippedOrders:
    async def test_empty_when_nothing_shipped(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        daemon = ShipmentNotifyDaemon(session_factory=session_factory, settings=_settings())

        notified = await daemon.tick()

        assert notified == []
        await daemon.aclose()
