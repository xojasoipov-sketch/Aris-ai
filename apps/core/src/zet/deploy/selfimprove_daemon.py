"""Self-Improvement Daemon — `SelfImproveEngine`ni fon ishga ulaydi (GAP_ANALYSIS §12).

`SelfImproveEngine` (`deploy/selfimprove.py`) faqat tavsiya/tasdiq
CRUD'ini bilar edi — `.suggest()` hech qayerdan chaqirilmasdi. Bu
daemon oxirgi 7 kunlik ishlab chiqarish signallarini bazadan o'qib,
mos xulosalar bo'yicha `engine.suggest()` chaqiradi va yig'ilgan
kutilayotgan tavsiyalarni haftalik dushanba ertalab egaga notifier
orqali yuboradi.

TAHLIL MANBALARI (ikkalasi ham prod trafigida yoziladi):
    - `CostLedger` — LLM chaqiruvlari, tier, ok/verified_ok, USD
    - `ToolCall`  — har bir tool chaqiruvi, ok/xato, tool nomi

TAVSIYA QOIDALARI (hammasi konservativ — noise'ni bostirish uchun
kamida bir necha o'nlab yozuv talab qilinadi, minimal namuna yo'q
degan degradatsiya emas):

    1. LLM xato foizi > 20% (kamida 20 chaqiruv) → `BUG_FIX`
       — tez-tez timeout/rate-limit qaytaradigan provider bor.
    2. T3 (strong) xarajati haftalik > 50% jami USD (kamida $0.10)
       → `COST_OPTIMIZATION` — routing qoidalari ko'p T3'ga tushmoqda.
    3. `verified_ok=False` ulushi > 30% (kamida 20 verified) →
       `BETTER_PROCESS` — verifier'dan o'ta olmayotgan run'lar ko'p.
    4. Eng ko'p xato qaytaradigan tool (kamida 10 chaqiruv va
       xato foizi > 30%) → `BUG_FIX` — o'sha tool ishlamayapti.

YO'Q NARSALAR (dizayn qarorlari):
    - AVTOMATIK TA'MIR YO'Q — faqat tavsiya. Tasdiq ega qo'lida
      qoladi (`selfimprove.py` docstringi V-36).
    - LLM ISHLATILMAYDI — barcha xulosalar deterministik
      SQL agregatidan. LLM'siz ishlashi kerak (fail-open falsafasi:
      Ollama/API pastda bo'lsa ham engine ishlab turishi kerak).
    - Bir kunda IKKI marta yubormaslik (`_last_sent` — `ReportsDaemon`
      bilan bir xil naqsh, restart'dan keyin takror ehtimoli qabul).

Bog'liq qarorlar:
    V-36 — self-improvement loop
    GAP_ANALYSIS §12 — "qurilgan-u ulanmagan" ro'yxati
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.config import Settings
from zet.db.models import CostLedger, ToolCall
from zet.db.session import session_scope
from zet.deploy.selfimprove import (
    ImprovementPriority,
    ImprovementSuggestion,
    ImprovementType,
    SelfImproveEngine,
)
from zet.domain.enums import ModelTier
from zet.telegram.notifier import Notifier

log = structlog.get_logger(__name__)

DEFAULT_TICK_SECONDS = 3600
"""Bir soatda bir marta tekshirish yetarli — jadval haftalik."""

DEFAULT_SEND_HOUR = 9
"""Toshkent bo'yicha (09:00) — ega ishga o'tirishdan oldin."""

ANALYSIS_WINDOW_DAYS = 7
"""Tahlil oynasi — o'tgan hafta signallari haftalik takrorda barqaror."""

# ── Chegaralar ────────────────────────────────────────────────────
# Bu sonlar false-positive'ni bostirish uchun ataylab konservativ.
# Kichkina namuna ustidan qat'iy xulosa chiqarish daemon'ning
# birinchi haftada tavsiyalar to'lqinini yaratishga olib keladi,
# ega ularni bir marta ko'radi va uni o'chirib qo'yadi. Yaxshiroq —
# har hafta 0-2 ta arzon signaldan iborat sokin ovoz.

MIN_LLM_CALLS = 20
"""Xato foizi bo'yicha xulosa chiqarish uchun minimal LLM chaqiruvi."""

MIN_VERIFIED_CALLS = 20
"""Verified_ok tahlili uchun minimal chaqiruvlar soni."""

MIN_TOOL_CALLS = 10
"""Bitta tool bo'yicha xato tahlili uchun minimal chaqiruvlar."""

LLM_ERROR_THRESHOLD = 0.20
"""20% dan ortiq LLM chaqiruvi xato qaytarsa — BUG_FIX signali."""

VERIFIER_FAIL_THRESHOLD = 0.30
"""30% dan ortiq run verifier'dan o'tolmasa — BETTER_PROCESS signali."""

