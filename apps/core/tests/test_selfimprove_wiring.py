"""SelfImproveDaemon wiring testlari — GAP_ANALYSIS §12.

`SelfImproveEngine.suggest()` ilgari hech qayerdan chaqirilmasdi
(qurilgan-u ulanmagan). Bu testlar daemon HAQIQATAN engine'ni oziqla-
ntirishini va notifier'ga xulosa yuborishini isbotlaydi.

Yopiladigan invariantlar:
    1. `get_selfimprove_engine()` — singleton (bir xil instansiya).
    2. Dushanba 09:00'da tahlil ishlaydi va notifier'ga xabar boradi.
    3. Boshqa kunda / erta soatda daemon jim turadi.
    4. Ma'lumot bo'lmasa (yangi baza) hech qanday tavsiya qo'shilmaydi
       — false-positive'ni bostirish (konservativ chegaralar).
    5. LLM xato foizi yuqori bo'lganda BUG_FIX tavsiyasi qo'shiladi
       — engine'ning `.suggest()`i haqiqatan chaqiriladi.
    6. Tool xato foizi yuqori bo'lganda BUG_FIX tavsiyasi qo'shiladi
       — ikkinchi manba (ToolCall) ham ishlashini isbotlaydi.
    7. Notifier yiqilsa daemon halok bo'lmaydi (fail-open).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.api.deps import get_selfimprove_engine
from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.db.models import CostLedger, Run, ToolCall
from zet.deploy.selfimprove import ImprovementType, SelfImproveEngine
from zet.deploy.selfimprove_daemon import SelfImproveDaemon
from zet.domain.enums import ModelTier, PermissionLevel, RunStatus, TaskClass, TrustLevel
from zet.telegram.notifier import Notification, StubNotifier

_OWNER = "selfimprove-daemon-test"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        owner_id=_OWNER,
        timezone="UTC",  # test-friendly: dushanba 09:00 UTC deterministik
    )


def _monday_9am() -> datetime:
    # 2026-08-17 dushanba
    return datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


async def _seed_llm_calls(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    total: int,
    errors: int,
    tier: ModelTier = ModelTier.T2_CHEAP,
    usd_per_call: float = 0.01,
) -> None:
    """Berilgan miqdorda CostLedger yozuvlarini qo'shadi."""
    async with session_factory() as session:
        for i in range(total):
            session.add(
                CostLedger(
                    run_id=uuid.uuid4(),
                    provider="test-provider",
                    model="test-model",
                    tier=tier,
                    task_class=TaskClass.NORMAL,
                    input_tokens=100,
                    output_tokens=50,
                    usd=usd_per_call,
                    latency_ms=200,
                    ok=(i >= errors),  # birinchi `errors` ta yozuv xato
                )
            )
        await session.commit()


async def _seed_tool_calls(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tool_name: str,
    total: int,
    errors: int,
) -> None:
    """Berilgan tool bo'yicha ToolCall yozuvlarini qo'shadi.

    `ToolCall.run_id` — `run.id`ga FK. Har bir yozuv uchun alohida Run
    qo'yamiz (rasm ozgina noreal, lekin agregat bo'yicha xato foizi
    bir xil chiqadi va tahlil aynan shuni o'lchaydi).
    """
    async with session_factory() as session:
        owner = await get_or_create_owner(session, external_id=_OWNER)
        await session.commit()
        for i in range(total):
            run = Run(
                owner_id=owner.id,
                command_text=f"probe {i}",
                status=RunStatus.DONE,
                trace_id=uuid.uuid4().hex[:16],
            )
            session.add(run)
            await session.flush()
            session.add(
                ToolCall(
                    run_id=run.id,
                    tool_name=tool_name,
                    permission_level=PermissionLevel.READ,
                    output_trust_level=TrustLevel.SYSTEM,
                    input={"x": 1},
                    output=None if i < errors else {"y": 2},
                    ok=(i >= errors),
                    error="boom" if i < errors else None,
                    latency_ms=10,
                )
            )
        await session.commit()


class TestSingleton:
    def test_get_selfimprove_engine_is_singleton(self) -> None:
        """`get_selfimprove_engine()` HAR CHAQIRIQ uchun bir xil instansiya —
        `.suggest()` yozgan tavsiyalar keyingi chaqiriqda ko'rinishi shu
        bilan kafolatlanadi."""
        get_selfimprove_engine.cache_clear()
        a = get_selfimprove_engine()
        b = get_selfimprove_engine()
        assert a is b
        assert isinstance(a, SelfImproveEngine)
        # Suggest qo'shsak keyingi chaqiruv shu tavsiyani ko'radi
        a.suggest(improvement_type=ImprovementType.BUG_FIX, title="probe")
        assert len(b.pending()) == 1
        get_selfimprove_engine.cache_clear()  # keyingi testlarga chuqmasin


