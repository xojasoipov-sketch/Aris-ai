"""AlertsDaemon wiring testlari — AUDIT #14 davomi.

`AlertNotificationBridge.check_metric()` va `AlertManager.check_metric()`
oldindan mavjud edi, biroq ularni davriy metrika bilan chaqiradigan hech
qanday joy yo'q edi ("dead wiring"). Bu testlar daemon:

    1. Sog'lom baza uchun hech qanday alert yubormasligini,
    2. Cost budjetdan oshsa alert yuborishini,
    3. Notifier haqiqatan chaqirilishini,
    4. Cooldown ichida takroriy alert yubormasligini (AlertRule.cooldown_s),
    5. DB xatosi tick'ni yiqitmasligini (fail-open)

isbotlaydi.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.db.models import CostLedger, Run, ToolCall
from zet.deploy.alerts_daemon import (
    METRIC_COST_DAILY_PCT,
    METRIC_TOOL_ERROR_RATE,
    METRIC_VERIFIED_OK_RATE,
    AlertsDaemon,
    default_rules,
)
from zet.domain.enums import (
    ModelTier,
    PermissionLevel,
    RunStatus,
    TaskClass,
    TrustLevel,
)
from zet.monitoring.alerts import AlertManager, AlertRule, AlertSeverity
from zet.monitoring.notify_bridge import AlertNotificationBridge
from zet.telegram.notifier import Notification, StubNotifier

_OWNER = "alerts-daemon-test"


def _settings(*, budget: float = 1.0) -> Settings:
    return Settings(
        _env_file=None,
        owner_id=_OWNER,
        timezone="UTC",
        budget_daily_usd=budget,
        budget_monthly_usd=max(budget * 30.0, budget),
    )


def _bridge_with_rules(
    *rules: AlertRule,
) -> tuple[AlertNotificationBridge, StubNotifier, AlertManager]:
    """Yordamchi: AlertManager + StubNotifier + Bridge yig'adi."""
    manager = AlertManager()
    for rule in rules:
        manager.add_rule(rule)
    notifier = StubNotifier()
    bridge = AlertNotificationBridge(alerts=manager, notifier=notifier)
    return bridge, notifier, manager


async def _seed_cost(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    usd: float,
    ok: bool = True,
    verified_ok: bool | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            CostLedger(
                run_id=uuid.uuid4(),
                provider="test",
                model="test-model",
                tier=ModelTier.T2_CHEAP,
                task_class=TaskClass.NORMAL,
                input_tokens=10,
                output_tokens=10,
                usd=usd,
                latency_ms=10,
                ok=ok,
                verified_ok=verified_ok,
            )
        )
        await session.commit()


async def _seed_tool_calls(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    total: int,
    errors: int,
    tool_name: str = "probe.tool",
) -> None:
    """Bitta owner + har chaqiruv uchun Run + ToolCall qo'shadi."""
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


class TestHealthyBaseline:
    async def test_no_alerts_when_metrics_healthy(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Bo'sh baza + kichik sarf → hech qanday alert yuborilmaydi."""
        bridge, notifier, manager = _bridge_with_rules(*default_rules())
        # Kunlik budjetning atigi 1% i sarflangan — barcha chegaralardan
        # ancha past.
        await _seed_cost(session_factory, usd=0.01, verified_ok=True)

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=10.0),
        )

        measured = await daemon.tick(now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))

        assert notifier.count == 0
        assert manager.list_alerts() == []
        # Cost o'lchandi — 0.01 / 10 * 100 = 0.1%
        assert measured[METRIC_COST_DAILY_PCT] is not None
        assert measured[METRIC_COST_DAILY_PCT] < 1.0
        # Tool/verified — 5 dan kam namuna → None (silence)
        assert measured[METRIC_TOOL_ERROR_RATE] is None
        assert measured[METRIC_VERIFIED_OK_RATE] is None


class TestCostAlert:
    async def test_fires_alert_when_cost_over_threshold(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Kunlik budjetning 90% i sarflansa cost_daily_pct > 80 → alert."""
        bridge, _notifier, manager = _bridge_with_rules(*default_rules())
        # Budjet 1 USD, sarf 0.9 USD → 90%
        await _seed_cost(session_factory, usd=0.9)

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=1.0),
        )

        measured = await daemon.tick(now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))

        assert measured[METRIC_COST_DAILY_PCT] == pytest.approx(90.0)
        # Aynan bitta alert — cost qoidasi bilan
        alerts = manager.list_alerts()
        assert len(alerts) == 1
        assert alerts[0].metric_name == METRIC_COST_DAILY_PCT
        assert alerts[0].severity == AlertSeverity.WARNING

    async def test_notifier_is_called_with_formatted_alert(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Alert paydo bo'lganda Notifier haqiqatan chaqiriladi (bridge orqali)."""
        bridge, notifier, _ = _bridge_with_rules(*default_rules())
        await _seed_cost(session_factory, usd=0.95)

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=1.0),
        )

        await daemon.tick(now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))

        assert notifier.count == 1
        text = notifier.sent[0].text
        # Format: `{icon} {rule_name}: {rule_name}: {metric_name} = {value} ...`
        assert METRIC_COST_DAILY_PCT in text
        assert "budjet" in text.lower()


