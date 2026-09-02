"""db/bootstrap.py testlari — get_or_create_owner."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.bootstrap import get_or_create_owner


class TestGetOrCreateOwner:
    async def test_creates_new_owner(self, session: AsyncSession) -> None:
        owner = await get_or_create_owner(session, external_id="zet-owner")
        assert owner.external_id == "zet-owner"
        assert owner.id is not None

    async def test_returns_existing_owner(self, session: AsyncSession) -> None:
        first = await get_or_create_owner(session, external_id="zet-owner")
        second = await get_or_create_owner(session, external_id="zet-owner")
        assert first.id == second.id

    async def test_uses_display_name_on_create(self, session: AsyncSession) -> None:
        owner = await get_or_create_owner(
            session, external_id="zet-owner", display_name="Xo'jasoipov"
        )
        assert owner.display_name == "Xo'jasoipov"
