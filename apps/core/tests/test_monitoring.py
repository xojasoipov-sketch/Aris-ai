"""Bo'lim 10 testlari — Monitoring (Health, Metrics, Alerts).

Test guruhlari:
    1. ComponentStatus — enum qiymatlari
    2. ComponentHealth — yaratish, maydonlar
    3. HealthReport — yaratish, is_healthy, unhealthy_components
    4. HealthChecker — register, check_all, check_one, xatolik
    5. MetricType — enum qiymatlari
    6. MetricSnapshot — yaratish, maydonlar, labels
    7. MetricsCollector — increment, set_gauge, get, snapshot, all_snapshots, reset, stats
    8. AlertSeverity — enum qiymatlari
    9. AlertRule — yaratish, evaluate (gt, lt, eq), disabled, noto'g'ri operator
    10. Alert — yaratish, maydonlar
    11. AlertManager — add_rule, check_metric, cooldown, fire_manual, acknowledge, stats
    12. Monitoring __init__ — exports
    13. Xavfsizlik invariantlari
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from zet.monitoring import (
    AlertManager,
    AlertRule,
    AlertSeverity,
    ComponentStatus,
    HealthChecker,
    HealthReport,
    MetricsCollector,
    MetricSnapshot,
)
from zet.monitoring.alerts import Alert
from zet.monitoring.health import ComponentHealth
from zet.monitoring.metrics import MetricType

# ─── 1. ComponentStatus ─────────────────────────────────────────


class TestComponentStatus:
    """ComponentStatus enum testlari."""

    def test_healthy_value(self) -> None:
        assert ComponentStatus.HEALTHY == "healthy"

    def test_degraded_value(self) -> None:
        assert ComponentStatus.DEGRADED == "degraded"

    def test_unhealthy_value(self) -> None:
        assert ComponentStatus.UNHEALTHY == "unhealthy"

    def test_unknown_value(self) -> None:
        assert ComponentStatus.UNKNOWN == "unknown"

    def test_four_statuses(self) -> None:
        assert len(ComponentStatus) == 4


# ─── 2. ComponentHealth ──────────────────────────────────────────


class TestComponentHealth:
    """ComponentHealth model testlari."""

    def test_create_healthy(self) -> None:
        h = ComponentHealth(name="db", status=ComponentStatus.HEALTHY)
        assert h.name == "db"
        assert h.status == ComponentStatus.HEALTHY
        assert h.message == ""
        assert h.response_ms == 0.0

    def test_create_with_message(self) -> None:
        h = ComponentHealth(
            name="llm",
            status=ComponentStatus.DEGRADED,
            message="Sekin javob",
            response_ms=1500.0,
        )
        assert h.message == "Sekin javob"
        assert h.response_ms == 1500.0

    def test_checked_at_auto(self) -> None:
        h = ComponentHealth(name="x", status=ComponentStatus.HEALTHY)
        assert isinstance(h.checked_at, datetime)

    def test_frozen(self) -> None:
        h = ComponentHealth(name="x", status=ComponentStatus.HEALTHY)
        with pytest.raises(ValidationError):
            h.name = "y"  # type: ignore[misc]


# ─── 3. HealthReport ────────────────────────────────────────────


class TestHealthReport:
    """HealthReport model testlari."""

    def test_empty_report(self) -> None:
        r = HealthReport(status=ComponentStatus.UNKNOWN)
        assert r.components == []
        assert not r.is_healthy

    def test_healthy_report(self) -> None:
        comps = [
            ComponentHealth(name="db", status=ComponentStatus.HEALTHY),
            ComponentHealth(name="llm", status=ComponentStatus.HEALTHY),
        ]
        r = HealthReport(status=ComponentStatus.HEALTHY, components=comps)
        assert r.is_healthy
        assert r.unhealthy_components == []

    def test_unhealthy_components(self) -> None:
        comps = [
            ComponentHealth(name="db", status=ComponentStatus.HEALTHY),
            ComponentHealth(name="llm", status=ComponentStatus.UNHEALTHY),
            ComponentHealth(name="budget", status=ComponentStatus.DEGRADED),
        ]
        r = HealthReport(status=ComponentStatus.UNHEALTHY, components=comps)
        assert not r.is_healthy
        names = [c.name for c in r.unhealthy_components]
        assert "llm" in names
        assert "budget" in names
        assert "db" not in names

    def test_frozen(self) -> None:
        r = HealthReport(status=ComponentStatus.HEALTHY)
        with pytest.raises(ValidationError):
            r.status = ComponentStatus.UNHEALTHY  # type: ignore[misc]


# ─── 4. HealthChecker ───────────────────────────────────────────


class TestHealthChecker:
    """HealthChecker testlari."""

    def test_register_and_list(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: ComponentHealth(name="db", status=ComponentStatus.HEALTHY))
        assert "db" in hc.registered_components

    def test_check_all_healthy(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: ComponentHealth(name="db", status=ComponentStatus.HEALTHY))
        hc.register("llm", lambda: ComponentHealth(name="llm", status=ComponentStatus.HEALTHY))
        report = hc.check_all()
        assert report.is_healthy
        assert report.status == ComponentStatus.HEALTHY
        assert len(report.components) == 2

    def test_check_all_one_unhealthy(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: ComponentHealth(name="db", status=ComponentStatus.HEALTHY))
        hc.register("llm", lambda: ComponentHealth(name="llm", status=ComponentStatus.UNHEALTHY))
        report = hc.check_all()
        assert not report.is_healthy
        assert report.status == ComponentStatus.UNHEALTHY

    def test_check_all_degraded(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: ComponentHealth(name="db", status=ComponentStatus.HEALTHY))
        hc.register("llm", lambda: ComponentHealth(name="llm", status=ComponentStatus.DEGRADED))
        report = hc.check_all()
        assert report.status == ComponentStatus.DEGRADED

    def test_check_all_unknown(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: ComponentHealth(name="db", status=ComponentStatus.HEALTHY))
        hc.register("llm", lambda: ComponentHealth(name="llm", status=ComponentStatus.UNKNOWN))
        report = hc.check_all()
        assert report.status == ComponentStatus.UNKNOWN

    def test_check_all_empty(self) -> None:
        hc = HealthChecker()
        report = hc.check_all()
        assert report.status == ComponentStatus.UNKNOWN

    def test_check_all_exception_in_check(self) -> None:
        """Tekshirish funksiyasi xatolik bersa — UNHEALTHY bo'ladi."""
        hc = HealthChecker()

        def bad_check() -> ComponentHealth:
            msg = "DB connection failed"
            raise ConnectionError(msg)

        hc.register("db", bad_check)
        report = hc.check_all()
        assert report.status == ComponentStatus.UNHEALTHY
        assert len(report.components) == 1
        assert "xatosi" in report.components[0].message

    def test_check_one_found(self) -> None:
        hc = HealthChecker()
        hc.register("db", lambda: ComponentHealth(name="db", status=ComponentStatus.HEALTHY))
        result = hc.check_one("db")
        assert result is not None
        assert result.status == ComponentStatus.HEALTHY

    def test_check_one_not_found(self) -> None:
        hc = HealthChecker()
        assert hc.check_one("missing") is None

    def test_check_one_exception(self) -> None:
        hc = HealthChecker()

        def bad() -> ComponentHealth:
            msg = "fail"
            raise RuntimeError(msg)

        hc.register("bad", bad)
        result = hc.check_one("bad")
        assert result is not None
        assert result.status == ComponentStatus.UNHEALTHY

    def test_worst_status_priority(self) -> None:
        """UNHEALTHY > DEGRADED > UNKNOWN > HEALTHY."""
        hc = HealthChecker()
        hc.register("a", lambda: ComponentHealth(name="a", status=ComponentStatus.DEGRADED))
        hc.register("b", lambda: ComponentHealth(name="b", status=ComponentStatus.UNHEALTHY))
        report = hc.check_all()
        # UNHEALTHY eng yomon
        assert report.status == ComponentStatus.UNHEALTHY


