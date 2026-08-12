"""Ish maydoni API — loyiha, vazifa, kalendar (Z46).

    GET/POST         /api/v1/projects
    GET/PATCH/DELETE /api/v1/projects/{id}
    GET/POST         /api/v1/tasks
    GET/PATCH/DELETE /api/v1/tasks/{id}
    GET/POST         /api/v1/events
    GET/PATCH/DELETE /api/v1/events/{id}

NEGA BU ROUTE'LAR KERAK BO'LDI.

`/projects`, `/tasks`, `/calendar` sahifalari mavjud edi, lekin ular
ortida BACKEND YO'Q edi — uchalasi ham frontend fayli ichidagi
qotirilgan massivdan chizilardi ("ZET Core 78%", "SMM strategiyani
yangilash 10:00"). Vazifani belgilash sahifani yangilashda yo'qolardi.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
    V-31 — READ/WRITE ruxsat darajalari (bu route'lar ega tokeni ostida)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from zet.api.deps import get_workspace
from zet.domain.workspace import ProjectStatus, TaskPriority, TaskStatus
from zet.workspace.repository import WorkspaceNotFoundError, WorkspaceRepository

router = APIRouter(tags=["workspace"])


# ── Javob modellari ──────────────────────────────────────────────


class ProjectResponse(BaseModel):
    """Loyiha + haqiqiy vazifa hisobi."""

    id: str
    name: str
    description: str
    status: ProjectStatus
    color: str
    due_at: datetime | None
    created_at: datetime
    task_total: int
    task_done: int
    progress: int
    """0-100. Vazifalardan HISOBLANADI — qotirilgan foiz emas."""


class TaskResponse(BaseModel):
    id: str
    project_id: str | None
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    done_at: datetime | None
    assigned_agent: str
    created_at: datetime


class EventResponse(BaseModel):
    id: str
    project_id: str | None
    title: str
    description: str
    location: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool


# ── So'rov modellari ─────────────────────────────────────────────


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    color: str = ""
    due_at: datetime | None = None


class ProjectUpdateRequest(BaseModel):
    """Faqat berilgan maydonlar o'zgaradi (`None` = tegilmaydi)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: ProjectStatus | None = None
    color: str | None = None
    due_at: datetime | None = None


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    project_id: str | None = None
    due_at: datetime | None = None
    assigned_agent: str = ""


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    project_id: str | None = None
    due_at: datetime | None = None
    assigned_agent: str | None = None


class EventCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    starts_at: datetime
    ends_at: datetime | None = None
    description: str = ""
    location: str = ""
    all_day: bool = False
    project_id: str | None = None


class EventUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    description: str | None = None
    location: str | None = None
    all_day: bool | None = None
    project_id: str | None = None


# ── Yordamchilar ─────────────────────────────────────────────────


def _uuid(value: str | None, *, field: str) -> uuid.UUID | None:
    """Matn UUID'ni tekshiradi — noto'g'ri format 500 emas, 422 bo'lsin."""
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Noto'g'ri {field}: {value}") from exc


def _require_uuid(value: str, *, field: str) -> uuid.UUID:
    parsed = _uuid(value, field=field)
    if parsed is None:
        raise HTTPException(status_code=422, detail=f"{field} bo'sh bo'lmasligi kerak")
    return parsed