TOOL_ERROR_THRESHOLD = 0.30
"""Tool 30%+ vaqt xato qaytarsa — BUG_FIX signali."""

T3_SHARE_THRESHOLD = 0.50
"""T3 (strong) xarajati jami xarajatning 50% dan oshsa —
COST_OPTIMIZATION signali (ADR-0006 nazarda tutgan naqshdan chetlanish)."""

T3_SHARE_MIN_TOTAL_USD = 0.10
"""Jami xarajat shundan pastda bo'lsa foiz shovqinli — signal
berilmaydi (masalan bir hafta hech kim ishlatmagan)."""


class SelfImproveDaemon:
    """`SelfImproveEngine`ni haftalik tahlil orqali oziqlantiruvchi tsikl.

    `run_forever()` — asyncio task sifatida (FastAPI lifespan orqali).
    `tick()` — bitta tekshiruv, test/manual chaqiruv uchun to'g'ridan-
    to'g'ri.
    """

    def __init__(
        self,
        *,
        engine: SelfImproveEngine,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        notifier: Notifier,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        send_hour: int = DEFAULT_SEND_HOUR,
        window_days: int = ANALYSIS_WINDOW_DAYS,
    ) -> None:
        self._engine = engine
        self._session_factory = session_factory
        self._settings = settings
        self._notifier = notifier
        self._tick_seconds = tick_seconds
        self._send_hour = send_hour
        self._window_days = window_days
        self._tz = ZoneInfo(settings.timezone)
        self._last_sent: dict[str, date] = {}
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Tsiklni keyingi tick oralig'ida to'xtatish."""
        self._stop_event.set()

    async def run_forever(self) -> None:
        log.info("selfimprove_daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                # Fail-open: daemon halok bo'lmasin — signalsiz hafta
                # tavsiyalarsiz haftadir, lekin production oqimi
                # buzilmaydi.
                log.exception("selfimprove_daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("selfimprove_daemon.stopped")

    async def tick(self, *, now: datetime | None = None) -> list[ImprovementSuggestion]:
        """Bitta tekshiruv — dushanba 09:00'da tahlil qiladi va yuboradi.

        Boshqa kunlarda BO'SH ro'yxat qaytaradi (daemon jim). Bir kunda
        ikki marta chaqirilsa faqat BIR marta yuboriladi.

        Returns:
            Shu tick'da qo'shilgan tavsiyalar (test va diagnostikaga).
        """
        current = now or datetime.now(tz=self._tz)
        # Dushanba (0=Monday, Python konventsiyasi)
        if current.weekday() != 0:
            return []
        if current.hour < self._send_hour:
            return []
        today = current.date()
        if self._last_sent.get("weekly") == today:
            return []
        self._last_sent["weekly"] = today

        try:
            new_suggestions = await self.analyze_once()
        except Exception:
            log.exception("selfimprove_daemon.analyze_failed")
            return []

        # Notifier'ga xulosa (yuqoridagi analiz yozib qoldirgan barcha
        # kutilayotgan tavsiyalar — birinchi haftada bittaga qo'shimcha
        # bir necha bo'lishi mumkin, keyingi haftalarda esa faqat
        # yangilari, chunki tasdiqlangan/amalga oshirilganlar `pending`ga
        # kirmaydi).
        try:
            text = self._format_summary(new_suggestions)
            if text:
                await self._notifier.send_text(text)
                log.info(
                    "selfimprove_daemon.sent",
                    new_count=len(new_suggestions),
                    pending_count=len(self._engine.pending()),
                )
        except Exception:
            # Notifier yiqilsa — tavsiyalar engine'da qoladi, egaga
            # boshqa kanal orqali yetadi.
            log.warning("selfimprove_daemon.notify_failed")

        return new_suggestions

    async def analyze_once(self) -> list[ImprovementSuggestion]:
        """Bitta tahlil sikli — bazani o'qiydi va `engine.suggest()` chaqiradi.

        Aynan shu metod `_dispatch_llm_error`/`_dispatch_verifier`/
        `_dispatch_cost`/`_dispatch_tool_error` ni ketma-ket ishlatadi.
        Har biri o'z chegarasidan o'tmasa `None` qaytadi va tavsiya
        qo'shilmaydi.

        Testlar shu metodni to'g'ridan-to'g'ri chaqirishi mumkin
        (jadval logikasi `tick()`da alohida).

        Returns:
            Shu tahlilda qo'shilgan tavsiyalar (bo'sh — hech nima
            g'oyalik chegarasidan o'tmagani).
        """
        since = datetime.now(tz=UTC) - timedelta(days=self._window_days)

        async with session_scope(self._session_factory) as session:
            llm_stats = await _load_llm_stats(session, since=since)
            tool_stats = await _load_tool_stats(session, since=since)

        added: list[ImprovementSuggestion] = []
        for suggestion in (
            self._dispatch_llm_error(llm_stats),
            self._dispatch_verifier(llm_stats),
            self._dispatch_cost(llm_stats),
            self._dispatch_tool_error(tool_stats),
        ):
            if suggestion is not None:
                added.append(suggestion)
        return added

    # ── Signal → tavsiya konvertorlari ────────────────────────────

    def _dispatch_llm_error(self, s: _LlmStats) -> ImprovementSuggestion | None:
        if s.total_calls < MIN_LLM_CALLS:
            return None
        rate = s.error_calls / s.total_calls
        if rate <= LLM_ERROR_THRESHOLD:
            return None
        return self._engine.suggest(
            improvement_type=ImprovementType.BUG_FIX,
            title="LLM chaqiruv xato foizi yuqori",
            description=(
                f"Oxirgi {self._window_days} kunda {s.total_calls} LLM chaqiruvining "
                f"{s.error_calls} tasi xato qaytardi ({rate:.0%}). Provider timeout/rate-"
                "limit/format xatolarini tekshiring; retry siyosati yoki fallback tier "
                "kerak bo'lishi mumkin."
            ),
            priority=ImprovementPriority.HIGH,
            estimated_impact=f"{rate:.0%} → 5% dan past xato foizi",
            source="cost_ledger.llm_errors",
        )

    def _dispatch_verifier(self, s: _LlmStats) -> ImprovementSuggestion | None:
        if s.verified_total < MIN_VERIFIED_CALLS:
            return None
        rate = s.verified_failed / s.verified_total
        if rate <= VERIFIER_FAIL_THRESHOLD:
            return None
        return self._engine.suggest(
            improvement_type=ImprovementType.BETTER_PROCESS,
            title="Verifier'dan o'tolmayotgan run'lar ko'p",
            description=(
                f"Oxirgi {self._window_days} kunda {s.verified_total} verified run'ning "
                f"{s.verified_failed} tasi `verified_ok=False` bilan yakunlangan "
                f"({rate:.0%}). Planner promptini yaxshilash yoki verifier'ga "
                "aniqroq expected_outcome berish kerak."
            ),
            priority=ImprovementPriority.HIGH,
            estimated_impact=f"{rate:.0%} → 15% dan past FAIL ulushi",
            source="cost_ledger.verified_ok",
        )

    def _dispatch_cost(self, s: _LlmStats) -> ImprovementSuggestion | None:
        if s.total_usd < T3_SHARE_MIN_TOTAL_USD:
            return None
        share = s.tier_usd.get(ModelTier.T3_STRONG, 0.0) / s.total_usd
        if share <= T3_SHARE_THRESHOLD:
            return None
        return self._engine.suggest(
            improvement_type=ImprovementType.COST_OPTIMIZATION,
            title="T3 (strong) xarajati ulushi katta",
            description=(
                f"Oxirgi {self._window_days} kunda umumiy ${s.total_usd:.2f} xarajatning "
                f"{share:.0%} T3 (strong) tier'da sarflandi. ADR-0006 T3'ni faqat COMPLEX/"
                "CODING vazifalarga cheklashni tavsiya qiladi — routing qoidalari yoki "
                "TaskClass tasnifi noto'g'ri bo'lishi mumkin."
            ),
            priority=ImprovementPriority.MEDIUM,
            estimated_impact=f"T3 ulushini {share:.0%} → 30% dan past",
            source="cost_ledger.tier_share",
        )

    def _dispatch_tool_error(self, stats: list[_ToolStat]) -> ImprovementSuggestion | None:
        worst: _ToolStat | None = None
        for stat in stats:
            if stat.total < MIN_TOOL_CALLS:
                continue
            rate = stat.errors / stat.total
            if rate <= TOOL_ERROR_THRESHOLD:
                continue
            if worst is None or (stat.errors / stat.total) > (worst.errors / worst.total):
                worst = stat
        if worst is None:
            return None
        rate = worst.errors / worst.total
        return self._engine.suggest(
            improvement_type=ImprovementType.BUG_FIX,
            title=f"`{worst.tool_name}` toolining xato foizi yuqori",
            description=(
                f"Oxirgi {self._window_days} kunda `{worst.tool_name}` toolining "
                f"{worst.total} chaqiruvidan {worst.errors} tasi xato qaytardi "
                f"({rate:.0%}). Tool implementatsiyasi, tashqi bog'liqlik yoki "
                "input validatsiyasini tekshiring."
            ),
            priority=ImprovementPriority.HIGH,
            estimated_impact=f"`{worst.tool_name}` xato foizi {rate:.0%} → 10% dan past",
            source="tool_call.error_rate",
        )

    # ── Yuborish formati ──────────────────────────────────────────

    def _format_summary(self, added: Iterable[ImprovementSuggestion]) -> str:
        pending = self._engine.pending()
        if not pending:
            # Yangi tavsiya yo'q va kutilayotgan ham yo'q — jim
            # bo'lish yaxshi, shovqin yaratmaslik uchun (spam
            # bo'lgan haftalik "Hech nima yo'q" xabari o'zi shovqin).
            return ""
        _ = list(added)  # signature'da mavjud, lekin format pending'ga tayanadi
        lines = [
            "🔧 <b>Haftalik takomillashtirish tavsiyalari</b>",
            f"Kutilayotgan: {len(pending)} ta",
            "",
        ]
        for s in pending:
            lines.append(f"• <b>[{s.priority.value.upper()}]</b> {s.title}")
            if s.estimated_impact:
                lines.append(f"    ↳ Kutilgan ta'sir: {s.estimated_impact}")
            if s.description:
                lines.append(f"    {s.description}")
        return "\n".join(lines)


# ── DB tahlili — pastki funksiyalar (session-scoped) ─────────────


class _LlmStats:
    """`CostLedger` bo'yicha oxirgi oynadagi agregatlar."""

    __slots__ = (
        "error_calls",
        "tier_usd",
        "total_calls",
        "total_usd",
        "verified_failed",
        "verified_total",
    )

    def __init__(
        self,
        *,
        total_calls: int,
        error_calls: int,
        verified_total: int,
        verified_failed: int,
        total_usd: float,
        tier_usd: dict[ModelTier, float],
    ) -> None:
        self.total_calls = total_calls
        self.error_calls = error_calls
        self.verified_total = verified_total
        self.verified_failed = verified_failed
        self.total_usd = total_usd
        self.tier_usd = tier_usd


