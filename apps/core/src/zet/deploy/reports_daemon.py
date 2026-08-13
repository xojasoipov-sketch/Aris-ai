"""Haftalik va oylik sotuv+faollik hisoboti — daemon (#45).

Har kuni bir marta (odatda 09:00 Toshkent) tekshiradi:
    - Bugun DUSHANBA bo'lsa → HAFTALIK hisobot yuboriladi
    - Bugun oyning 1-KUNI bo'lsa → OYLIK hisobot yuboriladi

Har bir hisobot 3 bo'lim'dan iborat:
    1. RAQAMLAR — sotuv jami (faqat DELIVERED), buyurtmalar soni holat
       bo'yicha, yangi kontaktlar soni (deterministik, baza asosida).
    2. FAOLLIK — kanal a'zolar soni o'zgarishi (agar `telegram.channel_stats`
       tool va bot sozlangan bo'lsa). Ma'lumot bo'lmasa "ulanmagan" deb yoziladi.
    3. TAKLIFLAR — LLM (fast tier) tomonidan raqamlar asosida generatsiya
       qilingan 3-5 ta o'sish taklifi. LLM javob bermasa bu bo'lim
       o'tkazib yuboriladi (halol) — asosiy raqamlar YO'QOLMAYDI.

Idempotentlik: daemon bir kunda ko'p marta ishga tushsa ham hisobot
faqat BIR MARTA yuboriladi (`_last_sent` dict — kun yakunida yangilanadi;
restart'dan keyin ba'zan takroriy xabar bo'lishi mumkin — bu qabul
qilinadigan darajada, chunki hisobot passiv ma'lumot).

Bog'liq qarorlar:
    Z51 — commerce/repository.py:sales_total_uzs
    A-01 — holat bazaga saqlanadi
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.commerce.repository import CommerceRepository
from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.crm import CRMContact
from zet.db.session import session_scope
from zet.domain.commerce import OrderStatus
from zet.domain.enums import TaskClass
from zet.llm.base import ChatMessage, LLMError, LLMProvider
from zet.llm.router import ModelRouter
from zet.telegram.notifier import Notifier

log = structlog.get_logger(__name__)

DEFAULT_TICK_SECONDS = 3600
"""Bir soatda bir marta tekshirish yetarli — jadval kunlik/haftalik/oylik."""

DEFAULT_SEND_HOUR = 9
"""Toshkent bo'yicha soati (09:00). Ega ishga o'tirishdan oldin ko'radi."""


