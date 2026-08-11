"""Run endpoint (Z1.14).

POST /api/v1/run — yangi run boshlash.

Lean versiya: sinxron bajarish, SSE yo'q.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_killswitch
from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState

router = APIRouter()


class RunRequest(BaseModel):
    """Run boshlash so'rovi."""

    message: str = Field(..., min_length=1, max_length=10_000)
    dry_run: bool = False


class RunResponse(BaseModel):
    """Run javobi."""

    trace_id: str
    status: str
    message: str
    steps_done: int = 0
    cost_usd: float = 0.0


@router.post("/run", response_model=RunResponse)
async def create_run(
    request: RunRequest,
    ks: KillSwitchState = Depends(get_killswitch),
) -> RunResponse:
    """Yangi run boshlash.

    Bo'lim 1 lean versiya — faqat intent aniqlash.
    To'liq pipeline (intent→plan→execute→verify) keyingi bo'limlarda.
    """
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
        # Bo'lim 1: faqat xabarni qabul qilish va tasdiqlab qaytarish
        # To'liq pipeline Z1.14+ da qo'shiladi
        return RunResponse(
            trace_id=trace_id,
            status="accepted",
            message=f"Qabul qilindi: {request.message[:100]}",
            steps_done=0,
            cost_usd=0.0,
        )
    finally:
        unbind_trace()
