"""AI Core holati endpoint'lari (gap-analysis #20).

POST /api/v1/state/sleep — proaktiv ishlarni pauza qilish
POST /api/v1/state/wake  — proaktiv ishlarni tiklash
GET  /api/v1/state       — joriy rejim
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from zet.api.deps import get_core_state
from zet.core.state import CoreState

router = APIRouter()


class SleepRequest(BaseModel):
    """Uxlash so'rovi."""

    reason: str = Field(default="Ega tomonidan", max_length=500)


@router.post("/state/sleep")
async def sleep(
    request: SleepRequest,
    state: CoreState = Depends(get_core_state),
) -> dict[str, object]:
    """SLEEPING rejimiga o'tish — kunlik jadval va boshqa proaktiv ishlar to'xtaydi."""
    state.sleep(reason=request.reason)
    return {"status": "sleeping", "state": state.to_dict()}


@router.post("/state/wake")
async def wake(
    request: SleepRequest,
    state: CoreState = Depends(get_core_state),
) -> dict[str, object]:
    """ACTIVE rejimiga qaytish."""
    state.wake(reason=request.reason)
    return {"status": "active", "state": state.to_dict()}


@router.get("/state")
async def get_state(
    state: CoreState = Depends(get_core_state),
) -> dict[str, object]:
    """Joriy rejim."""
    return {"state": state.to_dict()}
