"""Approval endpoint'lari (Z1.14+, V-32).

GET  /api/v1/approvals?run_id=...           — run uchun kutilayotgan tasdiqlar
POST /api/v1/approvals/{approval_id}/approve — tasdiqlash va davom ettirish
POST /api/v1/approvals/{approval_id}/reject  — rad etish va run'ni bekor qilish

Ilgari `ApprovalService` to'liq ishlab chiqilgan, lekin hech qanday production
yo'lida chaqirilmagan edi (faqat o'z testlarida). Endi `Orchestrator` orqali
haqiqiy `/api/v1/run` bilan bog'langan.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from zet.api.deps import (
    get_approval_service,
    get_killswitch,
    get_orchestrator,
    get_session_factory,
)
from zet.core.orchestrator import Orchestrator, RunNotFoundError
from zet.db.session import session_scope
from zet.security.approvals import (
    ApprovalError,
    ApprovalExpiredError,
    ApprovalRequest,
    ApprovalService,
)
from zet.security.audit_writer import write_audit

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalResponse(BaseModel):
    """Tasdiq so'rovi javobi."""

    id: str
    run_id: str
    status: str
    reason: str
    tool_name: str | None
    requested_permission: str
    created_at: str
    expires_at: str


class ApprovalDecisionRequest(BaseModel):
    """Tasdiq/rad etish so'rovi."""

    note: str | None = None


class ApprovalDecisionResponse(BaseModel):
    """Tasdiq qarori javobi — run holati bilan birga."""

    approval: ApprovalResponse
    run_id: str
    run_status: str


