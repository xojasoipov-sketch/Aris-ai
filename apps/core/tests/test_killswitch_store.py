"""Killswitch DB persistence testlari (V-33, GAP_ANALYSIS BROKEN #3).

Ilgari `KillSwitchState` faqat xotirada edi — docstring "DB'da saqlanadi"
degan da'voga qaramay, hech qayerda yozilmasdi. Restart har safar
holatni yo'q qilardi. Bu testlar aynan restart-simulyatsiyasini qulflaydi:
    - yoqilgan holat DB'ga yozilishi
    - yangi (bo'sh) KillSwitchState instansiyasi shu DB'dan yoqilgan
      holatda tiklanishi (protsess qayta ishga tushishi simulyatsiyasi)
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.security.killswitch import KillSwitchState
from zet.security.killswitch_store import load_killswitch, persist_killswitch


async def test_persist_then_load_restores_engaged_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Restart-simulyatsiyasi: yoqilgan holat DB orqali yangi instansiyaga uzatiladi."""
    # 1. Yoqamiz va DB'ga yozamiz
    ks1 = KillSwitchState()
    ks1.engage(reason="Test emergency", by="unit-test")
    await persist_killswitch(ks1, session_factory)

    # 2. "Protsess qayta ishga tushdi" — yangi bo'sh instansiya
    ks2 = KillSwitchState()
    assert ks2.is_engaged is False  # xotira toza

    # 3. DB'dan tiklaymiz — endi u ham yoqilgan bo'lishi kerak
    await load_killswitch(ks2, session_factory)

    assert ks2.is_engaged is True
    assert ks2.reason == "Test emergency"
    assert ks2.engaged_by == "unit-test"
    assert ks2.engaged_at is not None


async def test_disengage_persists_off_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ochirish ham DB'ga yoziladi — yangi instansiya yoqilgan bo'lib qolmaydi."""
    ks1 = KillSwitchState()
    ks1.engage(reason="Test")
    await persist_killswitch(ks1, session_factory)

    ks1.disengage()
    await persist_killswitch(ks1, session_factory)

    ks2 = KillSwitchState()
    await load_killswitch(ks2, session_factory)

    assert ks2.is_engaged is False


async def test_load_from_empty_db_leaves_state_untouched(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Birinchi ishga tushirishda DB bo'sh — startup crash bermasin."""
    ks = KillSwitchState()
    await load_killswitch(ks, session_factory)  # xato bermasligi kerak
    assert ks.is_engaged is False


async def test_persist_updates_single_row_not_creates_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Bir necha marta yozib qo'ysak ham jadvalda faqat bitta qator bo'ladi
    (`singleton=True` unique constraint)."""
    from sqlalchemy import select

    from zet.db.models.security import KillSwitch as KillSwitchRow

    ks = KillSwitchState()
    ks.engage(reason="a")
    await persist_killswitch(ks, session_factory)

    ks.disengage()
    ks.engage(reason="b")
    await persist_killswitch(ks, session_factory)

    async with session_factory() as session:
        rows = (await session.execute(select(KillSwitchRow))).scalars().all()

    assert len(rows) == 1
    assert rows[0].reason == "b"


async def test_load_reasserts_token_revocation_after_restart(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SR-06 invariant: yoqilgan holat tiklanganda TOKENLAR HAM revoke bo'ladi.

    Adversarial verify topgan gap: agar oldingi protsess engage+persist
    tugagach, revoke_all_capability_tokens_on_killswitch tugashidan
    OLDIN crash bo'lsa — restart'da flag qaytardi-yu, tokenlar faol
    qolardi. Endi load_killswitch buni qayta yoqadi.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select as sa_select

    from zet.db.bootstrap import get_or_create_owner
    from zet.db.models.device import CapabilityToken as CapabilityTokenRow
    from zet.db.models.device import Device as DeviceRow
    from zet.devices.registry import DeviceType

    # 1. Yoqilgan killswitch DB'da bor, LEKIN tokenlar hali faol
    #    (crash-simulation: engage+persist bajarilgan, revoke bajarilmagan).
    async with session_factory() as session:
        owner = await get_or_create_owner(session, external_id="restart-revoke-test")
        device = DeviceRow(
            owner_id=owner.id,
            name="Test iPhone",
            device_type=DeviceType.PHONE,
        )
        session.add(device)
        await session.flush()
        token = CapabilityTokenRow(
            device_id=device.id,
            token_hash="a" * 64,
            capabilities=["camera.snapshot"],
            label="crashed-token",
        )
        session.add(token)
        await session.commit()

    ks = KillSwitchState()
    ks.engage(reason="restart simulation", by="test", now=datetime.now(UTC))
    await persist_killswitch(ks, session_factory)

    # 2. Yangi protsess — load_killswitch qayta revoke qilishi kerak
    ks2 = KillSwitchState()
    await load_killswitch(ks2, session_factory)

    assert ks2.is_engaged is True

    # 3. Token endi revoked bo'lishi kerak
    async with session_factory() as session:
        rows = (
            await session.execute(sa_select(CapabilityTokenRow).where(
                CapabilityTokenRow.token_hash == "a" * 64
            ))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].revoked_at is not None, (
            "Restart'da tokenlar qayta revoke bo'lmadi — SR-06 invariant buzilgan"
        )
