"""Alert endpoint'lari (Bo'lim 10, gap-analysis #14).

POST /api/v1/alerts               — qo'lda alert yaratish va yuborish
GET  /api/v1/alerts                — alertlar ro'yxati
POST /api/v1/alerts/{id}/acknowledge — ko'rilgan deb belgilash

Ilgari `AlertManager` faqat in-memory saqlardi — hech qanday kanalga
(Telegram va h.k.) yuborilmasdi. Endi `AlertNotificationBridge` orqali
har bir yangi alert `Notifier.send_alert()`ga ham boradi.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_alert_bridge, get_alert_manager
from zet.monitoring.alerts import Alert, AlertManager, AlertSeverity
from zet.monitoring.notify_bridge import AlertNotificationBridge

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertFireRequest(BaseModel):
    """Qo'lda alert yaratish so'rovi."""

    name: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=2000)
    severity: AlertSeverity = AlertSeverity.WARNING


class AlertResponse(BaseModel):
    """Alert javobi."""

    id: str
    rule_name: str
    severity: str
    message: str
    metric_name: str
    metric_value: float
    fired_at: str
    acknowledged: bool


def _to_response(alert: Alert) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        rule_name=alert.rule_name,
        severity=alert.severity.value,
        message=alert.message,
        metric_name=alert.metric_name,
        metric_value=alert.metric_value,
        fired_at=alert.fired_at.isoformat(),
        acknowledged=alert.acknowledged,
    )


@router.post("", response_model=AlertResponse, status_code=201)
async def fire_alert(
    request: AlertFireRequest,
    bridge: AlertNotificationBridge = Depends(get_alert_bridge),
) -> AlertResponse:
    """Qo'lda alert yaratish — darhol yuboriladi."""
    alert = await bridge.fire_manual(
        name=request.name,
        message=request.message,
        severity=request.severity,
    )
    return _to_response(alert)


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    unacknowledged_only: bool = False,
    bridge: AlertNotificationBridge = Depends(get_alert_bridge),
) -> list[AlertResponse]:
    """Alertlar ro'yxati."""
    return [
        _to_response(a) for a in bridge.alerts.list_alerts(unacknowledged_only=unacknowledged_only)
    ]


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    alerts: AlertManager = Depends(get_alert_manager),
) -> dict[str, bool]:
    """Alertni ko'rilgan deb belgilash (yuborilmaydi — faqat holat)."""
    if not alerts.acknowledge(alert_id):
        raise HTTPException(status_code=404, detail="Alert topilmadi")
    return {"acknowledged": True}
