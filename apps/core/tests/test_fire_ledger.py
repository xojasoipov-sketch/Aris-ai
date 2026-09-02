"""Scheduled fire ledger testlari (JB-11).

`claim_fire()` — DB-native atomik "compare-and-set". Bir xil
`(rule_id, minute_key)` juftligi ikkinchi marta da'vo qilinolmasligini
isbotlaydi (dublikat rejalashtirilgan ijro oldini olish).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.automation.fire_ledger import claim_fire, claim_fire_standalone
from zet.db.models import Owner


class TestClaimFire:
    async def test_first_claim_succeeds(self, session: AsyncSession, owner: Owner) -> None:
        claimed = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )
        assert claimed is True

    async def test_duplicate_claim_same_minute_fails(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Kritik dalil: ikkinchi da'vo (bir xil rule+daqiqa) rad etiladi."""
        first = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )
        second = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )

        assert first is True
        assert second is False

    async def test_same_rule_different_minute_both_succeed(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Bir xil qoida, BOSHQA daqiqa — ikkalasi ham xavfsiz da'vo qilinadi."""
        first = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )
        second = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:01"
        )

        assert first is True
        assert second is True

    async def test_different_rules_same_minute_both_succeed(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Ikki BOSHQA qoida, bir xil daqiqa — bir-biriga ta'sir qilmaydi."""
        first = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )
        second = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-2", minute_key="2026-08-16 09:00"
        )

        assert first is True
        assert second is True

    async def test_session_remains_usable_after_rejected_claim(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """`IntegrityError` dan keyin sessiya "buzuq" holatda qolmasligi kerak."""
        await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )
        rejected = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-1", minute_key="2026-08-16 09:00"
        )
        assert rejected is False

        # Sessiya hali ham ishlaydi — keyingi (mustaqil) da'vo muvaffaqiyatli.
        still_works = await claim_fire(
            session, owner_id=owner.id, rule_id="rule-3", minute_key="2026-08-16 09:00"
        )
        assert still_works is True


class TestClaimFireStandalone:
    async def test_claims_via_own_session(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        owner: Owner,
    ) -> None:
        claimed = await claim_fire_standalone(
            session_factory,
            owner_external_id=owner.external_id,
            rule_id="rule-standalone",
            minute_key="2026-08-16 09:00",
        )
        assert claimed is True

    async def test_second_standalone_claim_rejected(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        owner: Owner,
    ) -> None:
        first = await claim_fire_standalone(
            session_factory,
            owner_external_id=owner.external_id,
            rule_id="rule-standalone-2",
            minute_key="2026-08-16 09:00",
        )
        second = await claim_fire_standalone(
            session_factory,
            owner_external_id=owner.external_id,
            rule_id="rule-standalone-2",
            minute_key="2026-08-16 09:00",
        )
        assert first is True
        assert second is False

    async def test_fails_open_on_broken_session_factory(self) -> None:
        """DB yetib bo'lmasa — `True` qaytadi (dedup yo'qligi — QO'SHIMCHA
        xavfsizlik, uning yo'qligi tizimni butunlay to'xtatmasligi kerak)."""

        def broken_factory() -> object:
            raise RuntimeError("baza yo'q")

        claimed = await claim_fire_standalone(
            broken_factory,  # type: ignore[arg-type]
            owner_external_id="whoever",
            rule_id="rule-x",
            minute_key="2026-08-16 09:00",
        )
        assert claimed is True
