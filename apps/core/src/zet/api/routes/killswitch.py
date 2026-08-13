"""KillSwitch endpoint'lari (Z1.14).

POST /api/v1/killswitch/engage    — emergency stop yoqish
POST /api/v1/killswitch/disengage — emergency stop o'chirish
GET  /api/v1/killswitch           — holat
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_killswitch, get_session_factory
from zet.security.audit_writer import write_audit
from zet.security.killswitch import KillSwitchState
from zet.security.killswitch_actions import revoke_all_capability_tokens_on_killswitch
from zet.security.killswitch_store import persist_killswitch

router = APIRouter()


class EngageRequest(BaseModel):
    """Emergency stop yoqish so'rovi."""

    reason: str = Field(default="Manual engage", max_length=500)


@router.post("/killswitch/engage")
async def engage_killswitch(
    request: EngageRequest,
    ks: KillSwitchState = Depends(get_killswitch),
) -> dict[str, object]:
    """Emergency stop yoqish.

    SR-06: yoqilish bilan ega barcha capability tokenlari bekor
    qilinadi — iPhone/Mac/Kamera clientlari validatsiyada 403 oladi.
    Disengage bu tokenlarni QAYTA TIKLAMAYDI (ega qurilmani qo'lda
    qayta ro'yxatga olishi kerak) — bu ataylab, "favqulodda stop"
    ma'nosi shu."""
    ks.engage(reason=request.reason)
    # DB'ga yozib qo'yamiz — restart'da holat yo'qolmasin (V-33, BROKEN #3)
    await persist_killswitch(ks, get_session_factory())
    # SR-06: barcha faol capability tokenlarni bekor qilamiz. Fail-open:
    # DB xatosida ham killswitch bayrog'i yoqilgan holicha qoladi (`check()`
    # yangi run'larni bloklashda davom etadi).
    revoked_count = await revoke_all_capability_tokens_on_killswitch(get_session_factory())
    await write_audit(
        get_session_factory(),
        actor="owner",
        action="killswitch.engaged",
        detail={"reason": request.reason, "revoked_token_count": revoked_count},
    )
    return {
        "status": "engaged",
        "killswitch": ks.to_dict(),
        "revoked_token_count": revoked_count,
    }


@router.post("/killswitch/disengage")
async def disengage_killswitch(
    ks: KillSwitchState = Depends(get_killswitch),
) -> dict[str, object]:
    """Emergency stop o'chirish.

    DIQQAT: bekor qilingan capability tokenlar QAYTA TIKLANMAYDI
    (SR-06 qarori) — ega har qurilmani qo'lda `POST /devices` orqali
    qayta ro'yxatga olishi kerak. Bu ataylab: emergency stop davomida
    tokenlar kompromatlangan deb hisoblanadi."""
    try:
        ks.disengage()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    await persist_killswitch(ks, get_session_factory())
    await write_audit(
        get_session_factory(),
        actor="owner",
        action="killswitch.disengaged",
    )
    return {"status": "disengaged", "killswitch": ks.to_dict()}


@router.get("/killswitch")
async def killswitch_status(
    ks: KillSwitchState = Depends(get_killswitch),
) -> dict[str, object]:
    """KillSwitch holati."""
    return {"killswitch": ks.to_dict()}
