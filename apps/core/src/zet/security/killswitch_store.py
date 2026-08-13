"""Killswitch DB persistence — restart-durability (V-33, GAP_ANALYSIS BROKEN #3).

`KillSwitchState` xotirada ishlaydi. Bu modul uni `kill_switch` jadvali
bilan sinxronlaydi:
    - `load_killswitch()`: startup'da bazadan tiklash (yoqilgan bo'lsa,
      qayta ishga tushirilgan protsess ham yoqilgan holatda boshlanadi)
    - `persist_killswitch()`: har `engage()`/`disengage()`dan keyin bazaga
      yozib qo'yish

Bitta qator (`singleton=True`) — jadvalda faqat bir yozuv bo'ladi.

Fail-open: DB yetib bo'lmasa xato yutiladi (log qoladi) — killswitch
xotirada ishlashda davom etadi. Restart'gacha ta'sir yo'q; agar shu payt
protsess qayta ishga tushsa, DB yozuvi eskirgan bo'lishi mumkin (ega
qayta engage/disengage qilib qo'yadi).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.models.security import KillSwitch as KillSwitchRow
from zet.db.session import session_scope
from zet.security.killswitch import KillSwitchState

log = structlog.get_logger(__name__)


async def load_killswitch(
    state: KillSwitchState,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Startup'da bazadan holatni tiklaydi (fail-open)."""
    try:
        async with session_scope(session_factory) as session:
            row = (
                await session.execute(
                    select(KillSwitchRow).where(KillSwitchRow.singleton.is_(True))
                )
            ).scalar_one_or_none()
            if row is None or not row.engaged:
                return
            # Yoqilgan holatni tiklaymiz — `engage()` idempotent, ikkinchi
            # marta chaqirilsa hech nima qilmaydi, shuning uchun manual
            # yozamiz (private atributlarni).
            state._engaged = True
            state._reason = row.reason
            state._engaged_at = row.engaged_at
            state._engaged_by = row.engaged_by
            log.critical(
                "killswitch.restored_from_db",
                reason=row.reason,
                engaged_at=str(row.engaged_at),
            )
    except Exception:
        log.warning("killswitch.load_failed")


async def persist_killswitch(
    state: KillSwitchState,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Joriy holatni bazaga yozadi (upsert, fail-open)."""
    try:
        async with session_scope(session_factory) as session:
            row = (
                await session.execute(
                    select(KillSwitchRow).where(KillSwitchRow.singleton.is_(True))
                )
            ).scalar_one_or_none()
            if row is None:
                row = KillSwitchRow(singleton=True)
                session.add(row)
            row.engaged = state.is_engaged
            row.reason = state.reason
            row.engaged_at = state.engaged_at
            row.engaged_by = state.engaged_by
    except Exception:
        log.warning("killswitch.persist_failed")


__all__ = ["load_killswitch", "persist_killswitch"]
