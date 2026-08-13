"""Alert avtomatik ishga tushiruvchi daemon — AlertManager wiring (GAP #14 davomi).

`AlertManager.check_metric()` va `AlertNotificationBridge.check_metric()` allaqachon
mavjud (`monitoring/alerts.py`, `monitoring/notify_bridge.py`), lekin ularni
davriy ravishda haqiqiy metrika qiymatlari bilan chaqiradigan hech qanday joy
yo'q edi: qoidalarni HTTP orqali yaratish mumkin, biroq ular hech qachon
faollashmasdi (audit "dead wiring" #14).

Bu daemon uchta signalni har 60 sekundda o'lchaydi va bridge orqali o'tkazadi:

    - `cost_daily_pct` — bugungi USD sarfi / kunlik budjet * 100
    - `tool_error_rate` — oxirgi 1 soatda ToolCall xato foizi (%)
    - `verified_ok_rate` — oxirgi 1 soatda `verified_ok=True` ulushi (%)

Standart qoidalar (bootstrap paytida qo'shiladi, egaga darhol trafik keladi):
    - cost_daily_pct >= 80 → WARNING
    - tool_error_rate  >= 30 → WARNING
    - verified_ok_rate <  70 → WARNING (operator: `lt`)

FAIL-OPEN: har bir bosqich alohida try/except ichida — DB xatosi, notifier
xatosi yoki bo'sh baza daemon'ni yiqitmaydi. Signalsiz kun signalsiz kundir;
tsikl davom etadi, keyingi tick'da yana urinamiz.

Cooldown allaqachon `AlertRule.cooldown_s` (default 300s) orqali qoidada
saqlanadi — `AlertManager.check_metric()` ikki marta bir xil alert
yubormaydi. Bu daemon o'zining dedup jadvalini saqlamaydi.

Bog'liq qarorlar:
    Bo'lim 10 — monitoring
    V-17 — Telegram = chiqish kanali
    AUDIT #14 — dead wiring (bridge mavjud, chaqiruvchi yo'q)
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.config import Settings
from zet.db.models import CostLedger, ToolCall
from zet.db.session import session_scope
from zet.monitoring.alerts import AlertRule, AlertSeverity
from zet.monitoring.notify_bridge import AlertNotificationBridge

log = structlog.get_logger(__name__)

DEFAULT_TICK_SECONDS = 60
"""Bir daqiqada bir marta — signal yetib borgunga qadar kutish uchun qulay."""

ERROR_WINDOW_MINUTES = 60
"""Tool va verifier tahlili uchun oyna — 1 soatlik silliqlash."""

MIN_TOOL_SAMPLE = 5
"""Bu miqdordan kam chaqiruv bo'lsa xato foizi ishonchsiz — signal berilmaydi."""

MIN_VERIFIED_SAMPLE = 5
"""Verified qiymati bo'yicha shundan kam yozuv bo'lsa signal berilmaydi."""

# ── Metrika nomlari (qoida `metric_name`i bilan mos tushishi shart) ─
METRIC_COST_DAILY_PCT = "cost_daily_pct"
METRIC_TOOL_ERROR_RATE = "tool_error_rate"
METRIC_VERIFIED_OK_RATE = "verified_ok_rate"

# ── Standart chegaralar ────────────────────────────────────────────
DEFAULT_COST_PCT_THRESHOLD = 80.0
DEFAULT_TOOL_ERROR_PCT_THRESHOLD = 30.0
DEFAULT_VERIFIED_OK_PCT_THRESHOLD = 70.0


def default_rules() -> list[AlertRule]:
    """Bootstrap paytida `AlertManager`ga qo'shiladigan standart qoidalar.

    Ega HTTP orqali qo'shimcha qoidalar yaratishi yoki bularni o'chirishi
    mumkin — bu funksiya faqat "qutidan chiqib ishlaydi" darajasini ta'-
    minlaydi (dead wiring #14 tabiiy ta'siri: qoida yo'q → hech qachon
    trafik yo'q).
    """
    return [
        AlertRule(
            name="Kunlik budjet chegarasi (80%)",
            description="Bugungi USD sarfi kunlik budjetning 80% dan oshdi.",
            severity=AlertSeverity.WARNING,
            metric_name=METRIC_COST_DAILY_PCT,
            threshold=DEFAULT_COST_PCT_THRESHOLD,
            operator="gt",
        ),
        AlertRule(
            name="Tool xato foizi yuqori (>30%)",
            description="Oxirgi 1 soatda tool chaqiruvlarining 30% dan ortig'i xato.",
            severity=AlertSeverity.WARNING,
            metric_name=METRIC_TOOL_ERROR_RATE,
            threshold=DEFAULT_TOOL_ERROR_PCT_THRESHOLD,
            operator="gt",
        ),
        AlertRule(
            name="Verifier o'tish foizi past (<70%)",
            description="Oxirgi 1 soatda verified_ok ulushi 70% dan past.",
            severity=AlertSeverity.WARNING,
            metric_name=METRIC_VERIFIED_OK_RATE,
            threshold=DEFAULT_VERIFIED_OK_PCT_THRESHOLD,
            operator="lt",
        ),
    ]


