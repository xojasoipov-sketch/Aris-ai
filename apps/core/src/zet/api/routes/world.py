"""World State endpoint — ZET hozir nimani KO'RAYOTGANINI ko'rsatadi (JB-3).

    GET /api/v1/world — muhitning joriy kesimi

NEGA kerak: `WorldState` reja va javob promptlariga qo'shiladi, ya'ni
javob sifatiga to'g'ridan-to'g'ri ta'sir qiladi. Uni tashqaridan
ko'rib bo'lmasa, "ZET nega bu vazifani bilmadi?" degan savolga javob
topish mumkin emas edi. Bu endpoint aynan modelga ketayotgan
ma'lumotni qaytaradi — jumladan `unavailable` ro'yxatini (qaysi manba
o'qilmagani).

Bog'liq qarorlar:
    JB-3 — World State (JARVIS Brain auditi §11)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.deps import (
    get_agent_registry,
    get_approval_service,
    get_config,
    get_core_state,
    get_db_session,
    get_killswitch,
)
from zet.config import Settings
from zet.core.world_state import WorldState, WorldStateBuilder
from zet.db.bootstrap import get_or_create_owner

router = APIRouter(prefix="/world", tags=["world"])


class WorldStateResponse(WorldState):
    """`WorldState` + LLM'ga ketadigan matn bloki.

    Model maydonlari o'zgarmasdan qaytadi (frontend ular bilan
    ishlaydi), `prompt_block` esa AYNAN promptga qo'shiladigan matn —
    nosozlik qidirishda eng foydali qism.
    """

    prompt_block: str = ""


@router.get("", response_model=WorldStateResponse)
async def get_world(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> WorldStateResponse:
    """Muhitning joriy holati — reja tuzishda ishlatiladigan ma'lumot."""
    from zet.core.mission_repository import MissionRepository
    from zet.llm.budget import BudgetGuard
    from zet.workspace.repository import WorkspaceRepository

    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    builder = WorldStateBuilder(
        core_state=get_core_state(),
        killswitch=get_killswitch(),
        agent_registry=get_agent_registry(),
        approvals=get_approval_service(),
        workspace=WorkspaceRepository(session, owner_id=owner.id),
        mission_repo=MissionRepository(session, owner_id=owner.id),
        budget_snapshot=BudgetGuard(session, settings).snapshot,
    )
    state = await builder.build()
    return WorldStateResponse(**state.model_dump(), prompt_block=state.to_prompt_block())
