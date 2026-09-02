"""AgentRepository — agentlarni DB'da saqlash (Bo'lim 3-4, A-02).

Ilgari `AgentRegistry` faqat in-memory edi — Agent Factory orqali yaratilgan
har qanday agent protsess qayta ishga tushganda yo'qolardi (gap-analysis #1:
"db/models/agent.py`da real jadval bor, lekin hech qachon ishlatilmaydi").

Arxitektura: `AgentRegistry` (sync, in-memory) runtime uchun **yagona
manba** bo'lib qoladi — uni o'zgartirish katta xavf (factory/lifecycle/
runtime/daemon ko'p joyda unga tayanadi). `AgentRepository` esa **write-through**
qatlam: har bir `register()`/`update_status()`/`record_run()` chaqiruvidan
keyin natija shu orqali ham DB'ga yoziladi; ilova boshlanganda esa oldin
saqlangan (builtin bo'lmagan) agentlar DB'dan `AgentRegistry`ga qayta
yuklanadi (`load_all` + bootstrap).

Bog'liq qarorlar:
    A-02 — agent = ma'lumot
    V-10 — Agent Factory
    V-11 — lifecycle avtomati
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.agent import Agent as AgentRow
from zet.domain.agent import AgentSpec, AgentState
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, TrustLevel

log = structlog.get_logger(__name__)


def _state_to_row_fields(state: AgentState) -> dict[str, Any]:
    """`AgentState`ni DB ustunlariga o'giradi (ijodkor va yangilash uchun umumiy)."""
    spec = state.spec
    return {
        "name": spec.name,
        "description": spec.description,
        "division": spec.division,
        "role": spec.role,
        "goal": spec.goal,
        "system_prompt": spec.system_prompt,
        "tool_allowlist": list(spec.tool_allowlist),
        "model_policy": spec.model_policy,
        "permission_level": spec.permission_level,
        "trust_level": spec.trust_level,
        "status": state.status,
        "version": spec.version,
        "max_steps": spec.max_steps,
        "max_tool_calls": spec.max_tool_calls,
        "timeout_s": spec.timeout_s,
        "total_runs": state.total_runs,
        "successful_runs": state.successful_runs,
        "failed_runs": state.failed_runs,
        "total_tool_calls_count": state.total_tool_calls,
    }


def _row_to_state(row: AgentRow) -> AgentState:
    """DB qatorini `AgentState`ga o'giradi."""
    spec = AgentSpec(
        name=row.name,
        description=row.description,
        division=row.division,
        role=row.role,
        goal=row.goal,
        system_prompt=row.system_prompt,
        tool_allowlist=list(row.tool_allowlist or []),
        model_policy=ModelTier(row.model_policy),
        permission_level=PermissionLevel(row.permission_level),
        trust_level=TrustLevel(row.trust_level),
        max_steps=row.max_steps,
        max_tool_calls=row.max_tool_calls,
        timeout_s=row.timeout_s,
        version=row.version,
    )
    return AgentState(
        spec=spec,
        status=AgentStatus(row.status),
        id=str(row.id),
        created_at=row.created_at,
        updated_at=row.updated_at,
        total_runs=row.total_runs,
        successful_runs=row.successful_runs,
        failed_runs=row.failed_runs,
        total_tool_calls=row.total_tool_calls_count,
    )


class AgentRepository:
    """Agent holatini DB'da saqlash va o'qish — `AgentRegistry`ga qo'shimcha
    (uni almashtirmaydi)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, state: AgentState) -> None:
        """`AgentState`ni DB'ga yozadi — mavjud bo'lsa yangilaydi, bo'lmasa yaratadi."""
        result = await self._session.execute(
            select(AgentRow).where(AgentRow.name == state.spec.name)
        )
        row = result.scalar_one_or_none()
        fields = _state_to_row_fields(state)

        if row is None:
            row = AgentRow(**fields)
            self._session.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)

        await self._session.flush()
        log.info("agent.repository.saved", name=state.spec.name, status=state.status.value)

    async def load_all(self) -> list[AgentState]:
        """DB'dagi barcha agentlarni `AgentState` sifatida qaytaradi."""
        result = await self._session.execute(select(AgentRow))
        return [_row_to_state(row) for row in result.scalars().all()]

    async def get(self, name: str) -> AgentState | None:
        """Bitta agentni nom bo'yicha o'qish (mavjud bo'lmasa None)."""
        result = await self._session.execute(select(AgentRow).where(AgentRow.name == name))
        row = result.scalar_one_or_none()
        return _row_to_state(row) if row is not None else None


__all__ = ["AgentRepository"]