class _ToolStat:
    __slots__ = ("errors", "tool_name", "total")

    def __init__(self, *, tool_name: str, total: int, errors: int) -> None:
        self.tool_name = tool_name
        self.total = total
        self.errors = errors


async def _load_llm_stats(session: AsyncSession, *, since: datetime) -> _LlmStats:
    """CostLedger'dan LLM tahlili uchun agregatlar."""
    total_calls_stmt = select(func.count()).where(CostLedger.created_at >= since)
    total_calls = int((await session.execute(total_calls_stmt)).scalar_one())

    error_stmt = select(func.count()).where(
        CostLedger.created_at >= since,
        CostLedger.ok.is_(False),
    )
    error_calls = int((await session.execute(error_stmt)).scalar_one())

    verified_total_stmt = select(func.count()).where(
        CostLedger.created_at >= since,
        CostLedger.verified_ok.is_not(None),
    )
    verified_total = int((await session.execute(verified_total_stmt)).scalar_one())

    verified_failed_stmt = select(func.count()).where(
        CostLedger.created_at >= since,
        CostLedger.verified_ok.is_(False),
    )
    verified_failed = int((await session.execute(verified_failed_stmt)).scalar_one())

    total_usd_stmt = select(func.coalesce(func.sum(CostLedger.usd), 0.0)).where(
        CostLedger.created_at >= since
    )
    total_usd = float((await session.execute(total_usd_stmt)).scalar_one())

    tier_stmt = (
        select(CostLedger.tier, func.coalesce(func.sum(CostLedger.usd), 0.0))
        .where(CostLedger.created_at >= since)
        .group_by(CostLedger.tier)
    )
    tier_usd: dict[ModelTier, float] = {
        row[0]: float(row[1]) for row in (await session.execute(tier_stmt)).all()
    }

    return _LlmStats(
        total_calls=total_calls,
        error_calls=error_calls,
        verified_total=verified_total,
        verified_failed=verified_failed,
        total_usd=total_usd,
        tier_usd=tier_usd,
    )


async def _load_tool_stats(session: AsyncSession, *, since: datetime) -> list[_ToolStat]:
    """ToolCall'dan tool nomi bo'yicha xato agregatlari."""
    total_stmt = (
        select(ToolCall.tool_name, func.count())
        .where(ToolCall.created_at >= since)
        .group_by(ToolCall.tool_name)
    )
    totals: dict[str, int] = {
        row[0]: int(row[1]) for row in (await session.execute(total_stmt)).all()
    }

    err_stmt = (
        select(ToolCall.tool_name, func.count())
        .where(
            ToolCall.created_at >= since,
            ToolCall.ok.is_(False),
        )
        .group_by(ToolCall.tool_name)
    )
    errors: dict[str, int] = {
        row[0]: int(row[1]) for row in (await session.execute(err_stmt)).all()
    }

    return [
        _ToolStat(tool_name=name, total=total, errors=errors.get(name, 0))
        for name, total in totals.items()
    ]


__all__ = [
    "ANALYSIS_WINDOW_DAYS",
    "DEFAULT_SEND_HOUR",
    "DEFAULT_TICK_SECONDS",
    "SelfImproveDaemon",
]