# ── Loyihalar ────────────────────────────────────────────────────


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    status: ProjectStatus | None = None,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> list[ProjectResponse]:
    """Loyihalar — progress haqiqiy vazifalardan hisoblanadi."""
    projects = await repo.list_projects(status=status)
    counts = await repo.project_task_counts()
    return [_project_response(p, counts.get(p.id, (0, 0))) for p in projects]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    request: ProjectCreateRequest,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> ProjectResponse:
    project = await repo.create_project(**request.model_dump())
    return _project_response(project, (0, 0))


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> ProjectResponse:
    try:
        project = await repo.update_project(
            _require_uuid(project_id, field="project_id"), **request.model_dump()
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    counts = await repo.project_task_counts()
    return _project_response(project, counts.get(project.id, (0, 0)))


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> None:
    try:
        await repo.delete_project(_require_uuid(project_id, field="project_id"))
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Vazifalar ────────────────────────────────────────────────────


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    status: TaskStatus | None = None,
    project_id: str | None = None,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> list[TaskResponse]:
    tasks = await repo.list_tasks(status=status, project_id=_uuid(project_id, field="project_id"))
    return [_task_response(t) for t in tasks]


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> TaskResponse:
    data = request.model_dump()
    data["project_id"] = _uuid(data["project_id"], field="project_id")
    task = await repo.create_task(**data)
    return _task_response(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> TaskResponse:
    data = request.model_dump()
    if data.get("project_id") is not None:
        data["project_id"] = _uuid(data["project_id"], field="project_id")
    try:
        task = await repo.update_task(_require_uuid(task_id, field="task_id"), **data)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _task_response(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> None:
    try:
        await repo.delete_task(_require_uuid(task_id, field="task_id"))
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Kalendar ─────────────────────────────────────────────────────


@router.get("/events", response_model=list[EventResponse])
async def list_events(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    repo: WorkspaceRepository = Depends(get_workspace),
) -> list[EventResponse]:
    events = await repo.list_events(start=start, end=end)
    return [_event_response(e) for e in events]


@router.post("/events", response_model=EventResponse, status_code=201)
async def create_event(
    request: EventCreateRequest,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> EventResponse:
    data = request.model_dump()
    data["project_id"] = _uuid(data["project_id"], field="project_id")
    event = await repo.create_event(**data)
    return _event_response(event)


@router.patch("/events/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    request: EventUpdateRequest,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> EventResponse:
    data = request.model_dump()
    if data.get("project_id") is not None:
        data["project_id"] = _uuid(data["project_id"], field="project_id")
    try:
        event = await repo.update_event(_require_uuid(event_id, field="event_id"), **data)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _event_response(event)


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: str,
    repo: WorkspaceRepository = Depends(get_workspace),
) -> None:
    try:
        await repo.delete_event(_require_uuid(event_id, field="event_id"))
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Konvertorlar ─────────────────────────────────────────────────


def _project_response(project: object, counts: tuple[int, int]) -> ProjectResponse:
    total, done = counts
    return ProjectResponse(
        id=str(project.id),  # type: ignore[attr-defined]
        name=project.name,  # type: ignore[attr-defined]
        description=project.description,  # type: ignore[attr-defined]
        status=project.status,  # type: ignore[attr-defined]
        color=project.color,  # type: ignore[attr-defined]
        due_at=project.due_at,  # type: ignore[attr-defined]
        created_at=project.created_at,  # type: ignore[attr-defined]
        task_total=total,
        task_done=done,
        # Vazifasiz loyiha 0% — 100% emas. "Hech nima yo'q" ni
        # "hammasi bajarildi" deb ko'rsatish yolg'on bo'lardi.
        progress=round(done * 100 / total) if total else 0,
    )


def _task_response(task: object) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),  # type: ignore[attr-defined]
        project_id=str(task.project_id) if task.project_id else None,  # type: ignore[attr-defined]
        title=task.title,  # type: ignore[attr-defined]
        description=task.description,  # type: ignore[attr-defined]
        status=task.status,  # type: ignore[attr-defined]
        priority=task.priority,  # type: ignore[attr-defined]
        due_at=task.due_at,  # type: ignore[attr-defined]
        done_at=task.done_at,  # type: ignore[attr-defined]
        assigned_agent=task.assigned_agent,  # type: ignore[attr-defined]
        created_at=task.created_at,  # type: ignore[attr-defined]
    )


def _event_response(event: object) -> EventResponse:
    return EventResponse(
        id=str(event.id),  # type: ignore[attr-defined]
        project_id=str(event.project_id) if event.project_id else None,  # type: ignore[attr-defined]
        title=event.title,  # type: ignore[attr-defined]
        description=event.description,  # type: ignore[attr-defined]
        location=event.location,  # type: ignore[attr-defined]
        starts_at=event.starts_at,  # type: ignore[attr-defined]
        ends_at=event.ends_at,  # type: ignore[attr-defined]
        all_day=event.all_day,  # type: ignore[attr-defined]
    )