class AlertsDaemon:
    """`AlertNotificationBridge`ni davriy metrika qiymatlari bilan oziqla-
    ntiruvchi fon tsikli.

    `run_forever()` — asyncio task (FastAPI lifespan orqali).
    `tick()` — bitta o'lchov + tekshiruv; test/manual chaqiruv uchun.
    """

    def __init__(
        self,
        *,
        bridge: AlertNotificationBridge,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        window_minutes: int = ERROR_WINDOW_MINUTES,
    ) -> None:
        self._bridge = bridge
        self._session_factory = session_factory
        self._settings = settings
        self._tick_seconds = tick_seconds
        self._window_minutes = window_minutes
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Tsiklni keyingi tick oralig'ida to'xtatish."""
        self._stop_event.set()

    async def run_forever(self) -> None:
        log.info("alerts_daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                # Fail-open: tsikl davom etsin — signalsiz daqiqa
                # signalsiz daqiqadir, ammo daemon halok bo'lmaydi.
                log.exception("alerts_daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("alerts_daemon.stopped")

    async def tick(self, *, now: datetime | None = None) -> dict[str, float | None]:
        """Bitta o'lchov — barcha uchta signalni hisoblab bridge'ga uzatadi.

        Har bir metrika alohida try/except ichida — biri yiqilsa
        boshqalari baribir ketadi.

        Returns:
            {metrika_nomi: qiymat|None} — testlar/diagnostika uchun.
            `None` — o'sha metrikani hisoblab bo'lmadi (bo'sh namuna
            yoki DB xatosi).
        """
        current = now or datetime.now(tz=UTC)
        measured: dict[str, float | None] = {}

        # 1) Kunlik budjet foizi
        try:
            measured[METRIC_COST_DAILY_PCT] = await self._cost_daily_pct(current)
        except Exception:
            log.exception("alerts_daemon.cost_metric_failed")
            measured[METRIC_COST_DAILY_PCT] = None

        # 2) Tool xato foizi (oxirgi 1 soat)
        try:
            measured[METRIC_TOOL_ERROR_RATE] = await self._tool_error_rate(current)
        except Exception:
            log.exception("alerts_daemon.tool_metric_failed")
            measured[METRIC_TOOL_ERROR_RATE] = None

        # 3) Verified ok foizi (oxirgi 1 soat)
        try:
            measured[METRIC_VERIFIED_OK_RATE] = await self._verified_ok_rate(current)
        except Exception:
            log.exception("alerts_daemon.verified_metric_failed")
            measured[METRIC_VERIFIED_OK_RATE] = None

        # Har bir mavjud qiymatni bridge orqali o'tkazamiz. `None`
        # (sample kam / DB xatosi) — signal bermaymiz (aks holda
        # "verified_ok_rate=0" false alert bo'lardi).
        for metric_name, value in measured.items():
            if value is None:
                continue
            try:
                await self._bridge.check_metric(metric_name, value)
            except Exception:
                log.exception("alerts_daemon.check_metric_failed", metric=metric_name)

        return measured

    # ── Metrika hisoblovchilari ───────────────────────────────────

    async def _cost_daily_pct(self, now: datetime) -> float | None:
        """Bugungi USD sarfi / kunlik budjet * 100. Budjet 0 bo'lsa `None`."""
        budget = float(self._settings.budget_daily_usd)
        if budget <= 0:
            return None
        day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with session_scope(self._session_factory) as session:
            total = await _sum_cost_usd(session, since=day_start)
        return (total / budget) * 100.0

    async def _tool_error_rate(self, now: datetime) -> float | None:
        """Oxirgi 1 soatda ToolCall xato foizi. Sample kichik bo'lsa `None`."""
        since = now.astimezone(UTC) - timedelta(minutes=self._window_minutes)
        async with session_scope(self._session_factory) as session:
            total, errors = await _count_tool_calls(session, since=since)
        if total < MIN_TOOL_SAMPLE:
            return None
        return (errors / total) * 100.0

    async def _verified_ok_rate(self, now: datetime) -> float | None:
        """Oxirgi 1 soatda `verified_ok=True` ulushi. Sample kichik bo'lsa `None`."""
        since = now.astimezone(UTC) - timedelta(minutes=self._window_minutes)
        async with session_scope(self._session_factory) as session:
            total, ok = await _count_verified(session, since=since)
        if total < MIN_VERIFIED_SAMPLE:
            return None
        return (ok / total) * 100.0


# ── DB agregatlari ─────────────────────────────────────────────────


async def _sum_cost_usd(session: AsyncSession, *, since: datetime) -> float:
    stmt = select(func.coalesce(func.sum(CostLedger.usd), 0.0)).where(
        CostLedger.created_at >= since
    )
    return float((await session.execute(stmt)).scalar_one())


async def _count_tool_calls(session: AsyncSession, *, since: datetime) -> tuple[int, int]:
    total_stmt = select(func.count()).where(ToolCall.created_at >= since)
    total = int((await session.execute(total_stmt)).scalar_one())
    err_stmt = select(func.count()).where(
        ToolCall.created_at >= since,
        ToolCall.ok.is_(False),
    )
    errors = int((await session.execute(err_stmt)).scalar_one())
    return total, errors


async def _count_verified(session: AsyncSession, *, since: datetime) -> tuple[int, int]:
    total_stmt = select(func.count()).where(
        CostLedger.created_at >= since,
        CostLedger.verified_ok.is_not(None),
    )
    total = int((await session.execute(total_stmt)).scalar_one())
    ok_stmt = select(func.count()).where(
        CostLedger.created_at >= since,
        CostLedger.verified_ok.is_(True),
    )
    ok = int((await session.execute(ok_stmt)).scalar_one())
    return total, ok


__all__ = [
    "DEFAULT_COST_PCT_THRESHOLD",
    "DEFAULT_TICK_SECONDS",
    "DEFAULT_TOOL_ERROR_PCT_THRESHOLD",
    "DEFAULT_VERIFIED_OK_PCT_THRESHOLD",
    "ERROR_WINDOW_MINUTES",
    "METRIC_COST_DAILY_PCT",
    "METRIC_TOOL_ERROR_RATE",
    "METRIC_VERIFIED_OK_RATE",
    "AlertsDaemon",
    "default_rules",
]