def _to_response(req: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(
        id=str(req.id),
        run_id=str(req.run_id),
        status=req.status.value,
        reason=req.reason,
        tool_name=req.tool_name,
        requested_permission=req.requested_permission.value,
        created_at=req.created_at.isoformat(),
        expires_at=req.expires_at.isoformat(),
    )


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Noto'g'ri {field}") from exc


@router.get("", response_model=list[ApprovalResponse])
async def list_pending(
    run_id: str | None = None,
    approvals: ApprovalService = Depends(get_approval_service),
) -> list[ApprovalResponse]:
    """Kutilayotgan tasdiqlar ro'yxati.

    `run_id` berilsa — faqat shu run'ga tegishlilari; berilmasa — HAMMA
    kutayotgan tasdiqlar (`z approvals` CLI ishlatadi, GAP_ANALYSIS
    BROKEN #1 tuzatilishida kerak bo'ldi).
    """
    if run_id is None:
        return [_to_response(r) for r in approvals.all_pending()]
    rid = _parse_uuid(run_id, "run_id")
    return [_to_response(r) for r in approvals.pending_for_run(rid)]


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionResponse)
async def approve(
    approval_id: str,
    body: ApprovalDecisionRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ApprovalDecisionResponse:
    """Tasdiqni qabul qilib, run yoki mission bajarilishini davom ettiradi.

    NEGA MISSION FALLBACK. Adversarial verify topgan bug (HIGH):
    Mission-level approval'lar `approvals.request_approval(run_id=mission.id)`
    orqali yoziladi (mission darajasida haqiqiy Run yo'q). Orchestrator.approve()
    esa RunStore'dan run qidiradi va RunNotFoundError otadi — mission bricked
    bo'lardi. Endi: agar approval `mission_id` bilan yozilgan bo'lsa (yoki
    Orchestrator uni topa olmasa), MissionEngine.approve() ga o'tamiz.
    """
    aid = _parse_uuid(approval_id, "approval_id")

    # Avval approval'ni ko'zdan kechiramiz — mission-level bo'lsa alohida yo'l.
    try:
        pending = orchestrator.approvals.get(aid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tasdiq topilmadi") from exc

    if pending.mission_id is not None:
        # Mission-level approval — MissionEngine orqali (mustaqil sessiya
        # ochamiz, chunki approve endpoint faqat Orchestrator'ga bog'langan).
        from zet.api.deps import build_mission_engine_for_session

        try:
            async with session_scope(get_session_factory()) as session:
                mission_engine = await build_mission_engine_for_session(
                    session,
                    orchestrator,
                    orchestrator.approvals,
                    # JB-12: approve orqali resume qilingan mission ham
                    # killswitch'ni hurmat qilsin.
                    killswitch=get_killswitch(),
                )
                mission = await mission_engine.approve(pending.mission_id, aid)
                mission = await mission_engine.run_to_completion(mission.id)
        except ApprovalExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        await write_audit(
            get_session_factory(),
            actor="owner",
            action="approval.granted",
            target=pending.tool_name,
            permission_level=pending.requested_permission,
            run_id=pending.run_id,  # backward compat (mission_id sifatida qayd)
            detail={
                "reason": pending.reason,
                "note": body.note,
                "mission_id": str(pending.mission_id),
                "mission_status": mission.status.value,
            },
        )
        return ApprovalDecisionResponse(
            approval=_to_response(orchestrator.approvals.get(aid)),
            run_id=str(pending.mission_id),  # UI mission ID ni ko'radi
            run_status=mission.status.value,
        )

    # Klassik run-level approval.
    try:
        record = orchestrator.approve(aid, note=body.note)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record = await orchestrator.resume(record.run_id)

    approval = orchestrator.approvals.get(aid)
    await write_audit(
        get_session_factory(),
        actor="owner",
        action="approval.granted",
        target=approval.tool_name,
        permission_level=approval.requested_permission,
        run_id=record.run_id,
        detail={"reason": approval.reason, "note": body.note},
    )
    return ApprovalDecisionResponse(
        approval=_to_response(approval),
        run_id=str(record.run_id),
        run_status=record.status.value,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalDecisionResponse)
async def reject(
    approval_id: str,
    body: ApprovalDecisionRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ApprovalDecisionResponse:
    """Tasdiqni rad etib, run yoki mission'ni bekor qiladi.

    JB-12 (audit topilmasi — `approve()`dagi bilan AYNAN bir xil sinfdagi
    bug): mission-level approval'lar `run_id=mission.id` bilan yoziladi
    (haqiqiy Run yo'q). Ilgari bu yerda HECH QANDAY tarmoqlanish yo'q edi
    — `orchestrator.reject()` doim `RunStore.get(approval.run_id)`ni
    chaqirardi, mission.id esa RunStore'da HECH QACHON topilmaydi —
    `RunNotFoundError` → 404, garchi tasdiq haqiqatda mavjud bo'lsa ham.
    Endi `approve()` bilan bir xil naqsh: mission-level bo'lsa
    `MissionEngine.cancel()` (mavjud, boshqa maqsad uchun yozilgan —
    "har qanday non-terminal holatdan CANCELLED" — bu yerga ayni mos).
    """
    aid = _parse_uuid(approval_id, "approval_id")

    try:
        pending = orchestrator.approvals.get(aid)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tasdiq topilmadi") from exc

    if pending.mission_id is not None:
        from zet.api.deps import build_mission_engine_for_session

        try:
            async with session_scope(get_session_factory()) as session:
                mission_engine = await build_mission_engine_for_session(
                    session,
                    orchestrator,
                    orchestrator.approvals,
                    killswitch=get_killswitch(),
                )
                # `reject()` ApprovalRequest'ni REJECTED qiladi — audit-
                # trail uchun `approve()`dan ustuvor (avval shu, keyin
                # mission'ni CANCELLED qilamiz).
                orchestrator.approvals.reject(aid, note=body.note)
                mission = await mission_engine.cancel(
                    pending.mission_id, body.note or "Ega tomonidan rad etildi"
                )
        except ApprovalExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except ApprovalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        await write_audit(
            get_session_factory(),
            actor="owner",
            action="approval.rejected",
            target=pending.tool_name,
            permission_level=pending.requested_permission,
            run_id=pending.run_id,
            detail={
                "reason": pending.reason,
                "note": body.note,
                "mission_id": str(pending.mission_id),
                "mission_status": mission.status.value,
            },
        )
        return ApprovalDecisionResponse(
            approval=_to_response(orchestrator.approvals.get(aid)),
            run_id=str(pending.mission_id),
            run_status=mission.status.value,
        )

    # Klassik run-level rad etish.
    try:
        record = orchestrator.reject(aid, note=body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tasdiq topilmadi") from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    approval = orchestrator.approvals.get(aid)
    await write_audit(
        get_session_factory(),
        actor="owner",
        action="approval.rejected",
        target=approval.tool_name,
        permission_level=approval.requested_permission,
        run_id=record.run_id,
        detail={"reason": approval.reason, "note": body.note},
    )
    return ApprovalDecisionResponse(
        approval=_to_response(approval),
        run_id=str(record.run_id),
        run_status=record.status.value,
    )