# ─── 5. MetricType ──────────────────────────────────────────────


class TestMetricType:
    """MetricType enum testlari."""

    def test_counter(self) -> None:
        assert MetricType.COUNTER == "counter"

    def test_gauge(self) -> None:
        assert MetricType.GAUGE == "gauge"

    def test_two_types(self) -> None:
        assert len(MetricType) == 2


# ─── 6. MetricSnapshot ──────────────────────────────────────────


class TestMetricSnapshot:
    """MetricSnapshot model testlari."""

    def test_create(self) -> None:
        s = MetricSnapshot(name="requests", metric_type=MetricType.COUNTER, value=42.0)
        assert s.name == "requests"
        assert s.metric_type == MetricType.COUNTER
        assert s.value == 42.0
        assert s.labels == {}

    def test_with_labels(self) -> None:
        s = MetricSnapshot(
            name="cost",
            metric_type=MetricType.GAUGE,
            value=1.5,
            labels={"tier": "t1", "agent": "research"},
        )
        assert s.labels["tier"] == "t1"
        assert s.labels["agent"] == "research"

    def test_updated_at_auto(self) -> None:
        s = MetricSnapshot(name="x", metric_type=MetricType.COUNTER, value=0)
        assert isinstance(s.updated_at, datetime)

    def test_frozen(self) -> None:
        s = MetricSnapshot(name="x", metric_type=MetricType.COUNTER, value=0)
        with pytest.raises(ValidationError):
            s.value = 10  # type: ignore[misc]


