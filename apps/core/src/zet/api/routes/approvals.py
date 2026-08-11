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

from zet.api.deps import get_approval_service, get_orchestrator
from zet.core.orchestrator import Orchestrator, RunNotFoundError
from zet.security.approvals import (
    ApprovalError,
    ApprovalExpiredError,
    ApprovalRequest,
    ApprovalService,
)

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
    """Run uchun kutilayotgan tasdiqlar ro'yxati."""
    if run_id is None:
        raise HTTPException(status_code=400, detail="run_id majburiy")
    rid = _parse_uuid(run_id, "run_id")
    return [_to_response(r) for r in approvals.pending_for_run(rid)]


@router.post("/{approval_id}/approve", response_model=ApprovalDecisionResponse)
async def approve(
    approval_id: str,
    body: ApprovalDecisionRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ApprovalDecisionResponse:
    """Tasdiqni qabul qilib, run bajarilishini davom ettiradi."""
    aid = _parse_uuid(approval_id, "approval_id")
    try:
        record = orchestrator.approve(aid, note=body.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tasdiq topilmadi") from exc
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApprovalExpiredError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record = await orchestrator.resume(record.run_id)

    approval = orchestrator.approvals.get(aid)
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
    """Tasdiqni rad etib, run'ni bekor qiladi."""
    aid = _parse_uuid(approval_id, "approval_id")
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
    return ApprovalDecisionResponse(
        approval=_to_response(approval),
        run_id=str(record.run_id),
        run_status=record.status.value,
    )
