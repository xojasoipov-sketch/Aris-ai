"""KillSwitch yon-ta'sirlari — DB'ga bog'liq amallar (SR-06).

`KillSwitchState` DB'ni bilmaydi (ataylab — barcha o'rinlarda mavjud
bo'lishi kerak, hattoki DB yiqilganda ham flag ishlashda davom etsin).
Yon ta'sirlar (masalan capability tokenlarni bekor qilish) esa aynan
DB'ni talab qiladi — shuning uchun ular alohida modulda.

Naqsh `killswitch_store.py` bilan bir xil: fail-open, `session_factory`
bilan qisqa sessiya, log yozib qaytish.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.models.device import CapabilityToken as CapabilityTokenRow
from zet.db.models.device import Device as DeviceRow
from zet.db.models.owner import Owner as OwnerRow
from zet.db.session import session_scope
from zet.devices.repository import DeviceDBRepository
from zet.security.killswitch import KillSwitchState

log = structlog.get_logger(__name__)


async def revoke_all_capability_tokens_on_killswitch(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Barcha egalarning faol capability tokenlarini bekor qiladi.

    Killswitch — global miqyosli (bir insonlik OS bo'lgani uchun bir
    ega, lekin dizayn ko'p-egali kelajakka ochiq qoldirilgan). Shuning
    uchun bu funksiya `owner_id` filtrisiz butun jadvalni yopadi.

    Returns:
        Bekor qilingan tokenlar soni. DB yetib bo'lmasa `0` (fail-open).
    """
    from datetime import UTC, datetime

    try:
        async with session_scope(session_factory) as session:
            result = await session.execute(
                update(CapabilityTokenRow)
                .where(CapabilityTokenRow.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
            count = int(result.rowcount or 0)
    except Exception:
        log.warning("killswitch.token_revoke_failed", exc_info=True)
        return 0

    if count:
        log.critical("killswitch.tokens_bulk_revoked", count=count)
    return count


def build_killswitch_revoke_callback(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], Awaitable[None]]:
    """`KillSwitchState.register_engage_callback` uchun hook yasaydi.

    Qaytariladigan funksiya har `engage()`da chaqiriladi va aynan bir
    ish qiladi — `revoke_all_capability_tokens_on_killswitch` ni await
    qilish. `KillSwitchState` uni fon vazifasi sifatida ishga tushiradi
    (event loop mavjud bo'lganda), fail-open.
    """

    async def _cb() -> None:
        await revoke_all_capability_tokens_on_killswitch(session_factory)

    return _cb


async def revoke_owner_tokens(
    session_factory: async_sessionmaker[AsyncSession], *, owner_external_id: str
) -> int:
    """Bitta egaga tegishli tokenlarni bekor qiladi (SR-04 Telegram runner uchun).

    `DeviceDBRepository.revoke_all_tokens` bilan bir xil natijani beradi,
    lekin session/owner qidiruvni ichiga oladi — chaqiruvchi (Telegram
    runner) faqat bitta chaqiruv bilan tugatadi.
    """
    try:
        async with session_scope(session_factory) as session:
            owner_row = (
                await session.execute(
                    select(OwnerRow).where(OwnerRow.external_id == owner_external_id)
                )
            ).scalar_one_or_none()
            if owner_row is None:
                # Egasi hali DB'da yo'q — hech narsa bekor qilish shart emas.
                return 0
            repo = DeviceDBRepository(session, owner_id=owner_row.id)
            return await repo.revoke_all_tokens()
    except Exception:
        log.warning("killswitch.owner_token_revoke_failed", exc_info=True)
        return 0


# `DeviceRow` re-eksporti — funksiyaga to'g'ridan-to'g'ri kerak bo'lmasa
# ham import izlar aniq turish uchun qo'yiladi.
_ = DeviceRow


__all__ = [
    "build_killswitch_revoke_callback",
    "revoke_all_capability_tokens_on_killswitch",
    "revoke_owner_tokens",
]


def register_killswitch_engage_callback(
    state: KillSwitchState,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Yordamchi — bitta chaqiruvda hook'ni qurish va ro'yxatga olish."""
    state.register_engage_callback(build_killswitch_revoke_callback(session_factory))
