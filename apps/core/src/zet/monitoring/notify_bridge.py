"""AlertManager → Notifier ko'prigi (gap-analysis #14).

Ilgari `AlertManager` yangi alert yaratganda `Notifier.send()`ni HECH QACHON
chaqirmasdi — faqat in-memory ro'yxatga saqlardi (`monitoring/alerts.py`,
`self._alerts.append(alert)`), Telegram/boshqa kanalga hech narsa
yuborilmasdi.

`AlertManager` sync (I/O yo'q, 99 ta test unga tayangan), `Notifier` esa
async (tarmoq I/O). Ularni bevosita birlashtirish `AlertManager`ning
testlangan sync interfeysini buzar edi — shuning uchun bu alohida ko'prik
ikkalasini ham o'zgartirmasdan bog'laydi.

Bog'liq qarorlar:
    Bo'lim 10 — monitoring
    V-17 — Telegram chiqish kanali
"""

from __future__ import annotations

import structlog

from zet.monitoring.alerts import Alert, AlertManager, AlertSeverity
from zet.telegram.notifier import Notifier

log = structlog.get_logger(__name__)

_SEVERITY_ICON: dict[str, str] = {
    "info": "ℹ️",  # noqa: RUF001 — qasddan Unicode belgi (emoji)
    "warning": "⚠️",
    "critical": "🔴",
}


def format_alert(alert: Alert) -> str:
    """Alert'ni Notifier uchun matnga aylantiradi."""
    icon = _SEVERITY_ICON.get(alert.severity.value, "⚠️")
    return f"{icon} {alert.rule_name or 'Alert'}: {alert.message}"


class AlertNotificationBridge:
    """`AlertManager`da yangi alert paydo bo'lganda `Notifier` orqali yuboradi.

    `AlertManager`ning o'zini o'zgartirmaydi — uni o'rab, har bir yangi
    alert uchun yuborishni qo'shadi.
    """

    def __init__(self, *, alerts: AlertManager, notifier: Notifier) -> None:
        self._alerts = alerts
        self._notifier = notifier

    @property
    def alerts(self) -> AlertManager:
        """Ichki `AlertManager` (qoidalarni boshqarish uchun)."""
        return self._alerts

    async def check_metric(self, metric_name: str, value: float) -> list[Alert]:
        """Metrikani tekshiradi; yangi alert(lar) bo'lsa — yuboradi.

        Returns:
            Yaratilgan (va yuborilgan) alertlar.
        """
        new_alerts = self._alerts.check_metric(metric_name, value)
        for alert in new_alerts:
            await self._notify(alert)
        return new_alerts

    async def fire_manual(
        self,
        *,
        name: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.WARNING,
    ) -> Alert:
        """Qo'lda alert yaratadi va darhol yuboradi."""
        alert = self._alerts.fire_manual(name=name, message=message, severity=severity)
        await self._notify(alert)
        return alert

    async def _notify(self, alert: Alert) -> None:
        try:
            sent = await self._notifier.send_alert(format_alert(alert))
        except Exception:
            log.exception("alert.notify_failed", alert_id=alert.id)
            return
        log.info("alert.notified", alert_id=alert.id, severity=alert.severity.value, sent=sent)


__all__ = ["AlertNotificationBridge", "format_alert"]
