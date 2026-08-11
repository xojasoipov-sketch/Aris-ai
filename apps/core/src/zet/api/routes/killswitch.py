"""KillSwitch endpoint'lari (Z1.14).

POST /api/v1/killswitch/engage    — emergency stop yoqish
POST /api/v1/killswitch/disengage — emergency stop o'chirish
GET  /api/v1/killswitch           — holat
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_killswitch
from zet.security.killswitch import KillSwitchState

router = APIRouter()


class EngageRequest(BaseModel):
    """Emergency stop yoqish so'rovi."""

    reason: str = Field(default="Manual engage", max_length=500)


@router.post("/killswitch/engage")
async def engage_killswitch(
    request: EngageRequest,
    ks: KillSwitchState = Depends(get_killswitch),
) -> dict[str, object]:
    """Emergency stop yoqish."""
    ks.engage(reason=request.reason)
    return {"status": "engaged", "killswitch": ks.to_dict()}


@router.post("/killswitch/disengage")
async def disengage_killswitch(
    ks: KillSwitchState = Depends(get_killswitch),
) -> dict[str, object]:
    """Emergency stop o'chirish."""
    try:
        ks.disengage()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    return {"status": "disengaged", "killswitch": ks.to_dict()}


@router.get("/killswitch")
async def killswitch_status(
    ks: KillSwitchState = Depends(get_killswitch),
) -> dict[str, object]:
    """KillSwitch holati."""
    return {"killswitch": ks.to_dict()}
