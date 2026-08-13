"""ReportsDaemon testlari — haftalik/oylik sotuv+faollik hisoboti (#45).

Tekshiriladi:
    - Dushanba 09:00'da haftalik yuboriladi
    - 1-sana 09:00'da oylik yuboriladi
    - Bir kunda ikki marta chaqirilsa faqat BIR marta yuboriladi
    - 09:00'dan oldin (masalan 06:00) hech narsa yuborilmaydi
    - Notifier xatosi butun daemon'ni to'xtatmaydi
    - LLM bo'lmasa (llm_providers=None) — raqamlar bo'lsa ham yuboradi,
      faqat "Takliflar" bo'limi bo'lmaydi
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.commerce.repository import CommerceRepository
from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.deploy.reports_daemon import ReportsDaemon
from zet.domain.commerce import OrderItem, OrderStatus
from zet.telegram.notifier import StubNotifier

_OWNER = "reports-daemon-test"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        owner_id=_OWNER,
        timezone="UTC",  # test-friendly
    )


async def _seed_delivered_order(
    session_factory: async_sessionmaker[AsyncSession], amount: float = 100_000
) -> None:
    async with session_factory() as session:
        owner = await get_or_create_owner(session, external_id=_OWNER)
        commerce = CommerceRepository(session, owner_id=owner.id)
        order = await commerce.create_order(
            items=[OrderItem(name="Test", quantity=1, unit_price_uzs=amount)],
        )
        await commerce.update_order_status(order.id, OrderStatus.DELIVERED)
        await session.commit()


class TestScheduling:
    async def test_monday_at_9am_sends_weekly(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        # 2026-08-17 dushanba, 09:00 UTC
        monday_9am = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)

        sent = await daemon.tick(now=monday_9am)

        assert sent == ["weekly"]
        assert len(notifier.sent) == 1
        assert "Haftalik hisobot" in notifier.sent[0].text

    async def test_first_of_month_sends_monthly(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        # 2026-09-01 seshanba (dushanba emas), 09:00 UTC
        first_of_month = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)

        sent = await daemon.tick(now=first_of_month)

        assert sent == ["monthly"]
        assert "Oylik hisobot" in notifier.sent[0].text

    async def test_monday_and_first_of_month_sends_both(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Kamdan-kam holat — dushanba + 1-sana bir kunda mos kelsa (masalan
        2026-06-01), ikkalasi ham yuboriladi."""
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        # 2026-06-01 dushanba, 09:00 UTC
        double_day = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

        sent = await daemon.tick(now=double_day)

        assert set(sent) == {"weekly", "monthly"}
        assert len(notifier.sent) == 2

    async def test_before_9am_no_report(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        monday_early = datetime(2026, 8, 17, 6, 0, tzinfo=UTC)

        sent = await daemon.tick(now=monday_early)

        assert sent == []
        assert notifier.sent == []

    async def test_second_tick_same_day_does_not_resend(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        monday_9am = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        monday_10am = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)

        await daemon.tick(now=monday_9am)
        second = await daemon.tick(now=monday_10am)

        assert second == []
        assert len(notifier.sent) == 1

    async def test_regular_weekday_sends_nothing(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        # 2026-08-20 payshanba, 09:00 UTC — hech qanday sana mos kelmaydi
        thursday = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

        sent = await daemon.tick(now=thursday)

        assert sent == []


class TestNumbers:
    async def test_delivered_sales_appear_in_body(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        await _seed_delivered_order(session_factory, amount=250_000)
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        await daemon.tick(now=datetime(2026, 8, 17, 9, 0, tzinfo=UTC))

        text = notifier.sent[0].text
        assert "250,000" in text
        assert "yetkazilgan" in text.lower()


class TestFailOpen:
    async def test_notifier_failure_does_not_crash(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        from zet.telegram.notifier import Notification

        class ExplodingNotifier(StubNotifier):
            async def send(self, notification: Notification) -> bool:
                raise RuntimeError("network down")

        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=ExplodingNotifier(),
        )
        # Xato bo'lmasligi kerak
        await daemon.tick(now=datetime(2026, 8, 17, 9, 0, tzinfo=UTC))

    async def test_no_llm_still_sends_numbers(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        notifier = StubNotifier()
        daemon = ReportsDaemon(
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
            llm_providers=None,  # taklif bo'limi bo'lmaydi
        )
        await daemon.tick(now=datetime(2026, 8, 17, 9, 0, tzinfo=UTC))

        text = notifier.sent[0].text
        assert "Raqamlar" in text
        assert "Takliflar" not in text