class TestCooldownDedup:
    async def test_same_alert_not_fired_twice_in_cooldown(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Ikkinchi tick cooldown ichida — takroriy notifikatsiya YO'Q."""
        # Katta cooldown — ikkinchi tick albatta uning ichida qoladi.
        bridge, notifier, manager = _bridge_with_rules(
            AlertRule(
                name="cost-high",
                metric_name=METRIC_COST_DAILY_PCT,
                threshold=50.0,
                operator="gt",
                cooldown_s=3600,
            )
        )
        await _seed_cost(session_factory, usd=0.9)

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=1.0),
        )

        await daemon.tick(now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))
        await daemon.tick(now=datetime(2026, 8, 13, 12, 0, 30, tzinfo=UTC))
        await daemon.tick(now=datetime(2026, 8, 13, 12, 1, 0, tzinfo=UTC))

        assert notifier.count == 1
        assert len(manager.list_alerts()) == 1


class TestFailOpen:
    async def test_db_error_does_not_crash_tick(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """DB session ochilmasa ham tick istisno ko'tarmaydi (fail-open).

        Barcha uch metrika DB'ga tegadi — session_factory yiqilsa uchtasi
        ham `None` qaytadi va bridge chaqirilmaydi. Tsikl davom etadi.
        """
        bridge, notifier, manager = _bridge_with_rules(*default_rules())

        def _broken_factory() -> AsyncIterator[AsyncSession]:  # pragma: no cover - shakl uchun
            raise RuntimeError("db down")

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=_broken_factory,  # type: ignore[arg-type]
            settings=_settings(budget=1.0),
        )

        # Istisno YO'Q — hammasi ushlanadi
        measured = await daemon.tick(now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))

        assert measured[METRIC_COST_DAILY_PCT] is None
        assert measured[METRIC_TOOL_ERROR_RATE] is None
        assert measured[METRIC_VERIFIED_OK_RATE] is None
        assert notifier.count == 0
        assert manager.list_alerts() == []

    async def test_notifier_failure_does_not_crash_tick(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Notifier yiqilsa alert AlertManager'da qoladi, tick davom etadi."""

        class _Exploding(StubNotifier):
            async def send(self, notification: Notification) -> bool:
                raise RuntimeError("network down")

        manager = AlertManager()
        for rule in default_rules():
            manager.add_rule(rule)
        bridge = AlertNotificationBridge(alerts=manager, notifier=_Exploding())
        await _seed_cost(session_factory, usd=0.95)

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=1.0),
        )

        # Istisno YO'Q
        await daemon.tick(now=datetime(2026, 8, 13, 12, 0, tzinfo=UTC))

        # Notifier tushdi, biroq alert qayd etilgan
        assert len(manager.list_alerts()) == 1


class TestVerifiedAndToolMetrics:
    """Boshqa ikki metrikaning ham haqiqatan hisoblanishini isbotlaydi."""

    async def test_tool_error_rate_triggers(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """10 chaqiruvdan 6 tasi xato → tool_error_rate=60 > 30 → alert."""
        bridge, notifier, manager = _bridge_with_rules(*default_rules())
        await _seed_tool_calls(session_factory, total=10, errors=6)

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=10.0),  # cost past — faqat tool signal
        )

        measured = await daemon.tick(now=datetime.now(tz=UTC))

        assert measured[METRIC_TOOL_ERROR_RATE] == pytest.approx(60.0)
        assert any(a.metric_name == METRIC_TOOL_ERROR_RATE for a in manager.list_alerts()), (
            "tool_error_rate uchun alert kelmadi"
        )
        assert notifier.count >= 1

    async def test_verified_ok_rate_triggers_on_low_pass(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """10 verified'dan 4 tasi ok (40%) < 70 → alert (operator `lt`)."""
        bridge, notifier, manager = _bridge_with_rules(*default_rules())
        for i in range(10):
            await _seed_cost(
                session_factory,
                usd=0.001,  # cost signalidan uzoq
                verified_ok=(i < 4),
            )

        daemon = AlertsDaemon(
            bridge=bridge,
            session_factory=session_factory,
            settings=_settings(budget=10.0),
        )

        measured = await daemon.tick(now=datetime.now(tz=UTC))

        assert measured[METRIC_VERIFIED_OK_RATE] == pytest.approx(40.0)
        assert any(a.metric_name == METRIC_VERIFIED_OK_RATE for a in manager.list_alerts()), (
            "verified_ok_rate uchun alert kelmadi"
        )
        assert notifier.count >= 1


class TestDefaultRules:
    def test_default_rules_cover_three_signals(self) -> None:
        """Bootstrap qoidalari uchta metrika nomi bilan mos keladi."""
        names = {r.metric_name for r in default_rules()}
        assert names == {
            METRIC_COST_DAILY_PCT,
            METRIC_TOOL_ERROR_RATE,
            METRIC_VERIFIED_OK_RATE,
        }

    def test_verified_rule_uses_lt_operator(self) -> None:
        """Verified `lt` operator ishlatishi kerak (past ulush = yomon)."""
        rules = {r.metric_name: r for r in default_rules()}
        assert rules[METRIC_VERIFIED_OK_RATE].operator == "lt"
        assert rules[METRIC_COST_DAILY_PCT].operator == "gt"
        assert rules[METRIC_TOOL_ERROR_RATE].operator == "gt"
