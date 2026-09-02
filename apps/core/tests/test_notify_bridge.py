"""AlertNotificationBridge testlari — gap-analysis #14 (AlertManager → Notifier)."""

from __future__ import annotations

from zet.monitoring.alerts import AlertManager, AlertRule, AlertSeverity
from zet.monitoring.notify_bridge import AlertNotificationBridge, format_alert
from zet.telegram.notifier import StubNotifier


class TestAlertNotificationBridge:
    async def test_fire_manual_sends_notification(self) -> None:
        alerts = AlertManager()
        notifier = StubNotifier()
        bridge = AlertNotificationBridge(alerts=alerts, notifier=notifier)

        alert = await bridge.fire_manual(
            name="Test", message="Diqqat", severity=AlertSeverity.CRITICAL
        )

        assert notifier.count == 1
        assert "Diqqat" in notifier.sent[0].text
        assert alert.severity == AlertSeverity.CRITICAL

    async def test_check_metric_sends_notification_on_new_alert(self) -> None:
        alerts = AlertManager()
        alerts.add_rule(
            AlertRule(name="budget_high", metric_name="budget_pct", threshold=80.0, operator="gt")
        )
        notifier = StubNotifier()
        bridge = AlertNotificationBridge(alerts=alerts, notifier=notifier)

        new_alerts = await bridge.check_metric("budget_pct", 95.0)

        assert len(new_alerts) == 1
        assert notifier.count == 1

    async def test_check_metric_no_alert_no_notification(self) -> None:
        alerts = AlertManager()
        alerts.add_rule(
            AlertRule(name="budget_high", metric_name="budget_pct", threshold=80.0, operator="gt")
        )
        notifier = StubNotifier()
        bridge = AlertNotificationBridge(alerts=alerts, notifier=notifier)

        new_alerts = await bridge.check_metric("budget_pct", 10.0)

        assert new_alerts == []
        assert notifier.count == 0

    async def test_cooldown_respected_across_bridge(self) -> None:
        alerts = AlertManager()
        alerts.add_rule(
            AlertRule(
                name="budget_high",
                metric_name="budget_pct",
                threshold=80.0,
                operator="gt",
                cooldown_s=300,
            )
        )
        notifier = StubNotifier()
        bridge = AlertNotificationBridge(alerts=alerts, notifier=notifier)

        await bridge.check_metric("budget_pct", 95.0)
        await bridge.check_metric("budget_pct", 96.0)  # cooldown ichida

        assert notifier.count == 1

    async def test_notifier_failure_does_not_raise(self) -> None:
        """Yuborish xatosi alert yaratishni bekor qilmaydi."""

        class _FailingNotifier(StubNotifier):
            async def send(self, notification: object) -> bool:  # type: ignore[override]
                raise RuntimeError("network down")

        alerts = AlertManager()
        bridge = AlertNotificationBridge(alerts=alerts, notifier=_FailingNotifier())

        alert = await bridge.fire_manual(name="Test", message="x")
        assert alert is not None
        assert len(alerts.list_alerts()) == 1

    def test_bridge_exposes_underlying_manager(self) -> None:
        alerts = AlertManager()
        bridge = AlertNotificationBridge(alerts=alerts, notifier=StubNotifier())
        assert bridge.alerts is alerts

    def test_format_alert_includes_severity_icon(self) -> None:
        from zet.monitoring.alerts import Alert

        critical = Alert(rule_name="X", severity=AlertSeverity.CRITICAL, message="y")
        assert "🔴" in format_alert(critical)

        info = Alert(rule_name="X", severity=AlertSeverity.INFO, message="y")
        assert "ℹ️" in format_alert(info)  # noqa: RUF001
