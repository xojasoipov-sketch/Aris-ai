"""Ish maydoni repozitoriysi — loyiha/vazifa/kalendar CRUD (Z46).

Route'lar SQL yozmaydi: butun DB mantiqi shu yerda. Shu bilan bir xil
amal Telegram bot, tool yoki agent tomonidan ham chaqirilishi mumkin
(hozircha API, keyin `task.create` tooli).

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.base import utcnow
from zet.db.models.workspace import CalendarEvent, Project, Task
from zet.domain.workspace import ProjectStatus, TaskPriority, TaskStatus


class WorkspaceNotFoundError(Exception):
    """So'ralgan yozuv topilmadi (yoki boshqa egaga tegishli)."""


def _fresh(stmt: Select[Any]) -> Select[Any]:
    """So'rovni bazadagi HOZIRGI qiymat bilan qaytarishga majbur qiladi.

    SQLAlchemy sukut bo'yicha sessiyada allaqachon yuklangan obyektni
    qaytaradi va uning maydonlarini SELECT natijasi bilan YANGILAMAYDI.
    Odatda bu tez, lekin baza yozuvni O'ZI o'zgartirgan holatda xato
    beradi: loyiha o'chirilganda `task.project_id` FK qoidasi bilan
    (`SET NULL`) bo'shatiladi — sessiyadagi obyekt esa o'chirilgan
    loyihaga ishora qilib turaverardi.

    `expire_all()` bu yerda YARAMAYDI: muddati o'tgan atributga
    murojaat sinxron IO talab qiladi va async kontekstda
    `MissingGreenlet` bilan yiqiladi. `populate_existing` esa
    qiymatlarni AYNI SELECT ichida yangilaydi.
    """
    return stmt.execution_options(populate_existing=True)