# ─── 7. MetricsCollector ────────────────────────────────────────


class TestMetricsCollector:
    """MetricsCollector testlari."""

    def test_increment_new(self) -> None:
        mc = MetricsCollector()
        result = mc.increment("requests")
        assert result == 1.0

    def test_increment_existing(self) -> None:
        mc = MetricsCollector()
        mc.increment("requests")
        result = mc.increment("requests")
        assert result == 2.0

    def test_increment_custom_value(self) -> None:
        mc = MetricsCollector()
        result = mc.increment("cost", 0.05)
        assert result == pytest.approx(0.05)
        result = mc.increment("cost", 0.10)
        assert result == pytest.approx(0.15)

    def test_get_counter_missing(self) -> None:
        mc = MetricsCollector()
        assert mc.get_counter("missing") == 0.0

    def test_get_counter_existing(self) -> None:
        mc = MetricsCollector()
        mc.increment("req", 5)
        assert mc.get_counter("req") == 5.0

    def test_set_gauge(self) -> None:
        mc = MetricsCollector()
        mc.set_gauge("cpu", 75.5)
        assert mc.get_gauge("cpu") == 75.5

    def test_set_gauge_overwrite(self) -> None:
        mc = MetricsCollector()
        mc.set_gauge("cpu", 75.0)
        mc.set_gauge("cpu", 90.0)
        assert mc.get_gauge("cpu") == 90.0

    def test_get_gauge_missing(self) -> None:
        mc = MetricsCollector()
        assert mc.get_gauge("missing") == 0.0

    def test_snapshot_counter(self) -> None:
        mc = MetricsCollector()
        mc.increment("req", 10)
        snap = mc.snapshot("req")
        assert snap is not None
        assert snap.metric_type == MetricType.COUNTER
        assert snap.value == 10.0

    def test_snapshot_gauge(self) -> None:
        mc = MetricsCollector()
        mc.set_gauge("mem", 4096)
        snap = mc.snapshot("mem")
        assert snap is not None
        assert snap.metric_type == MetricType.GAUGE
        assert snap.value == 4096

    def test_snapshot_missing(self) -> None:
        mc = MetricsCollector()
        assert mc.snapshot("nope") is None

    def test_all_snapshots(self) -> None:
        mc = MetricsCollector()
        mc.increment("a")
        mc.set_gauge("b", 2.0)
        snaps = mc.all_snapshots()
        assert len(snaps) == 2
        names = {s.name for s in snaps}
        assert names == {"a", "b"}

    def test_all_snapshots_empty(self) -> None:
        mc = MetricsCollector()
        assert mc.all_snapshots() == []

    def test_reset(self) -> None:
        mc = MetricsCollector()
        mc.increment("a")
        mc.set_gauge("b", 1)
        mc.reset()
        assert mc.get_counter("a") == 0.0
        assert mc.get_gauge("b") == 0.0
        assert mc.stats["total"] == 0

    def test_stats(self) -> None:
        mc = MetricsCollector()
        mc.increment("c1")
        mc.increment("c2")
        mc.set_gauge("g1", 1)
        s = mc.stats
        assert s["counters"] == 2
        assert s["gauges"] == 1
        assert s["total"] == 3


