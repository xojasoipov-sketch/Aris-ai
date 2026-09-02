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
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.bootstrap import get_or_create_owner
from zet.db.models.run import Run as RunRow
from zet.db.models.security import Approval as ApprovalRow
from zet.db.session import session_scope
from zet.domain.enums import ApprovalStatus, RunStatus, RunTrigger, StepStatus
from zet.domain.tool import ToolResult

if TYPE_CHECKING:
    from zet.core.executor import StepResult
    from zet.core.orchestrator import RunRecord, RunStore
    from zet.domain.plan import Plan
    from zet.security.approvals import ApprovalRequest, ApprovalService

log = structlog.get_logger(__name__)


# ─── Run persistence ──────────────────────────────────────────────


async def persist_run(
    session_factory: async_sessionmaker[AsyncSession],
    record: RunRecord,
    *,
    owner_external_id: str,
) -> bool:
    """RunRecord'ni `run` jadvaliga UPSERT qiladi (fail-open).

    Har status o'zgarganida chaqiriladi. Idempotent (id bilan upsert).

    Returns:
        JB-13: `True` — DB'ga haqiqatan yozildi (commit muvaffaqiyatli).
        `False` — xato yutildi (fail-open, eski chaqiruvchilar buni
        e'tiborsiz qoldiradi — qaytish qiymati YANGI, orqaga moslik
        buzilmaydi). `RunStore.ensure_placeholder()` bu bayroqni
        `MissionEngine`ga uzatib, DB haqiqatan yozilmagan bo'lsa
        `attach_run()`ni FK-halokatga uchratadigan pre-attach yo'lidan
        xavfsiz voz kechish uchun ishlatadi.
    """
    try:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id=owner_external_id)
            existing = (
                await session.execute(select(RunRow).where(RunRow.id == record.run_id))
            ).scalar_one_or_none()

            # HIGH #2 audit fix (KONSOLIDATSIYA v2): `record.plan`ni ham
            # yozamiz — usiz real restart'dan keyin `resume()` "Reja
            # mavjud emas" bilan darhol yiqilardi, `completed_steps`
            # checkpoint hech qachon ishlatilmas edi (yuqoridagi model
            # izohiga qarang). `Plan` — frozen Pydantic BaseModel,
            # to'g'ridan-to'g'ri JSON serializatsiya qilinadi.
            plan_snapshot = record.plan.model_dump(mode="json") if record.plan is not None else None

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
                    plan_snapshot=plan_snapshot,
                )
                session.add(row)
            else:
                # Mavjud — UPDATE
                existing.status = record.status
                existing.spent_usd = record.spent_usd
                existing.verified_ok = record.verified_ok
                existing.error = record.error
                existing.result_summary = record.result_summary
                if plan_snapshot is not None:
                    # Reja odatda faqat PLANNING'da bir marta o'rnatiladi
                    # va o'zgarmaydi — recovery kengaytirsa (`record.plan
                    # = outcome.extended_plan`) YANGI qiymat yoziladi.
                    existing.plan_snapshot = plan_snapshot
                if record.status.is_terminal:
                    existing.finished_at = datetime.now(UTC)
    except SQLAlchemyError:
        log.warning("run.persist_failed", run_id=str(record.run_id))
        return False
    except Exception:
        log.warning("run.persist_failed_unexpected", run_id=str(record.run_id))
        return False
    return True


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
    from zet.domain.plan import Plan as DomainPlan

    try:
        async with session_scope(session_factory) as session:
            rows = (
                await session.execute(
                    select(RunRow).where(RunRow.status == RunStatus.AWAITING_APPROVAL)
                )
            ).scalars().all()

            for row in rows:
                # HIGH #2 audit fix: `plan_snapshot`ni tiklaymiz — usiz
                # `resume()` "Reja mavjud emas" bilan darhol yiqilardi.
                # Buzuq/eski (migratsiya 0011'dan oldingi) qatorlarda
                # `None` bo'lishi mumkin — fail-open, `resume()` o'zi
                # aniq `OrchestratorError` beradi (log yutilmaydi).
                restored_plan: DomainPlan | None = None
                if row.plan_snapshot:
                    try:
                        restored_plan = DomainPlan.model_validate(row.plan_snapshot)
                    except Exception:
                        log.warning("run.plan_snapshot_invalid", run_id=str(row.id))
                record = RunRecord(
                    run_id=row.id,
                    command=Command(text=row.command_text),
                    plan=restored_plan,
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


async def load_run_by_id(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> RunRecord | None:
    """Bitta run yozuvini — ISTALGAN status — DB'dan `RunRecord`ga tiklaydi.

    JB-13 Gap #1: `load_pending_runs()`ning umumlashtirilgan varianti.
    U FAQAT startup'da, FAQAT AWAITING_APPROVAL run'larni ommaviy
    tiklaydi. Bu funksiya esa BITTA run'ni, QAYSI STATUS bo'lishidan
    qat'i nazar (EXECUTING ham), on-demand tiklaydi — `MissionEngine.
    execute()` restart/crash'dan keyin "bu mission uchun oldingi run
    hali tirikmi?" deb so'raganda ishlatiladi (`RunStore.materialize()`
    orqali). Fail-open: DB xatosi yoki topilmasa `None`.
    """
    from zet.core.orchestrator import RunRecord
    from zet.domain.command import Command
    from zet.domain.plan import Plan as DomainPlan

    try:
        async with session_scope(session_factory) as session:
            row = (
                await session.execute(select(RunRow).where(RunRow.id == run_id))
            ).scalar_one_or_none()
            if row is None:
                return None

            restored_plan: DomainPlan | None = None
            if row.plan_snapshot:
                try:
                    restored_plan = DomainPlan.model_validate(row.plan_snapshot)
                except Exception:
                    log.warning("run.plan_snapshot_invalid", run_id=str(row.id))

            return RunRecord(
                run_id=row.id,
                command=Command(text=row.command_text),
                plan=restored_plan,
                status=row.status,
                spent_usd=row.spent_usd,
                verified_ok=row.verified_ok,
                error=row.error,
                result_summary=row.result_summary,
            )
    except SQLAlchemyError:
        log.warning("run.load_by_id_failed", run_id=str(run_id))
        return None
    except Exception:
        log.warning("run.load_by_id_failed_unexpected", run_id=str(run_id))
        return None


# ─── Step persistence (HIGH #2 audit fix — idempotent resume) ────


def _serialize_step_result(result: StepResult) -> dict[str, Any]:
    """`StepResult`ni JSON-saqlanadigan dict'ga aylantiradi.

    `step: PlanStep` maydoni SAQLANMAYDI — qayta tiklashda `Plan.steps`
    ichidan `position` bo'yicha topiladi (`load_completed_steps`ga
    qarang). Faqat NATIJA saqlanadi."""
    return {
        "status": result.status.value,
        "output": result.output,
        "error": result.error,
        "retries": result.retries,
        "cost_usd": result.cost_usd,
        "tool_result": (
            result.tool_result.model_dump(mode="json")
            if result.tool_result is not None
            else None
        ),
    }


def _deserialize_step_result(step, data: dict[str, Any]) -> StepResult:  # type: ignore[no-untyped-def]
    from zet.core.executor import StepResult as _StepResult

    raw_tool_result = data.get("tool_result")
    tool_result = ToolResult.model_validate(raw_tool_result) if raw_tool_result else None
    return _StepResult(
        step,
        status=StepStatus(data.get("status", StepStatus.DONE.value)),
        tool_result=tool_result,
        error=data.get("error"),
        retries=int(data.get("retries", 0) or 0),
        output=data.get("output") or "",
        cost_usd=float(data.get("cost_usd", 0.0) or 0.0),
    )


async def persist_step_result(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    position: int,
    result: StepResult,
) -> None:
    """Bitta DONE qadam natijasini `run.completed_steps` JSON ustuniga yozadi.

    NEGA per-step (per-run emas): resume() paytida XATOLIK BO'LSA HAM
    (masalan 3-qadam yiqilib run FAILED bo'lsa), 1- va 2-qadam
    natijalari allaqachon yozilgan bo'ladi — keyingi qayta urinish
    (agar bo'lsa) ularni yana takrorlamaydi. Faqat `StepStatus.DONE`
    chaqiruvchi tomonidan uzatiladi deb kutiladi (`Orchestrator`
    FAILED/SKIPPED natijalarni bu yerga yubormaydi — ular qayta
    baholanishi kerak, checkpoint qilinmaydi).

    Fail-open — DB yetib bo'lmasa xato yutiladi (run xotirada davom etadi,
    faqat checkpoint yo'qoladi — keyingi resume() battar holatda emas,
    shunchaki eski — qayta bajarish — xatti-harakatga tushadi).
    """
    try:
        async with session_scope(session_factory) as session:
            row = (
                await session.execute(select(RunRow).where(RunRow.id == run_id))
            ).scalar_one_or_none()
            if row is None:
                log.info("step.persist_skipped_no_backing_run", run_id=str(run_id), position=position)
                return
            current = dict(row.completed_steps or {})
            current[str(position)] = _serialize_step_result(result)
            row.completed_steps = current
    except SQLAlchemyError:
        log.warning("step.persist_failed", run_id=str(run_id), position=position, exc_info=True)
    except Exception:
        log.warning(
            "step.persist_failed_unexpected", run_id=str(run_id), position=position, exc_info=True
        )


async def load_completed_steps(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    plan: Plan,
) -> dict[int, StepResult]:
    """Run'ning avval DONE bo'lgan qadamlarini tiklaydi.

    `Executor.execute_plan(completed_steps=...)`ga to'g'ridan-to'g'ri
    uzatiladi — u shu pozitsiyalarni QAYTA BAJARMAYDI (HIGH #2 audit
    fix). `plan.steps`dan mos `PlanStep`ni topib olamiz — DB'da faqat
    natija saqlanadi, qadam ta'rifi emas (reja allaqachon `record.plan`da
    bor).

    Fail-open: DB yetib bo'lmasa yoki position `plan.steps`da topilmasa
    (masalan eski/mos kelmaydigan reja) — o'sha yozuv o'tkazib
    yuboriladi, xato ko'tarilmaydi.
    """
    try:
        async with session_scope(session_factory) as session:
            row = (
                await session.execute(select(RunRow).where(RunRow.id == run_id))
            ).scalar_one_or_none()
            if row is None or not row.completed_steps:
                return {}
            by_position = {s.position: s for s in plan.steps}
            restored: dict[int, StepResult] = {}
            for pos_str, data in row.completed_steps.items():
                try:
                    position = int(pos_str)
                except (TypeError, ValueError):
                    continue
                step = by_position.get(position)
                if step is None:
                    # Reja o'zgargan (masalan yangi Planner javobi) —
                    # bu pozitsiya endi mavjud emas, tashlab yuboramiz.
                    continue
                restored[position] = _deserialize_step_result(step, data)
            if restored:
                log.info(
                    "step.restored_from_db",
                    run_id=str(run_id),
                    positions=sorted(restored.keys()),
                )
            return restored
    except SQLAlchemyError:
        log.warning("step.load_failed", run_id=str(run_id))
        return {}
    except Exception:
        log.warning("step.load_failed_unexpected", run_id=str(run_id))
        return {}


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

    HIGH #1 audit fix (KONSOLIDATSIYA v2) — TO'LIQ YECHIM. Ilgari
    `approval.run_id` NOT NULL FK edi (`run.id`ga). Mission-darajali
    so'rovlar (`MissionEngine.request_approval`) `run_id=mission.id`
    berardi — bu UUID `run` jadvalida HECH QACHON bo'lmaydi (mission
    haqiqiy Run emas). INSERT HAR SAFAR `ForeignKeyViolationError` bilan
    yiqilardi (A1 audit, real Postgres'da topilgan) — avval faqat
    "graceful skip" bilan yumshatilgan edi (approval DB'ga HECH QACHON
    yozilmasdi, restart'da mission-level pending approval yo'qolardi).

    Endi (migratsiya 0012): `approval.run_id` NULLABLE, yangi
    `approval.mission_id` — `mission.id`ga HAQIQIY FK. Ikkalasidan
    QAYSI BIRI to'ldirilishi `request.mission_id` borligiga qarab
    aniqlanadi (`ApprovalRequest.mission_id` — mavjud domen maydoni,
    `MissionEngine.request_approval()` allaqachon to'ldiradi):
        - `mission_id` bor → mission-darajali: `run_id=None,
          mission_id=<mission.id>` — mission mavjudligi OLDINDAN
          tekshiriladi (xuddi run uchun bo'lgani kabi).
        - `mission_id` yo'q → step-darajali (eski xatti-harakat):
          `run_id=<run.id>, mission_id=None`.
    """
    try:
        async with session_scope(session_factory) as session:
            mission_id = getattr(request, "mission_id", None)

            if mission_id is not None:
                from zet.db.models.mission import Mission as MissionRow

                mission_exists = (
                    await session.execute(
                        select(MissionRow.id).where(MissionRow.id == mission_id)
                    )
                ).scalar_one_or_none()
                if mission_exists is None:
                    log.info(
                        "approval.persist_skipped_no_backing_mission",
                        approval_id=str(request.id),
                        mission_id=str(mission_id),
                    )
                    return
                effective_run_id: uuid.UUID | None = None
            else:
                run_exists = (
                    await session.execute(select(RunRow.id).where(RunRow.id == request.run_id))
                ).scalar_one_or_none()
                if run_exists is None:
                    log.info(
                        "approval.persist_skipped_no_backing_run",
                        approval_id=str(request.id),
                        run_id=str(request.run_id),
                    )
                    return
                effective_run_id = request.run_id

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
                    run_id=effective_run_id,
                    mission_id=mission_id,
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
                # HIGH #1 audit fix (KONSOLIDATSIYA v2): mission-darajali
                # qatorlarda `row.run_id` endi NULL (migratsiya 0012) —
                # in-memory shartnoma bo'yicha `ApprovalRequest.run_id`
                # mission uchun `mission.id`ni olib yuradi (`MissionEngine.
                # request_approval()` shunday yaratadi), shuning uchun
                # tiklashda ham aynan shu qiymat qaytariladi.
                #
                # DB CheckConstraint (`approval_has_run_or_mission`) ikkalasi
                # ham NULL bo'lishini man qiladi, lekin mypy buni bila
                # olmaydi — shuning uchun explicit if/elif bilan real
                # None-tekshiruv qilinadi (mypy narrowing) va qatorni
                # o'tkazib yuborish (fail-open) ehtimoliy buzuq ma'lumot
                # holatida ham xavfsiz.
                effective_run_id: uuid.UUID
                if row.mission_id is not None:
                    effective_run_id = row.mission_id
                elif row.run_id is not None:
                    effective_run_id = row.run_id
                else:
                    log.warning("approval.skipped_missing_run_and_mission", approval_id=str(row.id))
                    continue
                # ApprovalRequest'ni direct field'lar bilan qurish.
                # B1 audit fix: `step_position` endi haqiqiy qiymatdan
                # tiklanadi (migratsiya 0010'dan oldin yozilgan eski
                # qatorlarda ustun NULL bo'ladi — bu holatda None qoladi,
                # fail-open, xato ko'tarilmaydi).
                req = ApprovalRequest(
                    run_id=effective_run_id,
                    mission_id=row.mission_id,
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
                service._by_run.setdefault(effective_run_id, []).append(req.id)  # noqa: SLF001
                if row.mission_id is not None:
                    # `pending_for_mission()` ham restart'dan keyin
                    # ishlashi uchun — ilgari bu indeks umuman
                    # tiklanmagan edi (HIGH #1 bilan bir vaqtda topilgan
                    # kichik, tegishli gap).
                    service._by_mission.setdefault(row.mission_id, []).append(req.id)

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
    "load_completed_steps",
    "load_pending_approvals",
    "load_pending_runs",
    "load_run_by_id",
    "persist_approval",
    "persist_run",
    "persist_step_result",
]
