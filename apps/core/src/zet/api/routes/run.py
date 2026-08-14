"""Run endpoint (Z1.14+).

POST /api/v1/run — yangi run boshlash: intent → reja → bajarish → tekshirish.
GET  /api/v1/run/{run_id} — run holatini olish.
GET  /api/v1/runs — run TARIXI, bazadan (sahifalangan, faqat egaga tegishli).

To'liq pipeline: `Orchestrator` orqali `IntentRecognizer` → `Planner` →
`Executor` (approval gate bilan) → `Verifier`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.deps import (
    get_config,
    get_db_session,
    get_killswitch,
    get_orchestrator,
    load_conversation_history,
    save_conversation_turn,
)
from zet.config import Settings
from zet.core.orchestrator import Orchestrator, RunNotFoundError, RunRecord
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.run import Run as RunRow
from zet.domain.command import Command
from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState

router = APIRouter()


class RunRequest(BaseModel):
    """Run boshlash so'rovi."""

    message: str = Field(..., min_length=1, max_length=10_000)
    dry_run: bool = False
    channel: str = Field(default="web", max_length=32)
    """Suhbat kanali — tarix shu bo'yicha ajratiladi (web/api/tg)."""


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


class RunHistoryResponse(BaseModel):
    """Run tarixi ro'yxatidagi bitta yozuv — `GET /api/v1/runs`.

    `RunResponse`dan farqi: bu bevosita `run` jadval qatoridan (bazadan)
    quriladi, faol `Orchestrator.run_store` (xotira) orqali emas —
    shuning uchun protsess qayta ishga tushgan/eski run'lar uchun ham
    ishlaydi.
    """

    run_id: str
    status: str
    command_text: str
    result_summary: str | None
    error: str | None
    created_at: str
    finished_at: str | None
    steps_done: int
    steps_total: int
    cost_usd: float
    tools_used: list[str]


def _run_history_response(row: RunRow) -> RunHistoryResponse:
    """`Run` DB qatorini `RunHistoryResponse`ga aylantiradi.

    `completed_steps`/`plan_snapshot` — ikkalasi ham `None` bo'lishi
    mumkin (run hali rejalashtirilmagan yoki checkpoint yozilmagan) —
    bunday holatda 0/steps_done bilan mos qiymat qaytadi, hech qanday
    o'ylab topilgan raqam yo'q.
    """
    completed: dict[str, Any] = row.completed_steps or {}
    steps_done = len(completed)

    steps_total = steps_done
    if row.plan_snapshot:
        plan_steps = row.plan_snapshot.get("steps")
        if isinstance(plan_steps, list):
            steps_total = len(plan_steps)

    # Position bo'yicha tartib — JSON kalitlari string, shuning uchun
    # int'ga o'girib saralanadi. Buzuq/raqam bo'lmagan kalitlar
    # o'tkazib yuboriladi (fail-open, `run_checkpoint.py` naqshi).
    ordered_positions: list[tuple[int, str]] = []
    for pos_str in completed:
        try:
            ordered_positions.append((int(pos_str), pos_str))
        except (TypeError, ValueError):
            continue
    ordered_positions.sort()

    tools_used: list[str] = []
    seen: set[str] = set()
    for _, pos_str in ordered_positions:
        step_data = completed.get(pos_str)
        if not isinstance(step_data, dict):
            continue
        tool_result = step_data.get("tool_result")
        if not isinstance(tool_result, dict):
            continue
        tool_name = tool_result.get("tool_name")
        if tool_name and tool_name not in seen:
            seen.add(tool_name)
            tools_used.append(tool_name)

    return RunHistoryResponse(
        run_id=str(row.id),
        status=row.status.value,
        command_text=row.command_text,
        result_summary=row.result_summary,
        error=row.error,
        created_at=row.created_at.isoformat(),
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        steps_done=steps_done,
        steps_total=steps_total,
        cost_usd=round(row.spent_usd, 6),
        tools_used=tools_used,
    )


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
    """Yangi run boshlash — to'liq pipeline, suhbat tarixi bilan.

    TARIX NEGA SHU YERDA. Ilgari bu route tarixsiz `Command` yaratardi
    va javobni hech qayerga yozmasdi — ya'ni brauzerdagi ZET oldingi
    gapni umuman eslamasdi ("Tushuntir" kabi ergash buyruq kontekstsiz
    qolardi). Telegram oqimida esa tarix allaqachon saqlanardi. Bir xil
    yadro, ikki xil xotira — shu farq yopildi.
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
        history = await load_conversation_history(request.channel)
        command = Command(text=request.message, channel=request.channel, history=history)
        try:
            record = await orchestrator.start(command, dry_run=request.dry_run)
        except KillSwitchEngagedError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Emergency stop yoqilgan: {exc}",
            ) from exc

        response = _to_response(record, trace_id)
        # Quruq ishga tushirish (`dry_run`) tarixga yozilmaydi — u
        # sinov, haqiqiy suhbat emas.
        if not request.dry_run:
            await save_conversation_turn(
                request.channel, user_text=request.message, reply=response.message
            )
        return response
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


@router.get("/runs", response_model=list[RunHistoryResponse])
async def list_run_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> list[RunHistoryResponse]:
    """Run tarixi — bazadan, faqat egaga tegishli, eng yangi birinchi.

    `GET /run/{run_id}` dan farqi: bu doim DB'dan o'qiydi (xotiradagi
    `Orchestrator.run_store`ga bog'liq emas) — shuning uchun protsess
    qayta ishga tushgandan keyingi run'lar ham ko'rinadi.
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    rows = (
        (
            await session.execute(
                select(RunRow)
                .where(RunRow.owner_id == owner.id)
                .order_by(RunRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_run_history_response(row) for row in rows]
