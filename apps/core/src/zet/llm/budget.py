"""USD budjet qo'riqchisi (ADR-0006 §4).

Fail-closed: chegara oshsa chaqiruv **rad etiladi**, "ozgina oshib ketsin" degan
yumshoq rejim yo'q. Avtonom run'lar avval to'xtaydi — qo'lda yozilgan buyruq
oxirgi bo'lib to'xtaydi (egasi hech bo'lmaganda gaplasha olishi kerak).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.db.models import CostLedger
from zet.domain.enums import ModelTier
from zet.llm.base import BudgetExceededError


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Hozirgi sarf holati — hisobot va alert uchun."""

    spent_today_usd: float
    spent_month_usd: float
    daily_limit_usd: float
    monthly_limit_usd: float
    tier3_calls_today: int
    tier3_daily_limit: int

    @property
    def remaining_today_usd(self) -> float:
        return max(0.0, self.daily_limit_usd - self.spent_today_usd)

    @property
    def remaining_month_usd(self) -> float:
        return max(0.0, self.monthly_limit_usd - self.spent_month_usd)

    @property
    def daily_usage_ratio(self) -> float:
        if self.daily_limit_usd <= 0:
            return 1.0
        return self.spent_today_usd / self.daily_limit_usd

    @property
    def should_alert(self) -> bool:
        """Kunlik budjetning 80% i sarflanganda egaga xabar beriladi."""
        return self.daily_usage_ratio >= 0.8


def _day_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


class BudgetGuard:
    """Sarfni o'lchaydi va chegaradan oshishiga yo'l qo'ymaydi."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def _sum_usd(self, since: datetime) -> float:
        stmt = select(func.coalesce(func.sum(CostLedger.usd), 0.0)).where(
            CostLedger.created_at >= since
        )
        return float((await self._session.execute(stmt)).scalar_one())

    async def _sum_usd_autonomous(self, since: datetime) -> float:
        stmt = select(func.coalesce(func.sum(CostLedger.usd), 0.0)).where(
            CostLedger.created_at >= since,
            CostLedger.is_autonomous.is_(True),
        )
        return float((await self._session.execute(stmt)).scalar_one())

    async def _count_tier3_today(self, now: datetime) -> int:
        stmt = select(func.count()).where(
            CostLedger.created_at >= _day_start(now),
            CostLedger.tier == ModelTier.T3_STRONG,
            CostLedger.ok.is_(True),
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def snapshot(self, *, now: datetime | None = None) -> BudgetSnapshot:
        now = now or datetime.now(UTC)
        return BudgetSnapshot(
            spent_today_usd=await self._sum_usd(_day_start(now)),
            spent_month_usd=await self._sum_usd(_month_start(now)),
            daily_limit_usd=self._settings.budget_daily_usd,
            monthly_limit_usd=self._settings.budget_monthly_usd,
            tier3_calls_today=await self._count_tier3_today(now),
            tier3_daily_limit=self._settings.tier3_daily_calls,
        )

    async def check(
        self,
        *,
        estimated_usd: float,
        tier: ModelTier,
        is_autonomous: bool,
        run_spent_usd: float = 0.0,
        run_budget_usd: float | None = None,
        now: datetime | None = None,
    ) -> None:
        """Chaqiruvga ruxsat bormi. Yo'q bo'lsa `BudgetExceededError`.

        Bepul tier'lar (`estimated_usd == 0`) faqat run chegarasidan o'tadi —
        ular budjetni sarflamaydi.
        """
        now = now or datetime.now(UTC)

        # 1) Bitta run uchun chegara (A-07)
        limit = self._settings.run_max_usd if run_budget_usd is None else run_budget_usd
        if run_spent_usd + estimated_usd > limit:
            raise BudgetExceededError(
                f"run chegarasi: {run_spent_usd + estimated_usd:.4f} > {limit:.4f} USD"
            )

        if estimated_usd <= 0:
            return

        # 2) Kuchli model uchun kunlik chaqiruv soni
        if tier is ModelTier.T3_STRONG:
            used = await self._count_tier3_today(now)
            if used >= self._settings.tier3_daily_calls:
                raise BudgetExceededError(
                    f"kuchli model kunlik chegarasi: {used}/{self._settings.tier3_daily_calls}"
                )

        # 3) Kunlik budjet
        spent_today = await self._sum_usd(_day_start(now))
        if spent_today + estimated_usd > self._settings.budget_daily_usd:
            raise BudgetExceededError(
                f"kunlik budjet: {spent_today + estimated_usd:.4f} > "
                f"{self._settings.budget_daily_usd:.2f} USD"
            )

        # 4) Avtonom run'larning ulushi (jadval vazifalari egani cheklab qo'ymasin)
        if is_autonomous:
            autonomous_today = await self._sum_usd_autonomous(_day_start(now))
            share_limit = self._settings.autonomous_daily_budget_usd
            if autonomous_today + estimated_usd > share_limit:
                raise BudgetExceededError(
                    f"avtonom ulush: {autonomous_today + estimated_usd:.4f} > {share_limit:.4f} USD"
                )

        # 5) Oylik budjet
        spent_month = await self._sum_usd(_month_start(now))
        if spent_month + estimated_usd > self._settings.budget_monthly_usd:
            raise BudgetExceededError(
                f"oylik budjet: {spent_month + estimated_usd:.4f} > "
                f"{self._settings.budget_monthly_usd:.2f} USD"
            )

    async def days_left_in_month(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        start = _month_start(now)
        next_month = (start + timedelta(days=32)).replace(day=1)
        return (next_month - now.astimezone(UTC)).days
