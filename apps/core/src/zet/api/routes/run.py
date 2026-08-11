"""Run endpoint (Z1.14+).

POST /api/v1/run — yangi run boshlash: intent → reja → bajarish → tekshirish.
GET  /api/v1/run/{run_id} — run holatini olish.

To'liq pipeline: `Orchestrator` orqali `IntentRecognizer` → `Planner` →
`Executor` (approval gate bilan) → `Verifier`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_killswitch, get_orchestrator
from zet.core.orchestrator import Orchestrator, RunNotFoundError, RunRecord
from zet.domain.command import Command
from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState

router = APIRouter()


class RunRequest(BaseModel):
    """Run boshlash so'rovi."""

    message: str = Field(..., min_length=1, max_length=10_000)
    dry_run: bool = False


class RunResponse(BaseModel):
    """Run javobi."""

    run_id: str
    trace_id: str
    status: str
    message: str
    steps_done: int = 0
    steps_total: int = 0
    cost_usd: float = 0.0
    pending_approval_id: str | None = None


def _to_response(record: RunRecord, trace_id: str) -> RunResponse:
    message = record.result_summary or record.error or record.command.text
    return RunResponse(
        run_id=str(record.run_id),
        trace_id=trace_id,
        status=record.status.value,
        message=message,
        steps_done=record.steps_done,
        steps_total=record.steps_total,
        cost_usd=round(record.spent_usd, 6),
        pending_approval_id=(
            str(record.pending_approval_id) if record.pending_approval_id else None
        ),
    )


@router.post("/run", response_model=RunResponse)
async def create_run(
    request: RunRequest,
    ks: KillSwitchState = Depends(get_killswitch),
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> RunResponse:
    """Yangi run boshlash — to'liq pipeline."""
    try:
        ks.check()
    except KillSwitchEngagedError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Emergency stop yoqilgan: {exc}",
        ) from exc

    from zet.observability.trace import bind_trace, unbind_trace

    trace_id = bind_trace()
    try:
        command = Command(text=request.message, channel="api")
        try:
            record = await orchestrator.start(command, dry_run=request.dry_run)
        except KillSwitchEngagedError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Emergency stop yoqilgan: {exc}",
            ) from exc
        return _to_response(record, trace_id)
    finally:
        unbind_trace()


@router.get("/run/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> RunResponse:
    """Run holatini olish."""
    try:
        rid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Noto'g'ri run_id") from exc
    try:
        record = orchestrator.run_store.get(rid)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(record, run_id)
