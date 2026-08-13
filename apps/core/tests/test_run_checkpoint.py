"""AR-01 minimal yechim uchun testlar (audit BLOCK-4).

Adversarial audit topgan HIGH gap: RunStore va ApprovalService
in-memory. Restart'da AWAITING_APPROVAL run va PENDING approval
yo'qolar edi. Bu testlar aynan restart simulyatsiyasini qulflaydi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.core.orchestrator import RunRecord, RunStore
from zet.core.run_checkpoint import (
    load_pending_approvals,
    load_pending_runs,
    persist_approval,
    persist_run,
)
from zet.db.bootstrap import get_or_create_owner
from zet.domain.command import Command
from zet.domain.enums import PermissionLevel, RunStatus
from zet.security.approvals import ApprovalService


async def test_run_persist_then_load_restores_awaiting_approval(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    """Restart simulyatsiyasi: AWAITING_APPROVAL run DB'da saqlanadi
    va yangi bo'sh RunStore'ga tiklanadi."""
    # 1. Owner ochamiz
    owner = await get_or_create_owner(session, external_id="e2e-run-checkpoint")
    await session.commit()

    # 2. Run yaratamiz va AWAITING_APPROVAL holatga o'tkazamiz
    store1 = RunStore()
    cmd = Command(text="risk qadam yaratish")
    record = store1.create(cmd)
    record.status = RunStatus.AWAITING_APPROVAL
    record.spent_usd = 0.03
    await persist_run(session_factory, record, owner_external_id="e2e-run-checkpoint")

    # 3. "Protsess qayta ishga tushdi" — yangi bo'sh RunStore
    store2 = RunStore()
    assert record.run_id not in store2._runs

    # 4. Startup'da tiklaymiz
    restored_count = await load_pending_runs(session_factory, store2)
    assert restored_count == 1
    assert record.run_id in store2._runs

    tiklangan = store2.get(record.run_id)
    assert tiklangan.status == RunStatus.AWAITING_APPROVAL
    assert tiklangan.command.text == "risk qadam yaratish"
    assert tiklangan.spent_usd == 0.03


async def test_terminal_runs_not_restored(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    """DONE/FAILED/CANCELLED run'lar tiklashga qarab bermaydi — tugagan."""
    owner = await get_or_create_owner(session, external_id="e2e-run-checkpoint-2")
    await session.commit()

    store1 = RunStore()
    done_record = store1.create(Command(text="done"))
    done_record.status = RunStatus.DONE
    await persist_run(session_factory, done_record, owner_external_id="e2e-run-checkpoint-2")

    failed_record = store1.create(Command(text="failed"))
    failed_record.status = RunStatus.FAILED
    failed_record.error = "test error"
    await persist_run(session_factory, failed_record, owner_external_id="e2e-run-checkpoint-2")

    store2 = RunStore()
    count = await load_pending_runs(session_factory, store2)

    # Faqat AWAITING_APPROVAL tiklanadi — bu ikkalasi tiklanmasligi kerak
    assert count == 0
    assert done_record.run_id not in store2._runs
    assert failed_record.run_id not in store2._runs


async def test_approval_persist_then_load_restores_pending(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    """Restart simulyatsiyasi: PENDING approval DB'da saqlanadi
    va yangi ApprovalService'ga tiklanadi."""
    # Approval FK bo'lgani sabab avval Run yozamiz
    owner = await get_or_create_owner(session, external_id="e2e-approval-checkpoint")
    await session.commit()

    store = RunStore()
    record = store.create(Command(text="ega tasdig'i talab qiladi"))
    record.status = RunStatus.AWAITING_APPROVAL
    await persist_run(store._runs and session_factory, record, owner_external_id="e2e-approval-checkpoint")

    # Approval yaratamiz
    svc1 = ApprovalService(ttl_minutes=30)
    req = svc1.request_approval(
        run_id=record.run_id,
        reason="test approval",
        requested_permission=PermissionLevel.WRITE,
        tool_name="test.tool",
        preview={"key": "value"},
    )
    await persist_approval(session_factory, req)

    # "Protsess qayta ishga tushdi" — yangi service
    svc2 = ApprovalService(ttl_minutes=30)
    assert req.id not in svc2._requests

    restored = await load_pending_approvals(session_factory, svc2)
    assert restored == 1
    assert req.id in svc2._requests

    tiklangan = svc2.get(req.id)
    assert tiklangan.run_id == record.run_id
    assert tiklangan.reason == "test approval"
    assert tiklangan.tool_name == "test.tool"
    assert tiklangan.preview == {"key": "value"}


async def test_expired_approvals_not_restored(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    """Muddati o'tgan approval'lar tiklanmaydi — expired approval bekor."""
    from zet.db.models.security import Approval as ApprovalRow

    owner = await get_or_create_owner(session, external_id="e2e-expired")
    await session.commit()

    store = RunStore()
    record = store.create(Command(text="expired"))
    record.status = RunStatus.AWAITING_APPROVAL
    await persist_run(session_factory, record, owner_external_id="e2e-expired")

    # Muddati o'tgan approval'ni DIRECT DB'ga yozamiz
    async with session_factory() as s:
        row = ApprovalRow(
            run_id=record.run_id,
            reason="expired approval",
            requested_permission=PermissionLevel.WRITE,
            tool_name="test.tool",
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # 1 soat oldin!
        )
        s.add(row)
        await s.commit()

    svc = ApprovalService()
    restored = await load_pending_approvals(session_factory, svc)
    assert restored == 0, "Muddati o'tgan approval tiklanmasligi kerak"


async def test_persist_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    """Bir xil run/approval'ni ikki marta yozib qo'ysak, jadvalda bir qator."""
    from sqlalchemy import func, select

    from zet.db.models.run import Run as RunRow

    owner = await get_or_create_owner(session, external_id="e2e-idempotent")
    await session.commit()

    store = RunStore()
    record = store.create(Command(text="idempotent"))
    record.status = RunStatus.PLANNING
    await persist_run(session_factory, record, owner_external_id="e2e-idempotent")

    # Yangilaymiz va qayta yozib qo'yamiz
    record.status = RunStatus.EXECUTING
    record.spent_usd = 0.10
    await persist_run(session_factory, record, owner_external_id="e2e-idempotent")

    async with session_factory() as s:
        result = await s.execute(
            select(func.count(RunRow.id)).where(RunRow.id == record.run_id)
        )
        count = result.scalar_one()

    assert count == 1, "Ikki marta yozish bitta qator qoldirishi kerak (idempotent)"


async def test_fail_open_when_db_unreachable() -> None:
    """DB yetib bo'lmasa persist_run/persist_approval xato ko'tarmaydi
    — asosiy oqim (memory RunStore) davom etadi."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    # Ishlamaydigan factory — chaqirilganda istisno tashlaydi
    class _BrokenFactory:
        def __call__(self):
            msg = "DB unreachable"
            raise RuntimeError(msg)

    store = RunStore()
    record = store.create(Command(text="fail-open"))
    record.status = RunStatus.PLANNING

    # ISTISNO KO'TARILMASLIGI KERAK
    await persist_run(_BrokenFactory(), record, owner_external_id="test")  # type: ignore[arg-type]
    # Load ham fail-open
    result = await load_pending_runs(_BrokenFactory(), store)  # type: ignore[arg-type]
    assert result == 0
