"""Kargo chiqishi bilan mijozga avtomatik xabar — daemon (Z51, #43).

`OrderStatus.SHIPPED`ga o'tgan, lekin hali xabar yuborilmagan
buyurtmalarni davriy tekshiradi (`CommerceRepository.
orders_awaiting_shipment_notice()`) va HAR BIRIGA bitta marta
Telegram DM yuboradi.

NEGA LLM/AGENT ISHLATILMAYDI. Bu — mexanik, deterministik amal:
"buyurtma X jo'natildi" degan bitta shablon xabar. LLM chaqirish
faqat xato ehtimolini (gallyutsinatsiya, kechikish, narxni noto'g'ri
aytish) qo'shardi — hech qanday foyda bermasdan. `DailyScheduleDaemon`/
`AutomationDaemon`dan farqli o'laroq bu daemon agent runtime'ni
umuman bilmaydi.

NEGA SHOP BOT TOKENI, ZETBOT EMAS. Mijoz `ShopBot`ga yozgan — Telegram
Bot API faqat foydalanuvchi O'ZI BIRINCHI BO'LIB YOZGAN botdan xabar
qabul qiladi. Owner boti (`ZetBot`) bilan mijoz hech qachon
gaplashmagan, demak unga xabar yubora olmaydi.

IDEMPOTENTLIK: `Order.shipped_notified_at` faqat MUVAFFAQIYATLI
yuborishdan KEYIN yoziladi (oldin emas) — Telegram API xato bersa,
buyurtma navbatda qoladi va keyingi tick'da qayta urinib ko'riladi.

Bog'liq qarorlar:
    Z51 — domain/commerce.py: shipped_notified_at nega kerak
    A-01 — holat bazaga saqlanadi
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.commerce.repository import CommerceRepository
from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.commerce import Order
from zet.db.session import session_scope

log = structlog.get_logger(__name__)

DEFAULT_TICK_SECONDS = 120
"""Kargo holati soatlab emas, daqiqalab o'zgaradi — 2 daqiqa yetarli tezkor."""

_API_BASE = "https://api.telegram.org"


class ShipmentNotifyDaemon:
    """Yuborilgan buyurtmalar haqida mijozga xabar beruvchi fon tsikli.

    `run_forever()` — asyncio task sifatida ishga tushiriladi (FastAPI
    lifespan orqali). `tick()` — bitta tekshiruv, testlarda to'g'ridan-
    to'g'ri chaqiriladi (loop kutmasdan).
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._tick_seconds = tick_seconds
        self._client = client
        self._owns_client = client is None
        self._stop_event = asyncio.Event()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def stop(self) -> None:
        """Tsiklni keyingi tick oralig'ida to'xtatish."""
        self._stop_event.set()

    async def run_forever(self) -> None:
        """Doimiy tsikl — `stop()` chaqirilmaguncha ishlaydi."""
        log.info("shipment_daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("shipment_daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("shipment_daemon.stopped")

    async def tick(self) -> list[str]:
        """Bitta tekshiruv — navbatdagi buyurtmalarga xabar yuboradi.

        Returns:
            Xabar MUVAFFAQIYATLI yuborilgan buyurtma ID'lari (diagnostika/test uchun).
        """
        token = self._settings.shop_bot_token
        notified: list[str] = []

        async with session_scope(self._session_factory) as session:
            owner = await get_or_create_owner(session, external_id=self._settings.owner_id)
            commerce = CommerceRepository(session, owner_id=owner.id)
            orders = await commerce.orders_awaiting_shipment_notice()

            for order in orders:
                if order.contact_id is None:
                    # Kontaktsiz buyurtma — kimga yuborishni bilmaymiz.
                    # Xabarsiz "yuborilgan" deb belgilash yolg'on bo'lardi,
                    # shuning uchun shunchaki O'TKAZIB YUBORAMIZ (ega
                    # keyinroq contact_id bog'lasa, keyingi tick'da ketadi).
                    log.debug("shipment_daemon.no_contact", order_id=str(order.id))
                    continue

                contact = await commerce.get_contact(order.contact_id)
                if contact is None or contact.telegram_chat_id is None:
                    log.debug("shipment_daemon.contact_has_no_chat_id", order_id=str(order.id))
                    continue

                if token is None:
                    log.warning("shipment_daemon.no_token", order_id=str(order.id))
                    continue

                sent = await self._send(
                    token.get_secret_value(), contact.telegram_chat_id, _shipment_text(order)
                )
                if not sent:
                    continue  # keyingi tick'da qayta urinadi — notified_at YOZILMAYDI

                await commerce.mark_shipment_notified(order.id)
                notified.append(str(order.id))

        return notified

    async def _send(self, token: str, chat_id: int, text: str) -> bool:
        try:
            response = await self._get_client().post(
                f"{_API_BASE}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        except httpx.HTTPError as exc:
            log.warning("shipment_daemon.send_failed", error=str(exc))
            return False
        if response.status_code != 200:
            log.warning("shipment_daemon.send_rejected", status=response.status_code)
            return False
        return True


def _shipment_text(order: Order) -> str:
    names = ", ".join(str(item.get("name", "")) for item in order.items) or "buyurtmangiz"
    return (
        "Buyurtmangiz yo'lga chiqdi! 📦\n\n"
        f"{names}\n"
        f"Jami: {order.total_uzs:,.0f} so'm\n\n"
        "Tez orada yetib boradi. Savolingiz bo'lsa shu yerga yozing."
    )


__all__ = ["DEFAULT_TICK_SECONDS", "ShipmentNotifyDaemon"]
