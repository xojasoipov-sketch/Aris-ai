"""MissionRepository — Mission CRUD va Run bog'lanishlari (Bo'lim 2, §2.2).

NEGA alohida modul, `workspace/repository.py` ichida emas: Mission
strategiya qatlami, Workspace esa foydalanuvchi ko'radigan sathi
(loyihalar/vazifalar/kalendar). Ularni bir modulga jipslash import
zanjirlarini murakkablashtirardi.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi (Mission ham davomli holat mashinasi)
    V-14 — owner-scoped so'rovlar
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.core.mission import (
    IllegalMissionTransitionError,
    Mission,
    MissionNotFoundError,
)
from zet.db.base import utcnow
from zet.db.models.mission import Mission as MissionORM
from zet.db.models.mission import MissionRunLink
from zet.domain.enums import MissionStatus


def _fresh(stmt: Select[Any]) -> Select[Any]:
    """`populate_existing` — WorkspaceRepository._fresh bilan bir xil naqsh.

    Sessiyada allaqachon yuklangan ORM obyekt bazadagi joriy qiymatga
    aynan yangilanadi. `expire_all()` async kontekstda `MissingGreenlet`
    otadi, shuning uchun bu yagona to'g'ri variant.
    """
    return stmt.execution_options(populate_existing=True)


class MissionRepository:
    """Mission jadvali bilan ishlaydi (owner-scoped).

    Har bir method `owner_id` bo'yicha cheklaydi: ega bittaligiga
    qaramay, noto'g'ri so'rovda begona missionni qaytarib yubormaslik
    uchun (WorkspaceRepository bilan bir xil chegara).
    """

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    @property
    def owner_id(self) -> uuid.UUID:
        """Repository qaysi ega ostida ishlayotgani (owner-scoped so'rovlar)."""
        return self._owner_id

    # ── CRUD ─────────────────────────────────────────────────────

    async def create(self, mission: Mission) -> Mission:
        """Yangi Mission yaratadi (INSERT)."""
        row = MissionORM(
            id=mission.id,
            owner_id=self._owner_id,
            objective=mission.objective,
            outcome_criteria=mission.outcome_criteria,
            context=mission.context,
            constraints=list(mission.constraints),
            tasks=[t.model_dump(mode="json") for t in mission.tasks],
            agents=list(mission.agents),
            tools=list(mission.tools),
            capabilities=list(mission.capabilities),
            permissions_required=[p.value for p in mission.permissions_required],
            risk_level=mission.risk_level,
            approval_requirements=list(mission.approval_requirements),
            deadline=mission.deadline,
            verification_rules=list(mission.verification_rules),
            memory_updates=list(mission.memory_updates),
            status=mission.status,
            priority=mission.priority,
            pending_approval_id=mission.pending_approval_id,
            retry_count=mission.retry_count,
            error=mission.error,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return await self._to_domain(row)

    async def get(self, mission_id: uuid.UUID) -> Mission:
        """Owner-scoped SELECT — topilmasa `MissionNotFoundError`."""
        row = await self._get_row(mission_id)
        if row is None:
            raise MissionNotFoundError(f"Mission topilmadi: {mission_id}")
        return await self._to_domain(row)

    async def list(
        self,
        *,
        status: MissionStatus | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> Sequence[Mission]:
        """Priority DESC → created_at DESC tartibida."""
        stmt = select(MissionORM).where(MissionORM.owner_id == self._owner_id)
        if status is not None:
            stmt = stmt.where(MissionORM.status == status)
        if active_only:
            stmt = stmt.where(
                MissionORM.status.notin_(
                    [MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED]
                )
            )
        stmt = stmt.order_by(MissionORM.priority.desc(), MissionORM.created_at.desc()).limit(limit)
        rows = (await self._session.execute(_fresh(stmt))).scalars().all()
        return [await self._to_domain(r) for r in rows]

    # Sentinel: `None`ni maxsus 'tozalash' signali sifatida farqlash uchun.
    # Adversarial verify topgan bug: `update(...pending_approval_id=None)` yoki
    # `set_status(...error=None)` maydonlarni TOZALAY OLMASDI — chunki None
    # 'don''t change' deb talqin qilinardi. `CLEAR` sentinel bilan `None`
    # aniq 'tozalash' bo'ladi; qolgan `None`'lar (agent partial update
    # yuborsa) o'zgarishsiz qoladi.
    _CLEAR = object()

    async def update(self, mission_id: uuid.UUID, **fields: object) -> Mission:
        """Maydonlarni yozadi. `None` = "o'zgartirma"; `Repo.CLEAR` = "tozalash".

        Backward compat: eski chaqiruvchilar `None`ni "o'zgartirma" deb
        ishlatishardi — bu saqlanadi. Bugun mission tozalashi kerak
        bo'lgan maydonlar uchun `MissionRepository.CLEAR` ishlatiladi
        (`pending_approval_id`ni approve/reject'dan keyin tozalash).
        """
        row = await self._get_row(mission_id)
        if row is None:
            raise MissionNotFoundError(f"Mission topilmadi: {mission_id}")
        for key, value in fields.items():
            if value is self.CLEAR:
                setattr(row, key, None)
            elif value is not None:
                setattr(row, key, value)
        row.updated_at = utcnow()
        await self._session.flush()
        return await self._to_domain(row)

    # Public sentinel — chaqiruvchilar `MissionRepository.CLEAR`ni ishlatadi.
    CLEAR = _CLEAR

    async def set_status(
        self,
        mission_id: uuid.UUID,
        new_status: MissionStatus,
        *,
        error: str | None = None,
        clear_error: bool = False,
        force: bool = False,
    ) -> Mission:
        """Holat mashinasini majburiy tekshiradi (`MISSION_TRANSITIONS`).

        `error=None` bilan `clear_error=True` yuborilsa, xato tozalanadi
        (recovery muvaffaqiyatli tugaganda kerak). `error=None` bilan
        `clear_error=False` (default) — xato o'zgarmaydi (backward compat).

        `force=True` — favqulodda hollar (cancel). Boshqa hollarda
        `IllegalMissionTransitionError` otiladi va yozuv o'zgarmaydi.
        """
        row = await self._get_row(mission_id)
        if row is None:
            raise MissionNotFoundError(f"Mission topilmadi: {mission_id}")
        if not force and not row.status.can_transition_to(new_status):
            raise IllegalMissionTransitionError(
                f"Mission {row.status.value} → {new_status.value} taqiqlangan"
            )
        row.status = new_status
        if error is not None:
            row.error = error
        elif clear_error:
            row.error = None
        row.updated_at = utcnow()
        await self._session.flush()
        return await self._to_domain(row)

    async def delete(self, mission_id: uuid.UUID) -> None:
        """CASCADE — `mission_run` yozuvlari ham o'chadi. Run'lar qoladi."""
        row = await self._get_row(mission_id)
        if row is None:
            raise MissionNotFoundError(f"Mission topilmadi: {mission_id}")
        await self._session.delete(row)
        await self._session.flush()

    # ── Runlar bilan bog'lanish ──────────────────────────────────

    async def attach_run(
        self, mission_id: uuid.UUID, run_id: uuid.UUID, *, attempt: int = 1
    ) -> None:
        """Yangi `MissionRunLink` yozuvi (mission ega bo'lmasa xato)."""
        # Owner tekshiruvi — begona missionga run biriktirmaslik uchun.
        row = await self._get_row(mission_id)
        if row is None:
            raise MissionNotFoundError(f"Mission topilmadi: {mission_id}")
        link = MissionRunLink(mission_id=mission_id, run_id=run_id, attempt=attempt)
        self._session.add(link)
        await self._session.flush()

    async def list_runs(self, mission_id: uuid.UUID) -> Sequence[uuid.UUID]:
        """Attempt → created_at tartibida run_id'lar."""
        # Owner tekshiruvi
        row = await self._get_row(mission_id)
        if row is None:
            raise MissionNotFoundError(f"Mission topilmadi: {mission_id}")
        stmt = (
            select(MissionRunLink.run_id)
            .where(MissionRunLink.mission_id == mission_id)
            .order_by(MissionRunLink.attempt, MissionRunLink.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_by_run(self, run_id: uuid.UUID) -> Mission | None:
        """Berilgan run qaysi missionga tegishli — orchestrator hook uchun."""
        stmt = (
            select(MissionORM)
            .join(MissionRunLink, MissionRunLink.mission_id == MissionORM.id)
            .where(
                MissionRunLink.run_id == run_id,
                MissionORM.owner_id == self._owner_id,
            )
            .limit(1)
        )
        row = (await self._session.execute(_fresh(stmt))).scalar_one_or_none()
        if row is None:
            return None
        return await self._to_domain(row)

    # ── Dashboard metrikalari ────────────────────────────────────

    async def count_by_status(self) -> dict[MissionStatus, int]:
        """Har holatdagi mission soni."""
        stmt = select(MissionORM.status).where(MissionORM.owner_id == self._owner_id)
        counts: dict[MissionStatus, int] = {}
        for (status,) in (await self._session.execute(stmt)).all():
            counts[status] = counts.get(status, 0) + 1
        return counts

    # ── Ichki ─────────────────────────────────────────────────

    async def _get_row(self, mission_id: uuid.UUID) -> MissionORM | None:
        stmt = select(MissionORM).where(
            MissionORM.id == mission_id, MissionORM.owner_id == self._owner_id
        )
        return (await self._session.execute(_fresh(stmt))).scalar_one_or_none()

    async def _to_domain(self, row: MissionORM) -> Mission:
        """ORM qatorni Pydantic Mission'ga aylantiradi.

        `run_ids` — join jadvalidan alohida so'rov bilan olinadi (lazy
        loading async'da xavfli edi).
        """
        run_ids = await self._session.execute(
            select(MissionRunLink.run_id)
            .where(MissionRunLink.mission_id == row.id)
            .order_by(MissionRunLink.attempt, MissionRunLink.created_at)
        )
        return Mission(
            id=row.id,
            owner_id=row.owner_id,
            objective=row.objective,
            outcome_criteria=row.outcome_criteria,
            context=row.context or {},
            constraints=list(row.constraints or []),
            tasks=list(row.tasks or []),
            agents=list(row.agents or []),
            tools=list(row.tools or []),
            capabilities=list(row.capabilities or []),
            permissions_required=list(row.permissions_required or []),
            risk_level=row.risk_level,
            approval_requirements=list(row.approval_requirements or []),
            deadline=row.deadline,
            verification_rules=list(row.verification_rules or []),
            memory_updates=list(row.memory_updates or []),
            status=row.status,
            priority=row.priority,
            run_ids=list(run_ids.scalars().all()),
            pending_approval_id=row.pending_approval_id,
            retry_count=row.retry_count,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


__all__ = ["MissionRepository"]
