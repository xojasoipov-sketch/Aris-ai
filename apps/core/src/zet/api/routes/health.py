"""Health check endpoint (Z1.14).

GET /api/v1/health — oddiy health check.
GET /api/v1/status — tizim holati (killswitch, config).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from zet.api.deps import get_config, get_killswitch
from zet.config import Settings
from zet.security.killswitch import KillSwitchState

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check — har doim 200."""
    return {"status": "ok"}


@router.get("/status")
async def system_status(
    ks: KillSwitchState = Depends(get_killswitch),
    config: Settings = Depends(get_config),
) -> dict[str, object]:
    """Tizim holati — killswitch, budjet, muhit."""
    return {
        "status": "ok" if not ks.is_engaged else "killswitch_engaged",
        "killswitch": ks.to_dict(),
        "env": config.env.value,
        "budget": {
            "daily_usd": config.budget_daily_usd,
            "monthly_usd": config.budget_monthly_usd,
            "run_max_usd": config.run_max_usd,
        },
    }