# ─── 8. AlertSeverity ───────────────────────────────────────────


class TestAlertSeverity:
    """AlertSeverity enum testlari."""

    def test_info(self) -> None:
        assert AlertSeverity.INFO == "info"

    def test_warning(self) -> None:
        assert AlertSeverity.WARNING == "warning"

    def test_critical(self) -> None:
        assert AlertSeverity.CRITICAL == "critical"

    def test_three_levels(self) -> None:
        assert len(AlertSeverity) == 3


# ─── 9. AlertRule ────────────────────────────────────────────────


class TestAlertRule:
    """AlertRule model testlari."""

    def test_create_default(self) -> None:
        r = AlertRule(name="test")
        assert r.name == "test"
        assert r.severity == AlertSeverity.WARNING
        assert r.operator == "gt"
        assert r.threshold == 0.0
        assert r.enabled is True
        assert r.cooldown_s == 300
        assert len(r.id) == 12

    def test_evaluate_gt_true(self) -> None:
        r = AlertRule(name="high_cost", metric_name="cost", threshold=5.0, operator="gt")
        assert r.evaluate(6.0) is True

    def test_evaluate_gt_false(self) -> None:
        r = AlertRule(name="high_cost", metric_name="cost", threshold=5.0, operator="gt")
        assert r.evaluate(3.0) is False

    def test_evaluate_gt_equal(self) -> None:
        r = AlertRule(name="high_cost", metric_name="cost", threshold=5.0, operator="gt")
        assert r.evaluate(5.0) is False  # > emas, = emas

    def test_evaluate_lt(self) -> None:
        r = AlertRule(name="low_mem", threshold=100, operator="lt")
        assert r.evaluate(50) is True
        assert r.evaluate(150) is False

    def test_evaluate_eq(self) -> None:
        r = AlertRule(name="exact", threshold=42, operator="eq")
        assert r.evaluate(42) is True
        assert r.evaluate(41) is False

    def test_evaluate_disabled(self) -> None:
        r = AlertRule(name="off", threshold=5, operator="gt", enabled=False)
        assert r.evaluate(100) is False

    def test_evaluate_unknown_operator(self) -> None:
        r = AlertRule(name="bad", operator="gte")
        assert r.evaluate(100) is False

    def test_frozen(self) -> None:
        r = AlertRule(name="test")
        with pytest.raises(ValidationError):
            r.name = "changed"  # type: ignore[misc]

    def test_name_validation(self) -> None:
        with pytest.raises(ValidationError, match="string_too_short"):
            AlertRule(name="")


# ─── 10. Alert ──────────────────────────────────────────────────


class TestAlert:
    """Alert model testlari."""

    def test_create_default(self) -> None:
        a = Alert()
        assert len(a.id) == 12
        assert a.rule_id == ""
        assert a.severity == AlertSeverity.WARNING
        assert a.acknowledged is False
        assert isinstance(a.fired_at, datetime)

    def test_create_with_values(self) -> None:
        a = Alert(
            rule_id="r1",
            rule_name="budget",
            severity=AlertSeverity.CRITICAL,
            message="Budjet oshdi!",
            metric_name="cost",
            metric_value=12.5,
        )
        assert a.rule_id == "r1"
        assert a.severity == AlertSeverity.CRITICAL
        assert a.metric_value == 12.5

    def test_frozen(self) -> None:
        a = Alert()
        with pytest.raises(ValidationError):
            a.acknowledged = True  # type: ignore[misc]