class WorkspaceRepository:
    """Loyiha/vazifa/kalendar yozuvlari bilan ishlaydi.

    Har bir metod `owner_id` bo'yicha cheklaydi — ega bittaligiga
    qaramay, bu qatlam noto'g'ri so'rovda boshqa yozuvni qaytarib
    yubormasligi uchun.
    """

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    # ── Loyihalar ────────────────────────────────────────────────

    async def create_project(
        self,
        *,
        name: str,
        description: str = "",
        status: ProjectStatus = ProjectStatus.ACTIVE,
        color: str = "",
        due_at: datetime | None = None,
    ) -> Project:
        project = Project(
            owner_id=self._owner_id,
            name=name,
            description=description,
            status=status,
            color=color,
            due_at=due_at,
        )
        self._session.add(project)
        await self._session.flush()
        return project

    async def list_projects(
        self, *, status: ProjectStatus | None = None, limit: int = 100
    ) -> Sequence[Project]:
        stmt = select(Project).where(Project.owner_id == self._owner_id)
        if status is not None:
            stmt = stmt.where(Project.status == status)
        stmt = stmt.order_by(Project.created_at.desc()).limit(limit)
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    async def get_project(self, project_id: uuid.UUID) -> Project:
        stmt = select(Project).where(Project.id == project_id, Project.owner_id == self._owner_id)
        project: Project | None = (await self._session.execute(_fresh(stmt))).scalar_one_or_none()
        if project is None:
            raise WorkspaceNotFoundError(f"Loyiha topilmadi: {project_id}")
        return project

    async def update_project(self, project_id: uuid.UUID, **fields: object) -> Project:
        project = await self.get_project(project_id)
        _apply(project, fields)
        await self._session.flush()
        return project

    async def delete_project(self, project_id: uuid.UUID) -> None:
        project = await self.get_project(project_id)
        await self._session.delete(project)
        await self._session.flush()

    async def project_task_counts(self) -> dict[uuid.UUID, tuple[int, int]]:
        """Loyiha → (jami vazifa, bajarilgan vazifa).

        Progress'ni FRONTEND o'ylab topmasligi uchun — ilgari u
        qotirilgan foiz edi ("ZET Core 78%"). Endi son haqiqiy
        vazifalardan hisoblanadi.
        """
        stmt = select(Task.project_id, Task.status).where(
            Task.owner_id == self._owner_id, Task.project_id.is_not(None)
        )
        counts: dict[uuid.UUID, tuple[int, int]] = {}
        for project_id, status in (await self._session.execute(stmt)).all():
            total, done = counts.get(project_id, (0, 0))
            counts[project_id] = (
                total + 1,
                done + (1 if status is TaskStatus.DONE else 0),
            )
        return counts

    # ── Vazifalar ────────────────────────────────────────────────

    async def create_task(
        self,
        *,
        title: str,
        description: str = "",
        status: TaskStatus = TaskStatus.TODO,
        priority: TaskPriority | str | None = None,
        project_id: uuid.UUID | None = None,
        due_at: datetime | None = None,
        assigned_agent: str = "",
        source_run_id: uuid.UUID | None = None,
    ) -> Task:
        task = Task(
            owner_id=self._owner_id,
            title=title,
            description=description,
            status=status,
            project_id=project_id,
            due_at=due_at,
            assigned_agent=assigned_agent,
            source_run_id=source_run_id,
            # `done_at` DARHOL to'ldiriladi, agar vazifa allaqachon
            # bajarilgan holda yaratilsa (import/migratsiya holati).
            done_at=utcnow() if status is TaskStatus.DONE else None,
        )
        if priority is not None:
            # MAJBURIY o'girish: xom satr berilsa obyekt xotirada satr
            # bo'lib qolardi (SQLAlchemy uni faqat yozishda o'giradi) va
            # `task.priority.value` o'qigan har bir joy `AttributeError`
            # bilan yiqilardi — `task.create` tooli aynan shunga urildi.
            task.priority = TaskPriority(priority)
        self._session.add(task)
        await self._session.flush()
        return task

    async def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> Sequence[Task]:
        stmt = select(Task).where(Task.owner_id == self._owner_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if project_id is not None:
            stmt = stmt.where(Task.project_id == project_id)
        stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    async def get_task(self, task_id: uuid.UUID) -> Task:
        stmt = select(Task).where(Task.id == task_id, Task.owner_id == self._owner_id)
        task: Task | None = (await self._session.execute(_fresh(stmt))).scalar_one_or_none()
        if task is None:
            raise WorkspaceNotFoundError(f"Vazifa topilmadi: {task_id}")
        return task

    async def update_task(self, task_id: uuid.UUID, **fields: object) -> Task:
        task = await self.get_task(task_id)
        previous = task.status
        _apply(task, fields)

        # `done_at` avtomatik — foydalanuvchi uni qo'lda yubormaydi.
        # Holat DONE'ga o'tganda belgilanadi, DONE'dan chiqsa tozalanadi;
        # aks holda "bajarildi" sanasi eski qiymatda qotib qolardi.
        if task.status is TaskStatus.DONE and previous is not TaskStatus.DONE:
            task.done_at = utcnow()
        elif task.status is not TaskStatus.DONE:
            task.done_at = None

        await self._session.flush()
        return task

    async def delete_task(self, task_id: uuid.UUID) -> None:
        task = await self.get_task(task_id)
        await self._session.delete(task)
        await self._session.flush()

    # ── Kalendar ─────────────────────────────────────────────────

    async def create_event(
        self,
        *,
        title: str,
        starts_at: datetime,
        ends_at: datetime | None = None,
        description: str = "",
        location: str = "",
        all_day: bool = False,
        project_id: uuid.UUID | None = None,
        external_id: str = "",
    ) -> CalendarEvent:
        event = CalendarEvent(
            owner_id=self._owner_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            description=description,
            location=location,
            all_day=all_day,
            project_id=project_id,
            external_id=external_id,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> Sequence[CalendarEvent]:
        """Oraliqdagi hodisalar (oy ko'rinishi uchun)."""
        stmt = select(CalendarEvent).where(CalendarEvent.owner_id == self._owner_id)
        if start is not None:
            stmt = stmt.where(CalendarEvent.starts_at >= start)
        if end is not None:
            stmt = stmt.where(CalendarEvent.starts_at <= end)
        stmt = stmt.order_by(CalendarEvent.starts_at).limit(limit)
        return (await self._session.execute(_fresh(stmt))).scalars().all()

    async def get_event(self, event_id: uuid.UUID) -> CalendarEvent:
        stmt = select(CalendarEvent).where(
            CalendarEvent.id == event_id, CalendarEvent.owner_id == self._owner_id
        )
        event: CalendarEvent | None = (
            await self._session.execute(_fresh(stmt))
        ).scalar_one_or_none()
        if event is None:
            raise WorkspaceNotFoundError(f"Hodisa topilmadi: {event_id}")
        return event

    async def update_event(self, event_id: uuid.UUID, **fields: object) -> CalendarEvent:
        event = await self.get_event(event_id)
        _apply(event, fields)
        await self._session.flush()
        return event

    async def delete_event(self, event_id: uuid.UUID) -> None:
        event = await self.get_event(event_id)
        await self._session.delete(event)
        await self._session.flush()


def _apply(entity: object, fields: dict[str, object]) -> None:
    """`None` bo'lmagan maydonlarni yozadi.

    `None` = "o'zgartirma" degani, chunki PATCH so'rovida berilmagan
    maydonlar Pydantic'da `None` bo'lib keladi. Maydonni ATAYIN
    tozalash kerak bo'lsa, route uni alohida hal qiladi."""
    for key, value in fields.items():
        if value is not None:
            setattr(entity, key, value)


__all__ = ["WorkspaceNotFoundError", "WorkspaceRepository"]
