"""DB darajasidagi bootstrap yordamchilari (Bo'lim 2, 12).

ZET bir egali tizim (V-02) — `owner` jadvalida har doim bitta faol qator
bo'ladi. `get_or_create_owner()` shu qatorni `external_id` (odatda
`Settings.owner_id`) bo'yicha topadi yoki yaratadi.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.owner import Owner


async def get_or_create_owner(
    session: AsyncSession,
    *,
    external_id: str,
    display_name: str = "owner",
) -> Owner:
    """Bitta egani `external_id` bo'yicha topadi yoki yaratadi.

    Args:
        session: faol DB sessiyasi
        external_id: barqaror identifikator (masalan `Settings.owner_id`)
        display_name: ko'rsatiladigan ism (faqat yaratishda ishlatiladi)

    Returns:
        Mavjud yoki yangi yaratilgan `Owner`.
    """
    result = await session.execute(select(Owner).where(Owner.external_id == external_id))
    owner = result.scalar_one_or_none()
    if owner is not None:
        return owner

    owner = Owner(external_id=external_id, display_name=display_name)
    session.add(owner)
    await session.flush()
    return owner


__all__ = ["get_or_create_owner"]