# ─── 11. AlertManager ───────────────────────────────────────────


class TestAlertManager:
    """AlertManager testlari."""

    def test_add_rule(self) -> None:
        am = AlertManager()
        rule = AlertRule(name="test", metric_name="cost", threshold=5)
        result = am.add_rule(rule)
        assert result.id == rule.id
        assert am.get_rule(rule.id) is not None

    def test_list_rules(self) -> None:
        am = AlertManager()
        am.add_rule(AlertRule(name="a"))
        am.add_rule(AlertRule(name="b"))
        assert len(am.list_rules()) == 2

    def test_remove_rule(self) -> None:
        am = AlertManager()
        rule = AlertRule(name="x")
        am.add_rule(rule)
        assert am.remove_rule(rule.id) is True
        assert am.get_rule(rule.id) is None

    def test_remove_rule_missing(self) -> None:
        am = AlertManager()
        assert am.remove_rule("nonexistent") is False

    def test_get_rule_missing(self) -> None:
        am = AlertManager()
        assert am.get_rule("nope") is None

    def test_check_metric_fires(self) -> None:
        am = AlertManager()
        rule = AlertRule(
            name="high_cost",
            metric_name="cost",
            threshold=5.0,
            operator="gt",
            cooldown_s=0,
        )
        am.add_rule(rule)
        alerts = am.check_metric("cost", 10.0)
        assert len(alerts) == 1
        assert alerts[0].rule_id == rule.id
        assert alerts[0].metric_value == 10.0
        assert "high_cost" in alerts[0].message

    def test_check_metric_no_fire(self) -> None:
        am = AlertManager()
        rule = AlertRule(
            name="high_cost",
            metric_name="cost",
            threshold=5.0,
            operator="gt",
        )
        am.add_rule(rule)
        alerts = am.check_metric("cost", 3.0)
        assert alerts == []

    def test_check_metric_wrong_name(self) -> None:
        am = AlertManager()
        rule = AlertRule(name="cost_rule", metric_name="cost", threshold=5, operator="gt")
        am.add_rule(rule)
        alerts = am.check_metric("memory", 100)
        assert alerts == []

    def test_check_metric_cooldown(self) -> None:
        """Cooldown ichida ikkinchi ogohlantirish bermaydi."""
        am = AlertManager()
        rule = AlertRule(
            name="x",
            metric_name="m",
            threshold=1,
            operator="gt",
            cooldown_s=3600,  # 1 soat
        )
        am.add_rule(rule)
        # Birinchi — o'tadi
        alerts1 = am.check_metric("m", 10)
        assert len(alerts1) == 1
        # Ikkinchi — cooldown ichida, o'tmaydi
        alerts2 = am.check_metric("m", 10)
        assert len(alerts2) == 0

    def test_check_metric_cooldown_expired(self) -> None:
        """Cooldown tugasa — yana ogohlantirish beradi."""
        am = AlertManager()
        rule = AlertRule(
            name="x",
            metric_name="m",
            threshold=1,
            operator="gt",
            cooldown_s=0,  # 0 sekundlik cooldown
        )
        am.add_rule(rule)
        alerts1 = am.check_metric("m", 10)
        assert len(alerts1) == 1
        # cooldown=0 bo'lgani uchun darhol o'tadi
        time.sleep(0.01)
        alerts2 = am.check_metric("m", 10)
        assert len(alerts2) == 1

    def test_check_metric_multiple_rules(self) -> None:
        am = AlertManager()
        am.add_rule(
            AlertRule(name="a", metric_name="cost", threshold=5, operator="gt", cooldown_s=0)
        )
        am.add_rule(
            AlertRule(name="b", metric_name="cost", threshold=8, operator="gt", cooldown_s=0)
        )
        # 10 ikkala qoidani ham trigger qiladi
        alerts = am.check_metric("cost", 10)
        assert len(alerts) == 2
        # 6 faqat birinchisini trigger qiladi
        alerts2 = am.check_metric("cost", 6)
        assert len(alerts2) == 1

    def test_fire_manual(self) -> None:
        am = AlertManager()
        alert = am.fire_manual(
            name="killswitch",
            message="Kill switch yoqildi!",
            severity=AlertSeverity.CRITICAL,
        )
        assert alert.rule_name == "killswitch"
        assert alert.severity == AlertSeverity.CRITICAL
        assert alert.message == "Kill switch yoqildi!"

    def test_acknowledge(self) -> None:
        am = AlertManager()
        alert = am.fire_manual(name="test", message="msg")
        assert am.acknowledge(alert.id) is True
        alerts = am.list_alerts()
        assert alerts[0].acknowledged is True

    def test_acknowledge_missing(self) -> None:
        am = AlertManager()
        assert am.acknowledge("nonexistent") is False

    def test_list_alerts_all(self) -> None:
        am = AlertManager()
        am.fire_manual(name="a", message="1")
        am.fire_manual(name="b", message="2")
        assert len(am.list_alerts()) == 2

    def test_list_alerts_unacknowledged(self) -> None:
        am = AlertManager()
        a1 = am.fire_manual(name="a", message="1")
        am.fire_manual(name="b", message="2")
        am.acknowledge(a1.id)
        unack = am.list_alerts(unacknowledged_only=True)
        assert len(unack) == 1
        assert unack[0].rule_name == "b"

    def test_clear_alerts(self) -> None:
        am = AlertManager()
        am.fire_manual(name="a", message="1")
        am.fire_manual(name="b", message="2")
        count = am.clear_alerts()
        assert count == 2
        assert am.list_alerts() == []

    def test_clear_alerts_empty(self) -> None:
        am = AlertManager()
        assert am.clear_alerts() == 0

    def test_stats(self) -> None:
        am = AlertManager()
        am.add_rule(AlertRule(name="r1"))
        am.add_rule(AlertRule(name="r2"))
        am.fire_manual(name="a", message="m", severity=AlertSeverity.WARNING)
        am.fire_manual(name="b", message="m", severity=AlertSeverity.CRITICAL)
        s = am.stats
        assert s["total_rules"] == 2
        assert s["total_alerts"] == 2
        assert s["unacknowledged"] == 2
        assert s["critical"] == 1
        assert s["warning"] == 1

    def test_stats_after_acknowledge(self) -> None:
        am = AlertManager()
        alert = am.fire_manual(name="x", message="m")
        am.acknowledge(alert.id)
        assert am.stats["unacknowledged"] == 0


