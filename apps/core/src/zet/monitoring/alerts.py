"""Alert Manager — ogohlantirishlar (Bo'lim 10).

Metrikalar va health check asosida ogohlantirishlar.
Produksiyada Telegram orqali egaga xabar yuboriladi.

Ogohlantirish turlari:
    - budget_warning — budjet chegarasiga yaqinlashmoqda
    - budget_exceeded — budjet oshib ketdi
    - health_degraded — komponent nosog'lom
    - error_rate_high — xatolar ko'paymoqda
    - killswitch_engaged — kill switch yoqildi

Bog'liq qarorlar:
    Bo'lim 10 — monitoring
    ADR-0006 — budjet chegaralari
    V-17 — Telegram = boshqaruv paneli
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class AlertSeverity(StrEnum):
    """Ogohlantirish darajasi."""

    INFO = "info"
    """Ma'lumot — hech narsa qilish shart emas."""

    WARNING = "warning"
    """Ogohlantirish — e'tibor kerak."""

    CRITICAL = "critical"
    """Muhim — darhol choralar kerak."""


class AlertRule(BaseModel, frozen=True):
    """Ogohlantirish qoidasi.

    Metrika yoki holat asosida ogohlantirish berish.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal qoida ID."""

    name: str = Field(min_length=1, max_length=100)
    """Qoida nomi."""

    description: str = ""
    """Tavsif."""

    severity: AlertSeverity = AlertSeverity.WARNING
    """Darajasi."""

    metric_name: str = ""
    """Kuzatiladigan metrika nomi (bo'sh = manual trigger)."""

    threshold: float = 0.0
    """Chegara qiymati (metrika bu qiymatdan oshsa — ogohlantirish)."""

    operator: str = "gt"
    """Taqqoslash: 'gt' (katta), 'lt' (kichik), 'eq' (teng)."""

    enabled: bool = True
    """Qoida yoqilganmi."""

    cooldown_s: int = 300
    """Ikki ogohlantirish orasidagi minimal vaqt (sekundda)."""

    def evaluate(self, value: float) -> bool:
        """Metrika qiymatini tekshirish.

        Args:
            value: Metrika qiymati

        Returns:
            True agar ogohlantirish kerak bo'lsa
        """
        if not self.enabled:
            return False
        if self.operator == "gt":
            return value > self.threshold
        if self.operator == "lt":
            return value < self.threshold
        if self.operator == "eq":
            return value == self.threshold
        return False


class Alert(BaseModel, frozen=True):
    """Ogohlantirish yozuvi."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal ID."""

    rule_id: str = ""
    """Ishga tushirgan qoida ID."""

    rule_name: str = ""
    """Qoida nomi."""

    severity: AlertSeverity = AlertSeverity.WARNING
    """Darajasi."""

    message: str = ""
    """Xabar matni."""

    metric_name: str = ""
    """Metrika nomi."""

    metric_value: float = 0.0
    """Metrika qiymati (ogohlantirish paytida)."""

    fired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Ogohlantirish vaqti."""

    acknowledged: bool = False
    """Ega ko'rdimi."""


class AlertManager:
    """Ogohlantirishlar boshqaruvchisi.

    Qoidalar asosida ogohlantirishlarni yaratadi va saqlaydi.
    """

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}
        self._alerts: list[Alert] = []
        self._last_fired: dict[str, datetime] = {}

    def add_rule(self, rule: AlertRule) -> AlertRule:
        """Qoida qo'shish."""
        self._rules[rule.id] = rule
        log.info("alert.rule_added", id=rule.id, name=rule.name)
        return rule

    def get_rule(self, rule_id: str) -> AlertRule | None:
        """Qoida olish."""
        return self._rules.get(rule_id)

    def list_rules(self) -> list[AlertRule]:
        """Barcha qoidalar."""
        return list(self._rules.values())

    def remove_rule(self, rule_id: str) -> bool:
        """Qoidani o'chirish."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def check_metric(self, metric_name: str, value: float) -> list[Alert]:
        """Metrikani barcha qoidalar bilan tekshirish.

        Args:
            metric_name: Metrika nomi
            value: Joriy qiymat

        Returns:
            Yaratilgan ogohlantirishlar
        """
        new_alerts: list[Alert] = []

        for rule in self._rules.values():
            if rule.metric_name != metric_name:
                continue
            if not rule.evaluate(value):
                continue

            # Cooldown tekshiruvi
            last = self._last_fired.get(rule.id)
            now = datetime.now(UTC)
            if last is not None:
                elapsed = (now - last).total_seconds()
                if elapsed < rule.cooldown_s:
                    continue

            alert = Alert(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity,
                message=f"{rule.name}: {metric_name} = {value} ({rule.operator} {rule.threshold})",
                metric_name=metric_name,
                metric_value=value,
            )
            self._alerts.append(alert)
            self._last_fired[rule.id] = now
            new_alerts.append(alert)

            log.warning(
                "alert.fired",
                rule=rule.name,
                severity=rule.severity.value,
                metric=metric_name,
                value=value,
            )

        return new_alerts

    def fire_manual(
        self,
        *,
        name: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
    ) -> Alert:
        """Qo'lda ogohlantirish yaratish.

        Args:
            name: Ogohlantirish nomi
            message: Xabar
            severity: Darajasi

        Returns:
            Yaratilgan alert
        """
        alert = Alert(
            rule_name=name,
            severity=severity,
            message=message,
        )
        self._alerts.append(alert)
        log.warning("alert.manual", name=name, severity=severity.value)
        return alert

    def acknowledge(self, alert_id: str) -> bool:
        """Ogohlantirishni ko'rilgan deb belgilash.

        Args:
            alert_id: Alert ID

        Returns:
            True agar topilsa va belgilansa
        """
        for i, alert in enumerate(self._alerts):
            if alert.id == alert_id:
                self._alerts[i] = Alert(
                    id=alert.id,
                    rule_id=alert.rule_id,
                    rule_name=alert.rule_name,
                    severity=alert.severity,
                    message=alert.message,
                    metric_name=alert.metric_name,
                    metric_value=alert.metric_value,
                    fired_at=alert.fired_at,
                    acknowledged=True,
                )
                return True
        return False

    def list_alerts(self, *, unacknowledged_only: bool = False) -> list[Alert]:
        """Ogohlantirishlar ro'yxati."""
        if unacknowledged_only:
            return [a for a in self._alerts if not a.acknowledged]
        return list(self._alerts)

    def clear_alerts(self) -> int:
        """Barcha ogohlantirishlarni tozalash.

        Returns:
            Tozalangan ogohlantirishlar soni
        """
        count = len(self._alerts)
        self._alerts.clear()
        return count

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        alerts = self._alerts
        return {
            "total_rules": len(self._rules),
            "total_alerts": len(alerts),
            "unacknowledged": sum(1 for a in alerts if not a.acknowledged),
            "critical": sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL),
            "warning": sum(1 for a in alerts if a.severity == AlertSeverity.WARNING),
        }
