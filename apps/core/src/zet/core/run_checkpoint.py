"""Run/Approval DB checkpoint — AR-01 minimal yechim.

NEGA. Adversarial audit (FINAL_READINESS_AUDIT.md §G-01/H-01) topgan
HIGH gap: `RunStore._runs` va `ApprovalService._requests` in-memory
dict edi. Restart/crash paytida:

    - AWAITING_APPROVAL run yo'qoladi → ega hech qachon tasdiqlay
      olmaydi (approve URL 404 qaytaradi)
    - Pending Approval yo'qoladi → ega Telegram/CLI'dan tasdiq berish
      imkoni yo'q
    - Ko'p soatlab davom etishi mumkin bo'lgan run halok bo'ladi

Bu modul minimal yechim beradi: mavjud `db/models/run.py::Run` va
`db/models/security.py::Approval` jadvallariga write-through +
startup'da qayta yuklash. `RunStore` API o'zgarmaydi — chaqiruvchilar
(`Orchestrator`, `api/routes/run.py`) hech nima o'zgartirmaydi.

Yechim MINIMAL — Task #57 (butun run/approval domen refactori)
o'rniga faqat davomiylik qismini yopadi:

    - CREATE (yangi run/approval) → INSERT + commit
    - UPDATE (status, plan, spent_usd, verified_ok) → UPDATE + commit
    - LOAD (startup) → AWAITING_APPROVAL run'lar + PENDING approval'lar
      qayta xotira store'iga tiklanadi

Fail-open: DB yetib bo'lmasa xato yutiladi, xotira store ishlashda
davom etadi. AR-01 to'liq yopishning kichik, sinaladigan qadami.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.bootstrap import get_or_create_owner
from zet.db.models.run import Run as RunRow
from zet.db.models.security import Approval as ApprovalRow
from zet.db.session import session_scope
from zet.domain.enums import ApprovalStatus, RunStatus, RunTrigger

if TYPE_CHECKING:
    from zet.core.orchestrator import RunRecord, RunStore
    from zet.security.approvals import ApprovalRequest, ApprovalService

log = structlog.get_logger(__name__)


# ─── Run persistence ──────────────────────────────────────────────


async def persist_run(
    session_factory: async_sessionmaker[AsyncSession],
    record: RunRecord,
    *,
    owner_external_id: str,
) -> None:
    """RunRecord'ni `run` jadvaliga UPSERT qiladi (fail-open).

    Har status o'zgarganida chaqiriladi. Idempotent (id bilan upsert).
    """
    try:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id=owner_external_id)
            existing = (
                await session.execute(select(RunRow).where(RunRow.id == record.run_id))
            ).scalar_one_or_none()

            if existing is None:
                # Yangi run — INSERT
                row = RunRow(
                    id=record.run_id,
                    owner_id=owner.id,
                    trigger=RunTrigger.MANUAL,
                    command_text=record.command.text,
                    status=record.status,
                    trace_id=str(record.run_id)[:32],
                    spent_usd=record.spent_usd,
                    verified_ok=record.verified_ok,
                    error=record.error,
                    result_summary=record.result_summary,
                )
                session.add(row)
            else:
                # Mavjud — UPDATE
                existing.status = record.status
                existing.spent_usd = record.spent_usd
                existing.verified_ok = record.verified_ok
                existing.error = record.error
                existing.result_summary = record.result_summary
                if record.status.is_terminal:
                    existing.finished_at = datetime.now(UTC)
    except SQLAlchemyError:
        log.warning("run.persist_failed", run_id=str(record.run_id))
    except Exception:
        log.warning("run.persist_failed_unexpected", run_id=str(record.run_id))


async def load_pending_runs(
    session_factory: async_sessionmaker[AsyncSession],
    store: RunStore,
) -> int:
    """Startup'da AWAITING_APPROVAL run'larni xotira store'iga tiklaydi.

    Bu chalasidan yopilmagan run oqimini davom ettirish uchun kerak.
    DONE/FAILED/CANCELLED run'lar tiklashga qarab hech narsa bermaydi
    — ular allaqachon tugagan.

    Returns:
        Tiklangan run soni.
    """
    from zet.core.orchestrator import RunRecord
    from zet.domain.command import Command

    try:
        async with session_scope(session_factory) as session:
            rows = (
                await session.execute(
                    select(RunRow).where(RunRow.status == RunStatus.AWAITING_APPROVAL)
                )
            ).scalars().all()

            for row in rows:
                record = RunRecord(
                    run_id=row.id,
                    command=Command(text=row.command_text),
                    status=row.status,
                    spent_usd=row.spent_usd,
                    verified_ok=row.verified_ok,
                    error=row.error,
                    result_summary=row.result_summary,
                )
                store._runs[row.id] = record  # noqa: SLF001 — internal restore

            if rows:
                log.warning("run.restored_from_db", count=len(rows))
            return len(rows)
    except SQLAlchemyError:
        log.warning("run.load_failed")
        return 0
    except Exception:
        log.warning("run.load_failed_unexpected")
        return 0


# ─── Approval persistence ─────────────────────────────────────────


async def persist_approval(
    session_factory: async_sessionmaker[AsyncSession],
    request: ApprovalRequest,
    *,
    run_owner_id: uuid.UUID | None = None,
) -> None:
    """ApprovalRequest'ni `approval` jadvaliga UPSERT qiladi (fail-open).

    Har `request_approval()`/`approve()`/`reject()`/`check_expired()`
    dan keyin chaqiriladi. Idempotent.

    MA'LUM CHEKLOV (A1 audit, real Postgres'da topilgan): `approval.run_id`
    ustuni `run.id`ga FK (NOT NULL). Mission-darajali so'rovlar
    (`MissionEngine.request_approval`) `run_id=mission.id` beradi — bu
    UUID `run` jadvalida HECH QACHON bo'lmaydi (mission haqiqiy Run emas).
    Bunday holatda INSERT DOIM `ForeignKeyViolationError` bilan yiqiladi.
    Avval bu xato SQLAlchemyError sifatida yutilardi va "persist_failed"
    warning yozardi — go'yo tasodifiy DB xatosi bo'lgandek, aslida esa
    HAR SAFAR takrorlanadigan, kutilgan holat edi. Endi run mavjudligini
    OLDINDAN tekshiramiz va aniq log bilan o'tkazib yuboramiz — real
    tasodifiy xatolardan (masalan tarmoq uzilishi) farqlanishi uchun.
    TO'LIQ YECHIM (keyingi bosqich): `approval.run_id`ni nullable qilish +
    mission-level approval'lar uchun alohida saqlash yo'li — bu Alembic
    migratsiya talab qiladi, shu funksiya darajasida hal qilinmaydi.
    """
    try:
        async with session_scope(session_factory) as session:
            run_exists = (
                await session.execute(
                    select(RunRow.id).where(RunRow.id == request.run_id)
                )
            ).scalar_one_or_none()
            if run_exists is None:
                log.info(
                    "approval.persist_skipped_no_backing_run",
                    approval_id=str(request.id),
                    run_id=str(request.run_id),
                    mission_id=(
                        str(request.mission_id)
                        if getattr(request, "mission_id", None)
                        else None
                    ),
                )
                return

            existing = (
                await session.execute(
                    select(ApprovalRow).where(ApprovalRow.id == request.id)
                )
            ).scalar_one_or_none()

            if existing is None:
                # INSERT — `step_id` (UUID, `step` jadvaliga FK) doim None:
                # `step` jadvali hech qachon to'ldirilmaydi. `step_position`
                # (B1 audit fix, migratsiya 0010) esa ApprovalRequest'ning
                # `step_position: int`ini to'g'ridan-to'g'ri saqlaydi —
                # FK'ga bog'liq emas, shuning uchun restart'dan keyin ham
                # "aynan qaysi reja qadami" ma'lumoti yo'qolmaydi.
                row = ApprovalRow(
                    id=request.id,
                    run_id=request.run_id,
                    step_id=None,
                    step_position=request.step_position,
                    tool_name=request.tool_name,
                    reason=request.reason,
                    requested_permission=request.requested_permission,
                    status=request.status,
                    preview=request.preview,
                    expires_at=request.expires_at,
                    decided_at=request.decided_at,
                    decision_note=request.decision_note,
                )
                session.add(row)
            else:
                # UPDATE
                existing.status = request.status
                existing.decided_at = request.decided_at
                existing.decision_note = request.decision_note
    except SQLAlchemyError:
        log.warning("approval.persist_failed", approval_id=str(request.id), exc_info=True)
    except Exception:
        log.warning(
            "approval.persist_failed_unexpected", approval_id=str(request.id), exc_info=True
        )


async def load_pending_approvals(
    session_factory: async_sessionmaker[AsyncSession],
    service: ApprovalService,
) -> int:
    """Startup'da PENDING (muddati o'tmagan) approval'larni xotira service'ga tiklaydi.

    Fail-open. Returns tiklangan approval soni.
    """
    from zet.security.approvals import ApprovalRequest

    try:
        now = datetime.now(UTC)
        async with session_scope(session_factory) as session:
            rows = (
                await session.execute(
                    select(ApprovalRow).where(
                        ApprovalRow.status == ApprovalStatus.PENDING,
                        ApprovalRow.expires_at > now,
                    )
                )
            ).scalars().all()

            for row in rows:
                # ApprovalRequest'ni direct field'lar bilan qurish.
                # B1 audit fix: `step_position` endi haqiqiy qiymatdan
                # tiklanadi (migratsiya 0010'dan oldin yozilgan eski
                # qatorlarda ustun NULL bo'ladi — bu holatda None qoladi,
                # fail-open, xato ko'tarilmaydi).
                req = ApprovalRequest(
                    run_id=row.run_id,
                    step_position=row.step_position,
                    reason=row.reason,
                    requested_permission=row.requested_permission,
                    tool_name=row.tool_name,
                    preview=row.preview,
                    ttl_minutes=1,  # keyingi qadamda expires_at bilan bekor qilinadi
                    now=row.created_at if row.created_at else now,
                )
                # ID va expires_at ni tiklaymiz (private field'lar)
                req.id = row.id
                req.expires_at = row.expires_at
                req.status = row.status

                service._requests[req.id] = req  # noqa: SLF001 — internal restore
                service._by_run.setdefault(row.run_id, []).append(req.id)  # noqa: SLF001

            if rows:
                log.warning("approval.restored_from_db", count=len(rows))
            return len(rows)
    except SQLAlchemyError:
        log.warning("approval.load_failed")
        return 0
    except Exception:
        log.warning("approval.load_failed_unexpected")
        return 0


__all__ = [
    "load_pending_approvals",
    "load_pending_runs",
    "persist_approval",
    "persist_run",
]