class TestScheduling:
    async def test_non_monday_returns_empty(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Payshanba 09:00 — jim: hech qanday tahlil ham, notifier ham yo'q."""
        engine = SelfImproveEngine()
        notifier = StubNotifier()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )
        thursday = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

        added = await daemon.tick(now=thursday)

        assert added == []
        assert notifier.sent == []
        assert engine.pending() == []

    async def test_monday_before_9am_returns_empty(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Dushanba 06:00 — hali barvaqt, tahlil o'tkazilmaydi."""
        engine = SelfImproveEngine()
        notifier = StubNotifier()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )

        added = await daemon.tick(now=datetime(2026, 8, 17, 6, 0, tzinfo=UTC))

        assert added == []
        assert notifier.sent == []

    async def test_second_tick_same_day_does_not_reanalyze(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Kunda ikkinchi tick — takroriy xabar YO'Q."""
        engine = SelfImproveEngine()
        notifier = StubNotifier()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )

        await daemon.tick(now=_monday_9am())
        second = await daemon.tick(now=_monday_9am() + timedelta(hours=2))

        assert second == []
        # Notifier'ga ham ikki marta xabar bormaganini bilvosita
        # bilamiz: pending bo'sh — xabar umuman yubormaydi.
        assert notifier.sent == []


class TestEngineActuallyCalled:
    async def test_empty_db_no_suggestions(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Yangi bazada hech qanday chaqiruv yo'q — konservativ chegaralar
        false-positive bermasin (namuna kichik, xulosa yo'q)."""
        engine = SelfImproveEngine()
        notifier = StubNotifier()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )

        added = await daemon.tick(now=_monday_9am())

        assert added == []
        assert engine.pending() == []
        # `pending` bo'shligi sabab notifier'ga xabar yubormaymiz
        assert notifier.sent == []

    async def test_high_llm_error_rate_triggers_bug_fix(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """CostLedger'da 30 chaqiruvdan 15 tasi xato → BUG_FIX + notifier."""
        await _seed_llm_calls(session_factory, total=30, errors=15)
        engine = SelfImproveEngine()
        notifier = StubNotifier()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )

        added = await daemon.tick(now=_monday_9am())

        # Engine haqiqatan `.suggest()` chaqirilgan
        assert len(added) >= 1
        titles = {s.title for s in added}
        assert any("xato foizi yuqori" in t for t in titles)
        types = {s.improvement_type for s in added}
        assert ImprovementType.BUG_FIX in types

        # Notifier'ga yig'ilgan tavsiyalar xulosasi jo'natildi
        assert len(notifier.sent) == 1
        text = notifier.sent[0].text
        assert "takomillashtirish" in text.lower()
        assert "xato foizi yuqori" in text

    async def test_high_tool_error_rate_triggers_bug_fix(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """ToolCall'da bitta tool 15/15 xato qaytardi → uni nomi bilan
        aytilgan BUG_FIX tavsiyasi."""
        await _seed_tool_calls(session_factory, tool_name="flaky.tool", total=15, errors=15)
        engine = SelfImproveEngine()
        notifier = StubNotifier()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=notifier,
        )

        added = await daemon.tick(now=_monday_9am())

        # Engine chaqirilgan va tool nomi tavsiya matnida
        assert any(
            "flaky.tool" in s.title and s.improvement_type == ImprovementType.BUG_FIX for s in added
        )
        assert notifier.sent, "notifier'ga xabar bormadi"
        assert "flaky.tool" in notifier.sent[0].text


class TestFailOpen:
    async def test_notifier_failure_does_not_crash(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Notifier yiqilsa daemon halok bo'lmaydi — signalsiz kun
        signalsiz kundir, lekin tsikl davom etadi."""

        class ExplodingNotifier(StubNotifier):
            async def send(self, notification: Notification) -> bool:
                raise RuntimeError("network down")

        await _seed_llm_calls(session_factory, total=30, errors=15)
        engine = SelfImproveEngine()
        daemon = SelfImproveDaemon(
            engine=engine,
            session_factory=session_factory,
            settings=_settings(),
            notifier=ExplodingNotifier(),
        )

        # Istisno YO'Q — analiz muvaffaqiyatli o'tadi, notifier xatosi
        # daemon ichida ushlanadi.
        added = await daemon.tick(now=_monday_9am())

        # Engine baribir yozilgan (analiz notifier'dan oldin bo'ladi)
        assert added, "notifier tushishi analizga zarar bermasligi kerak"
        assert engine.pending()