class ReportsDaemon:
    """Haftalik/oylik hisobotni egaga avtomatik yuboruvchi fon tsikli."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        notifier: Notifier,
        llm_providers: dict[str, LLMProvider] | None = None,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        send_hour: int = DEFAULT_SEND_HOUR,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._notifier = notifier
        self._llm_providers = llm_providers
        self._tick_seconds = tick_seconds
        self._send_hour = send_hour
        self._tz = ZoneInfo(settings.timezone)
        self._last_sent: dict[str, date] = {}
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def run_forever(self) -> None:
        log.info("reports_daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("reports_daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("reports_daemon.stopped")

    async def tick(self, *, now: datetime | None = None) -> list[str]:
        """Bitta tekshiruv — vaqti kelgan hisobot(lar)ni yuboradi.

        Returns:
            Yuborilgan hisobot turlari (["weekly"], ["monthly"], yoki ikkalasi).
        """
        current = now or datetime.now(tz=self._tz)
        if current.hour < self._send_hour:
            return []

        sent: list[str] = []
        today = current.date()

        # Dushanba (Python: 0=Monday) — haftalik
        if current.weekday() == 0 and self._last_sent.get("weekly") != today:
            self._last_sent["weekly"] = today
            await self._send_report("weekly", days=7)
            sent.append("weekly")

        # Oyning 1-kuni — oylik
        if current.day == 1 and self._last_sent.get("monthly") != today:
            self._last_sent["monthly"] = today
            await self._send_report("monthly", days=30)
            sent.append("monthly")

        return sent

    async def _send_report(self, period: str, *, days: int) -> None:
        """Berilgan davr uchun hisobot tayyorlaydi va notifier orqali yuboradi."""
        title = "📊 Haftalik hisobot" if period == "weekly" else "📈 Oylik hisobot"
        since = datetime.now(tz=UTC) - timedelta(days=days)

        try:
            numbers = await self._compute_numbers(since=since)
        except Exception:
            log.exception("reports_daemon.compute_failed", period=period)
            return

        body_parts = [f"{title} ({days} kun)\n", "🔢 <b>Raqamlar</b>", numbers]

        activity = await self._activity_line()
        if activity:
            body_parts.append(f"\n📣 <b>Faollik</b>\n{activity}")

        suggestions = await self._suggest_growth(period=period, numbers=numbers, activity=activity)
        if suggestions:
            body_parts.append(f"\n💡 <b>Takliflar</b>\n{suggestions}")

        text = "\n".join(body_parts)
        try:
            await self._notifier.send_text(text)
            log.info("reports_daemon.sent", period=period)
        except Exception:
            log.warning("reports_daemon.notify_failed", period=period)

    async def _compute_numbers(self, *, since: datetime) -> str:
        """Baza asosida deterministik raqamlar — DELIVERED sales + orders + kontaktlar."""
        async with session_scope(self._session_factory) as session:
            owner = await get_or_create_owner(session, external_id=self._settings.owner_id)
            commerce = CommerceRepository(session, owner_id=owner.id)

            sales = await commerce.sales_total_uzs(since=since)
            all_orders = await commerce.list_orders(since=since, limit=1000)
            status_counts: dict[OrderStatus, int] = {}
            for o in all_orders:
                status_counts[o.status] = status_counts.get(o.status, 0) + 1

            new_contacts = await _count_new_contacts(session, owner_id=owner.id, since=since)

        lines = [
            f"• Sotuv (yetkazilgan): {sales:,.0f} so'm",
            f"• Buyurtmalar jami: {len(all_orders)}",
        ]
        for status in OrderStatus:
            n = status_counts.get(status, 0)
            if n:
                lines.append(f"  · {status.value}: {n}")
        lines.append(f"• Yangi mijozlar (CRM): {new_contacts}")
        return "\n".join(lines)

    async def _activity_line(self) -> str:
        """Telegram kanal a'zolari o'zgarishi (agar konfiguratsiya bo'lsa)."""
        if self._settings.telegram_bot_token is None:
            return ""
        # Kanal chat_id `.env` da alohida ko'rsatilmagan bo'lishi mumkin —
        # bu daemon konfiguratsiyaviy majburiyat qo'ymaydi, mavjud bo'lsa
        # foydalanadi. Hozircha "ulanmagan" deb yozamiz, chunki kanal
        # chat_id sozlamasi hozircha yo'q (kelajakda ZET_MAIN_CHANNEL_ID
        # kabi maydon qo'shilsa — shu yerga ulanadi).
        return "kanal statistikasi ulanmagan (kanal ID sozlanmagan)"

    async def _suggest_growth(self, *, period: str, numbers: str, activity: str) -> str:
        """Raqamlar asosida LLM'dan 3-5 ta o'sish taklifi. Xato bo'lsa bo'sh."""
        if self._llm_providers is None:
            return ""
        try:
            async with session_scope(self._session_factory) as session:
                router = ModelRouter(self._llm_providers, session, self._settings)
                system = (
                    "Sen do'kon egasining biznes maslahatchisisan. Berilgan "
                    "raqamlar va faollik ma'lumoti asosida 3 dan 5 gacha "
                    "AMALIY o'sish taklifi ber. Har biri:\n"
                    " - qisqa (bir-ikki qatorda)\n"
                    " - AYNAN raqamlarga asoslangan (masalan 'buyurtmalar "
                    "10% pastroq — X ni sinang')\n"
                    " - o'zbek tilida\n"
                    "Umumiy gap yoki iqtibos yozma."
                )
                user = f"Davr: {period}\n\n{numbers}\n\n{activity or ''}"
                result = await router.complete(
                    task_class=TaskClass.SIMPLE,
                    messages=[ChatMessage(role="user", content=user)],
                    system=system,
                    max_tokens=500,
                    is_autonomous=True,
                )
                return result.response.text.strip()
        except LLMError:
            log.warning("reports_daemon.llm_unavailable", period=period)
            return ""


async def _count_new_contacts(session: AsyncSession, *, owner_id: object, since: datetime) -> int:
    """`crm_contact` jadvalidan `since` dan keyin yaratilganlar sonini qaytaradi."""
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(CRMContact)
        .where(
            CRMContact.owner_id == owner_id,
            CRMContact.created_at >= since,
        )
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return int(row or 0)


__all__ = ["DEFAULT_TICK_SECONDS", "ReportsDaemon"]
