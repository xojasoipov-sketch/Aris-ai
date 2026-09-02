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
        step_position=2,  # B1 audit fix — restart'dan keyin ham saqlanishi kerak
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
    assert tiklangan.step_position == 2, (
        "B1 audit fix: step_position restart'dan keyin yo'qolmasligi kerak"
    )


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


async def test_mission_level_approval_skipped_when_mission_missing(
    session_factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
) -> None:
    """A1 audit (KONSOLIDATSIYA v2) topgan tizimli gap — QOLDIQ holat:
    haqiqatan mavjud bo'lmagan `mission_id` bilan yozishga urinish
    (masalan buzuq/eskirgan ma'lumot) istisnosiz, aniq log bilan
    o'tkazib yuboriladi.

    ESLATMA: BU TEST 2026-08-13'GACHA "mission-approval umuman DB'ga
    yozilmaydi" degan holatni tekshirar edi — HIGH #1 audit fix
    (KONSOLIDATSIYA v2, 2-bo'lim) BUNI TO'LIQ TUZATDI: haqiqiy mission
    mavjud bo'lsa, approval endi DB'ga yoziladi (pastdagi
    `TestMissionApprovalDurability`ga qarang). Bu test faqat "mission
    HAQIQATAN yo'q" chekka holatini — fail-open, xato ko'tarilmasligini
    — tekshiradi."""
    import uuid

    from zet.core.run_checkpoint import persist_approval
    from zet.domain.enums import PermissionLevel

    mission_id = uuid.uuid4()  # HECH QACHON mission jadvalida bo'lmaydi
    svc = ApprovalService(ttl_minutes=30)
    req = svc.request_approval(
        run_id=mission_id,
        mission_id=mission_id,
        reason="mission-level test",
        requested_permission=PermissionLevel.WRITE,
        preview={},
    )

    # ISTISNO KO'TARILMASLIGI KERAK (fail-open)
    await persist_approval(session_factory, req)

    # DB'da yozuv YO'Q — mission HAQIQATAN mavjud emas
    from sqlalchemy import select

    from zet.db.models.security import Approval as ApprovalRow

    async with session_factory() as s:
        row = (
            await s.execute(select(ApprovalRow).where(ApprovalRow.id == req.id))
        ).scalar_one_or_none()
    assert row is None, "Mission mavjud bo'lmasa yozuv bo'lmasligi kerak"


class TestMissionApprovalDurability:
    """HIGH #1 audit fix (KONSOLIDATSIYA v2) — TO'LIQ YECHIM.

    Foydalanuvchi talabi: "approval.run_id NOT NULL FK muammosini hal
    qil — mission-level approval ham Postgres'ga yozilsin. Real
    Postgres bilan: approval yaratilsin -> restart qilinsin -> approval
    holati saqlanganini tasdiqla (aynan AR-01'da qilingan uslubda)."

    Bu klass AYNAN shu ssenariyni SQLite bilan qulflaydi (real Postgres
    dalili — `docs/KONSOLIDATSIYA_V2_REPORT.md`da, A1 bilan bir xil
    ikkinchi-sessiya usuli)."""

    async def test_mission_approval_persists_and_survives_restart(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        session: AsyncSession,
    ) -> None:
        from sqlalchemy import select

        from zet.core.mission import Mission
        from zet.core.mission_repository import MissionRepository
        from zet.db.models.security import Approval as ApprovalRow
        from zet.domain.enums import ApprovalStatus, PermissionLevel

        owner = await get_or_create_owner(session, external_id="e2e-mission-approval")
        await session.commit()

        # Haqiqiy Mission qatori — mission_id endi HAQIQIY FK (soxta emas)
        repo = MissionRepository(session, owner_id=owner.id)
        mission = await repo.create(
            Mission(owner_id=owner.id, objective="Yangi veb-sayt qurish")
        )
        await session.commit()

        # ── 1-SESSIYA: approval yaratamiz va DB'ga yozamiz ───────────
        svc1 = ApprovalService(ttl_minutes=30, session_factory=session_factory)
        req = svc1.request_approval(
            run_id=mission.id,  # MissionEngine.request_approval() naqshi
            mission_id=mission.id,
            reason="Mission risk level requires owner approval",
            requested_permission=PermissionLevel.EXECUTE,
            preview={"objective": mission.objective},
        )
        await svc1.persist_pending(req)

        # ENG MUHIM DALIL #1: DB'da HAQIQIY qator bor — run_id=NULL,
        # mission_id=<mission.id> (soxta run_id emas).
        async with session_factory() as s:
            row = (
                await s.execute(select(ApprovalRow).where(ApprovalRow.id == req.id))
            ).scalar_one_or_none()
        assert row is not None, "HIGH #1 BUZILDI: mission-approval DB'ga yozilmadi"
        assert row.run_id is None
        assert row.mission_id == mission.id
        assert row.status == ApprovalStatus.PENDING

        # ── "RESTART": butunlay yangi ApprovalService, faqat DB'dan ──
        svc2 = ApprovalService(ttl_minutes=30, session_factory=session_factory)
        assert req.id not in svc2._requests

        restored = await load_pending_approvals(session_factory, svc2)
        assert restored == 1

        # ENG MUHIM DALIL #2: restart'dan keyin approval TO'LIQ holati
        # bilan (mission_id, sabab, ruxsat darajasi) tiklangan.
        tiklangan = svc2.get(req.id)
        assert tiklangan.mission_id == mission.id
        assert tiklangan.run_id == mission.id  # in-memory shartnoma saqlangan
        assert tiklangan.status == ApprovalStatus.PENDING
        assert tiklangan.reason == "Mission risk level requires owner approval"
        assert tiklangan.requested_permission == PermissionLevel.EXECUTE

        # `_by_mission` indeksi ham tiklangan — `pending_for_mission()` ishlaydi
        assert svc2.pending_for_mission(mission.id) == [tiklangan]
