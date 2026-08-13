"""Mission API — POST /missions, GET /missions/{id}, GET /missions.

MissionOrchestrator orqali `Command` qabul qilinadi, yakuniy `Mission`
qaytariladi. Ilgari faqat past darajali `POST /run` (bitta Run) bor
edi — Mission qatlami hech bir tashqi yo'lga chiqmasdi. Endi:

    POST /api/v1/missions        — yangi mission (objective) yaratish
    GET  /api/v1/missions/{id}   — bitta mission holati
    GET  /api/v1/missions        — yaqindagi missionlar ro'yxati

Bog'liq qarorlar:
    A-01 — mission holat mashinasi
    V-32 — HIGH_RISK → WAITING_APPROVAL
    V-33 — killswitch preflight (CANCELLED)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from zet.api.deps import get_mission_orchestrator
from zet.core.mission import Mission, MissionNotFoundError
from zet.core.mission_orchestrator import MissionOrchestrator
from zet.domain.command import Command
from zet.domain.enums import MissionStatus, TrustLevel

router = APIRouter(prefix="/missions", tags=["missions"])


# ── Javob modellari ──────────────────────────────────────────────


class MissionResponse(BaseModel):
    """Mission javobi — HTTP yuzasidagi holat."""

    id: str
    owner_id: str
    objective: str
    status: MissionStatus
    risk_level: str
    tasks: list[dict[str, Any]]
    tools: list[str]
    capabilities: list[str]
    context: dict[str, Any]
    run_ids: list[str]
    pending_approval_id: str | None
    retry_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class MissionListResponse(BaseModel):
    """Missionlar ro'yxati javobi — sahifa metama'lumoti bilan."""

    items: list[MissionResponse]
    limit: int
    offset: int
    count: int


class CreateMissionRequest(BaseModel):
    """Yangi mission so'rovi."""

    objective: str = Field(min_length=1, max_length=4096)
    channel: str = Field(default="api", max_length=32)


def _to_response(m: Mission) -> MissionResponse:
    return MissionResponse(
        id=str(m.id),
        owner_id=str(m.owner_id),
        objective=m.objective,
        status=m.status,
        risk_level=m.risk_level.value,
        tasks=[t if isinstance(t, dict) else t.model_dump(mode="json") for t in m.tasks],
        tools=list(m.tools),
        capabilities=list(m.capabilities),
        context=dict(m.context),
        run_ids=[str(r) for r in m.run_ids],
        pending_approval_id=(str(m.pending_approval_id) if m.pending_approval_id else None),
        retry_count=m.retry_count,
        error=m.error,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


# ── Endpoint'lar ─────────────────────────────────────────────────


@router.post("", response_model=MissionResponse)
async def create_mission(
    request: CreateMissionRequest,
    orchestrator: MissionOrchestrator = Depends(get_mission_orchestrator),
) -> MissionResponse:
    """Yangi mission yaratadi va oxirigacha aylantiradi.

    NEGA sinxron (async wait) va SSE emas: Bo'lim 5 lean; API oddiy
    REST — ega natijani kutadi va oxirgi holatni oladi. WAITING_APPROVAL
    holatida qaytish ham normal (natija emas — kutmoqda).
    """
    command = Command(
        text=request.objective,
        trust_level=TrustLevel.OWNER,
        channel=request.channel,
    )
    # owner_id — MissionOrchestrator ichida repository allaqachon
    # owner-scoped; submit() alohida `owner_id` argumentini talab
    # qiladi (Mission modeliga yoziladi).
    mission = await orchestrator.run(command, owner_id=orchestrator.owner_id)
    return _to_response(mission)


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    orchestrator: MissionOrchestrator = Depends(get_mission_orchestrator),
) -> MissionResponse:
    """Bitta mission holati — id bo'yicha."""
    try:
        mid = uuid.UUID(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Noto'g'ri mission_id") from exc
    try:
        mission = await orchestrator.get(mid)
    except MissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(mission)


@router.get("", response_model=MissionListResponse)
async def list_missions(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: MissionStatus | None = Query(default=None),
    orchestrator: MissionOrchestrator = Depends(get_mission_orchestrator),
) -> MissionListResponse:
    """Yaqindagi missionlar — priority DESC → created_at DESC, sahifalash."""
    rows = await orchestrator.list_recent(limit=limit, offset=offset, status=status)
    items = [_to_response(m) for m in rows]
    return MissionListResponse(items=items, limit=limit, offset=offset, count=len(items))
