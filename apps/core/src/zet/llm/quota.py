"""Free tier kvota hisobchisi (ADR-0006 §3).

Free tier'lar **pulda emas, so'rovlar sonida** cheklanadi (RPM / RPD).
`CostLedger` bu chegarani ko'rmaydi — shuning uchun alohida hisobchi kerak.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models import QuotaLedger
from zet.llm.catalog import ModelSpec

WINDOW_DAY = "day"
WINDOW_MINUTE = "minute"


def day_window(now: datetime) -> tuple[datetime, datetime]:
    """UTC sutkasining boshi va tugashi."""
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def minute_window(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(second=0, microsecond=0)
    return start, start + timedelta(minutes=1)


class QuotaManager:
    """Provayder kvotalarini o'qiydi va yozadi.

    Fail-closed emas, fail-over: kvota tugagan provayder **o'tkazib yuboriladi**,
    router keyingi nomzodga o'tadi.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_row(
        self, provider: str, window: str, window_start: datetime
    ) -> QuotaLedger | None:
        stmt = select(QuotaLedger).where(
            QuotaLedger.provider == provider,
            QuotaLedger.window == window,
            QuotaLedger.window_start == window_start,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def has_quota(self, spec: ModelSpec, *, now: datetime) -> bool:
        """Modelda hozir bo'sh kvota bormi.

        Kvotasi e'lon qilinmagan (`free_rpd`/`free_rpm` = None) provayderlar
        cheklanmagan deb hisoblanadi — ular odatda pullik va budjet nazorat qiladi.
        """
        limits = (
            (WINDOW_DAY, spec.free_rpd, day_window(now)[0]),
            (WINDOW_MINUTE, spec.free_rpm, minute_window(now)[0]),
        )
        for window, limit, start in limits:
            if limit is None:
                continue
            row = await self._get_row(spec.provider, window, start)
            if row is not None and row.used >= limit:
                return False
        return True

    async def record_use(self, spec: ModelSpec, *, now: datetime) -> None:
        """Muvaffaqiyatli chaqiruvni hisobga olish."""
        windows = (
            (WINDOW_DAY, spec.free_rpd, day_window(now)),
            (WINDOW_MINUTE, spec.free_rpm, minute_window(now)),
        )
        for window, limit, (start, end) in windows:
            if limit is None:
                continue
            row = await self._get_row(spec.provider, window, start)
            if row is None:
                row = QuotaLedger(
                    provider=spec.provider,
                    window=window,
                    window_start=start,
                    used=1,
                    limit_value=limit,
                    resets_at=end,
                )
                self._session.add(row)
            else:
                row.used += 1
        await self._session.flush()

    async def remaining(self, spec: ModelSpec, *, now: datetime) -> dict[str, int | None]:
        """Qolgan kvota — `z cost` hisobotida ko'rsatiladi."""
        result: dict[str, int | None] = {WINDOW_DAY: None, WINDOW_MINUTE: None}
        for window, limit, start in (
            (WINDOW_DAY, spec.free_rpd, day_window(now)[0]),
            (WINDOW_MINUTE, spec.free_rpm, minute_window(now)[0]),
        ):
            if limit is None:
                continue
            row = await self._get_row(spec.provider, window, start)
            result[window] = limit if row is None else row.remaining
        return result