# ─── 12. Monitoring __init__ exports ────────────────────────────


class TestMonitoringExports:
    """__init__.py dan export qilingan nomlar."""

    def test_all_exports(self) -> None:
        import zet.monitoring as mod

        expected = {
            "AlertManager",
            "AlertNotificationBridge",
            "AlertRule",
            "AlertSeverity",
            "ComponentStatus",
            "HealthChecker",
            "HealthReport",
            "MetricSnapshot",
            "MetricsCollector",
        }
        assert set(mod.__all__) == expected

    def test_import_health_checker(self) -> None:
        from zet.monitoring import HealthChecker

        hc = HealthChecker()
        assert hc.registered_components == []

    def test_import_metrics_collector(self) -> None:
        from zet.monitoring import MetricsCollector

        mc = MetricsCollector()
        assert mc.stats["total"] == 0

    def test_import_alert_manager(self) -> None:
        from zet.monitoring import AlertManager

        am = AlertManager()
        assert am.stats["total_alerts"] == 0


# ─── 13. Xavfsizlik invariantlari ───────────────────────────────


class TestMonitoringSecurityInvariants:
    """Xavfsizlik invariantlari testlari."""

    def test_frozen_component_health(self) -> None:
        """ComponentHealth o'zgartirib bo'lmaydi."""
        h = ComponentHealth(name="db", status=ComponentStatus.HEALTHY)
        with pytest.raises(ValidationError):
            h.status = ComponentStatus.UNHEALTHY  # type: ignore[misc]

    def test_frozen_health_report(self) -> None:
        """HealthReport o'zgartirib bo'lmaydi."""
        r = HealthReport(status=ComponentStatus.HEALTHY)
        with pytest.raises(ValidationError):
            r.status = ComponentStatus.UNHEALTHY  # type: ignore[misc]

    def test_frozen_metric_snapshot(self) -> None:
        """MetricSnapshot o'zgartirib bo'lmaydi."""
        s = MetricSnapshot(name="x", metric_type=MetricType.COUNTER, value=0)
        with pytest.raises(ValidationError):
            s.value = 99  # type: ignore[misc]

    def test_frozen_alert_rule(self) -> None:
        """AlertRule o'zgartirib bo'lmaydi."""
        r = AlertRule(name="test")
        with pytest.raises(ValidationError):
            r.threshold = 999  # type: ignore[misc]

    def test_frozen_alert(self) -> None:
        """Alert o'zgartirib bo'lmaydi."""
        a = Alert()
        with pytest.raises(ValidationError):
            a.acknowledged = True  # type: ignore[misc]

    def test_health_check_exception_safe(self) -> None:
        """Tekshirish xatosi tizimni to'xtatmaydi."""
        hc = HealthChecker()
        hc.register("good", lambda: ComponentHealth(name="good", status=ComponentStatus.HEALTHY))

        def explode() -> ComponentHealth:
            msg = "boom"
            raise RuntimeError(msg)

        hc.register("bad", explode)
        report = hc.check_all()
        # Tizim ishlamoqda, faqat bad komponent UNHEALTHY
        assert len(report.components) == 2
        names_ok = [c.name for c in report.components if c.status == ComponentStatus.HEALTHY]
        assert "good" in names_ok

    def test_alert_ids_unique(self) -> None:
        """Har bir alert unikal ID ga ega."""
        am = AlertManager()
        a1 = am.fire_manual(name="x", message="m")
        a2 = am.fire_manual(name="y", message="n")
        assert a1.id != a2.id

    def test_alert_rule_ids_unique(self) -> None:
        """Har bir rule unikal ID ga ega."""
        r1 = AlertRule(name="a")
        r2 = AlertRule(name="b")
        assert r1.id != r2.id

    def test_metrics_counter_monotonic(self) -> None:
        """Counter faqat o'sadi (increment bilan)."""
        mc = MetricsCollector()
        mc.increment("c", 5)
        mc.increment("c", 3)
        assert mc.get_counter("c") == 8.0

    def test_alert_cooldown_prevents_spam(self) -> None:
        """Cooldown ogohlantirish spamini oldini oladi."""
        am = AlertManager()
        rule = AlertRule(
            name="spam_test",
            metric_name="x",
            threshold=0,
            operator="gt",
            cooldown_s=9999,
        )
        am.add_rule(rule)
        am.check_metric("x", 100)
        am.check_metric("x", 100)
        am.check_metric("x", 100)
        assert am.stats["total_alerts"] == 1  # Faqat 1, 3 ta emas

    def test_disabled_rule_never_fires(self) -> None:
        """Disabled qoida hech qachon ogohlantirish bermaydi."""
        am = AlertManager()
        rule = AlertRule(
            name="off",
            metric_name="x",
            threshold=0,
            operator="gt",
            enabled=False,
            cooldown_s=0,
        )
        am.add_rule(rule)
        alerts = am.check_metric("x", 9999)
        assert alerts == []

    def test_check_metric_with_mock_time(self) -> None:
        """Cooldown vaqt bilan ishlashini tekshirish."""
        am = AlertManager()
        rule = AlertRule(
            name="timed",
            metric_name="t",
            threshold=0,
            operator="gt",
            cooldown_s=60,
        )
        am.add_rule(rule)

        # Birinchi — o'tadi
        alerts1 = am.check_metric("t", 10)
        assert len(alerts1) == 1

        # Cooldown ichida — o'tmaydi
        alerts2 = am.check_metric("t", 10)
        assert len(alerts2) == 0

        # Vaqtni 61 sekund oldinga surish
        past = datetime(2020, 1, 1, tzinfo=UTC)
        am._last_fired[rule.id] = past
        alerts3 = am.check_metric("t", 10)
        assert len(alerts3) == 1
