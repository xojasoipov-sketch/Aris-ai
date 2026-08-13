"""Model Router mark_run_verified testi (A-04 feedback loop).

`CostLedger.verified_ok` ilgari doim NULL edi (chaqirilmasdi). Endi
Orchestrator run yakunida `mark_run_verified` chaqiradi va shu run'ning
barcha yozuvlarini yangilaydi.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.models import CostLedger
from zet.domain.enums import ModelTier, TaskClass
from zet.llm.router import mark_run_verified


async def _seed_ledger_rows(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    count: int = 2,
) -> None:
    async with session_factory() as session:
        for i in range(count):
            session.add(
                CostLedger(
                    run_id=run_id,
                    provider="test",
                    model=f"test-model-{i}",
                    tier=ModelTier.T1_FREE,
                    task_class=TaskClass.SIMPLE,
                    input_tokens=100,
                    output_tokens=50,
                    usd=0.001,
                    latency_ms=200,
                    ok=True,
                )
            )
        await session.commit()


async def test_mark_verified_updates_all_rows_for_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = uuid.uuid4()
    await _seed_ledger_rows(session_factory, run_id, count=3)

    await mark_run_verified(session_factory, run_id, verified_ok=True)

    async with session_factory() as session:
        rows = (
            (await session.execute(select(CostLedger).where(CostLedger.run_id == run_id)))
            .scalars()
            .all()
        )

    assert len(rows) == 3
    assert all(r.verified_ok is True for r in rows)


async def test_mark_verified_false_persists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = uuid.uuid4()
    await _seed_ledger_rows(session_factory, run_id, count=1)

    await mark_run_verified(session_factory, run_id, verified_ok=False)

    async with session_factory() as session:
        row = (
            await session.execute(select(CostLedger).where(CostLedger.run_id == run_id))
        ).scalar_one()

    assert row.verified_ok is False


async def test_mark_verified_does_not_touch_other_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    await _seed_ledger_rows(session_factory, run_a, count=2)
    await _seed_ledger_rows(session_factory, run_b, count=2)

    await mark_run_verified(session_factory, run_a, verified_ok=True)

    async with session_factory() as session:
        b_rows = (
            (await session.execute(select(CostLedger).where(CostLedger.run_id == run_b)))
            .scalars()
            .all()
        )

    assert all(r.verified_ok is None for r in b_rows)


async def test_mark_verified_on_missing_run_is_noop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Yo'q run_id — hech narsa yangilanmaydi, xato yo'q."""
    ghost_id = uuid.uuid4()
    await mark_run_verified(session_factory, ghost_id, verified_ok=True)
    # Xato yo'q — bo'ldi
