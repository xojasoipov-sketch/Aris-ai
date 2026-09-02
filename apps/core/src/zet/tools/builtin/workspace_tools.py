"""Ish maydoni tool'lari — vazifa, loyiha, kalendar (Z48).

NEGA BU FAYL KERAK BO'LDI.

Z46'da `project`/`task`/`calendar_event` jadvallari, repozitoriy va 12
ta HTTP endpoint yozildi. Ya'ni EGA brauzer orqali vazifa qo'sha oladi.
Lekin **ZET o'zi qo'sha olmasdi**: agent faqat registry'dagi tool'lar
orqali ish qiladi, u yerda esa doska yo'q edi.

Aynan shu sabab `detect_capabilities()` `TASK_BOARD` va `CALENDAR`ni
"yo'q" deb sanardi va ikkita TIZIM retsepti bloklangan turardi:

    T02 "Ovozdan rejaga"  — 3-qadam: muddat va mas'ul biriktirish
    T06 "Kunlik puls"     — 1-qadam: barcha loyiha doskalarini tekshirish

Jadval bor, lekin unga agent yo'li yo'q edi — imkoniyatni "bor" deb
belgilash o'sha paytda YOLG'ON bo'lardi. Bu fayl yo'lni ochadi, shundan
keyingina `recipes.py`da imkoniyat yoqiladi.

SESSIYA. `memory.search` bilan bir xil naqsh: registry global singleton
(`lru_cache`), DB esa sessiyaga bog'liq. Shuning uchun tool sessiyani
emas, **sessiya ochadigan kontekst fabrikasini** oladi va har chaqiruvda
qisqa sessiya ochadi. Fabrika berilmasa tool ochiq xato qaytaradi —
jimgina bo'sh ro'yxat emas, aks holda "doska ulanmagan" va "doska bo'sh"
bir xil ko'rinardi.

Bog'liq qarorlar:
    V-31 — READ/WRITE ruxsat darajalari
    A-01 — holat bazaga saqlanadi
    A-05 — natija SYSTEM trust (ega o'z ma'lumoti, tashqi manba emas)
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from zet.db.base import utcnow
from zet.domain.enums import PermissionLevel
from zet.domain.workspace import (
    TERMINAL_TASK_STATUSES,
    ProjectStatus,
    TaskPriority,
    TaskStatus,
)
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.db.models.workspace import CalendarEvent, Project, Task
    from zet.workspace.repository import WorkspaceRepository

WorkspaceScope = Callable[[], "AbstractAsyncContextManager[WorkspaceRepository]"]
"""`async with scope() as repo:` — har chaqiruvda yangi qisqa sessiya."""

DEFAULT_TZ = "Asia/Tashkent"
"""Ega vaqt mintaqasi. LLM "ertaga soat 15:00" deganda AYNAN shu
mintaqa nazarda tutiladi — UTC emas. Baza doim UTC saqlaydi."""

STALE_DAYS = 3
"""Necha kun qimirlamagan vazifa "turib qolgan" deb hisoblanadi.

3 kun — ish haftasining yarmi: bir kun sekinlik normal, uch kun esa
allaqachon e'tibor talab qiladi."""

MAX_LIMIT = 200


class _WorkspaceTool(Tool):
    """Ish maydoni tool'lari uchun umumiy asos — sessiya va xatolar."""

    def __init__(self, *, scope: WorkspaceScope | None = None, tz: str = DEFAULT_TZ) -> None:
        self._scope = scope
        self._tz = tz

    # `output_trust_level` qayta yozilmaydi: default SYSTEM to'g'ri —
    # mazmun ega o'zi kiritgan yoki ZET yozgan, tashqi manba emas.

    @property
    def connected(self) -> bool:
        """Doska HAQIQATAN ulanganmi.

        Tool registry'da TURISHI yetarli emas: fabrika berilmasa tool
        chaqirilganda yiqiladi. `detect_capabilities()` aynan shu
        xossaga qaraydi — "tool bor" degani "ishlaydi" degani emas.
        """
        return self._scope is not None

    def _require_scope(self) -> WorkspaceScope:
        if self._scope is None:
            raise ToolError("Ish maydoni bazasi ulanmagan — vazifa/kalendar tool'lari ishlamaydi")
        return self._scope

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self._tz)
        except Exception:
            return ZoneInfo("UTC")

    def _parse_dt(self, raw: str | None, *, field: str) -> datetime | None:
        """LLM yozgan sanani UTC `datetime`ga o'giradi.

        Mintaqasiz yozilgan vaqt EGA MINTAQASIDA deb tushuniladi.
        Sukut bo'yicha UTC deb olish jimgina 5 soatlik xatoga olib
        kelardi: "ertaga 09:00" ertalab emas, tushdan keyin chiqardi.
        """
        if raw is None or not str(raw).strip():
            return None
        text = str(raw).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ToolError(
                f"`{field}` sanasini o'qib bo'lmadi: {raw!r}. "
                f"ISO formatda yoz, masalan 2026-08-14T15:00"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=self._zone())
        return parsed.astimezone(ZoneInfo("UTC"))

    def _local(self, value: datetime | None) -> str | None:
        """UTC vaqtni ega mintaqasidagi ko'rinishga o'giradi."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("UTC"))
        return value.astimezone(self._zone()).isoformat(timespec="minutes")


def _task_dict(task: Task, tool: _WorkspaceTool) -> dict[str, Any]:
    """Vazifani LLM o'qiy oladigan qisqa lug'atga aylantiradi.

    `description` ATAYIN qisqartiriladi: ro'yxatda o'nlab vazifa bo'lsa
    to'liq matn kontekstni to'ldirib, muhim narsani siqib chiqaradi.
    """
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status.value,
        "priority": task.priority.value,
        "due_at": tool._local(task.due_at),
        "assigned_agent": task.assigned_agent or None,
        "project_id": str(task.project_id) if task.project_id else None,
        "updated_at": tool._local(task.updated_at),
    }


def _project_dict(
    project: Project, counts: tuple[int, int], tool: _WorkspaceTool
) -> dict[str, Any]:
    total, done = counts
    return {
        "id": str(project.id),
        "name": project.name,
        "status": project.status.value,
        "task_total": total,
        "task_done": done,
        "progress": round(done * 100 / total) if total else 0,
        "due_at": tool._local(project.due_at),
    }


def _event_dict(event: CalendarEvent, tool: _WorkspaceTool) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "title": event.title,
        "starts_at": tool._local(event.starts_at),
        "ends_at": tool._local(event.ends_at),
        "location": event.location or None,
        "all_day": event.all_day,
    }


def _parse_uuid(raw: str | None, *, field: str) -> uuid.UUID | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return uuid.UUID(str(raw).strip())
    except ValueError as exc:
        raise ToolError(f"`{field}` haqiqiy ID emas: {raw!r}") from exc


# ── Vazifalar ─────────────────────────────────────────────────────


class TaskListTool(_WorkspaceTool):
    """Doskadagi vazifalarni o'qiydi."""

    @property
    def name(self) -> str:
        return "task.list"

    @property
    def description(self) -> str:
        return (
            "Ega vazifalar doskasini o'qiydi. Holat bo'yicha filtrlash mumkin "
            "(todo, in_progress, blocked, done, cancelled). 'Nima qilishim kerak', "
            "'qaysi ishlar ochiq', 'doskada nima bor' savollariga shu tool javob beradi."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [s.value for s in TaskStatus],
                    "description": "Faqat shu holatdagi vazifalar (bermasang — hammasi)",
                },
                "project_id": {"type": "string", "description": "Faqat shu loyiha vazifalari"},
                "limit": {"type": "integer", "description": f"Nechta (1-{MAX_LIMIT})"},
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        status = TaskStatus(params["status"]) if params.get("status") else None
        project_id = _parse_uuid(params.get("project_id"), field="project_id")
        limit = max(1, min(int(params.get("limit", 50)), MAX_LIMIT))

        async with scope() as repo:
            tasks = await repo.list_tasks(status=status, project_id=project_id, limit=limit)
            return {"total": len(tasks), "tasks": [_task_dict(t, self) for t in tasks]}


class TaskCreateTool(_WorkspaceTool):
    """Doskaga yangi vazifa qo'shadi."""

    @property
    def name(self) -> str:
        return "task.create"

    @property
    def description(self) -> str:
        return (
            "Doskaga yangi vazifa qo'shadi — sarlavha, muhimlik va muddat bilan. "
            "Ega 'buni eslab qol', 'shuni qilish kerak', 'ro'yxatga qo'sh' desa shu tool."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Vazifa sarlavhasi — qisqa va aniq"},
                "description": {"type": "string", "description": "Qo'shimcha tafsilot"},
                "priority": {
                    "type": "string",
                    "enum": [p.value for p in TaskPriority],
                    "description": "Muhimlik (default: medium)",
                },
                "due_at": {
                    "type": "string",
                    "description": "Muddat, ISO format: 2026-08-14T15:00 (ega vaqt mintaqasida)",
                },
                "project_id": {"type": "string", "description": "Qaysi loyihaga tegishli"},
            },
            "required": ["title"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        # Ikki marta chaqirilsa IKKITA vazifa paydo bo'ladi.
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        title = str(params.get("title", "")).strip()
        if not title:
            raise ToolError("`title` bo'sh bo'lmasligi kerak")

        async with scope() as repo:
            task = await repo.create_task(
                title=title,
                description=str(params.get("description", "")),
                priority=params.get("priority"),
                due_at=self._parse_dt(params.get("due_at"), field="due_at"),
                project_id=_parse_uuid(params.get("project_id"), field="project_id"),
            )
            return {"created": True, "task": _task_dict(task, self)}


class TaskUpdateTool(_WorkspaceTool):
    """Vazifa holatini/maydonlarini o'zgartiradi."""

    @property
    def name(self) -> str:
        return "task.update"

    @property
    def description(self) -> str:
        return (
            "YOZISH: Mavjud vazifani yangilaydi — holatini o'zgartirish "
            "(bajarildi, jarayonda, to'sildi), muhimligini yoki muddatini "
            "qayta belgilash. AVVAL `task.list` bilan ID'ni top. DIQQAT: "
            "yangi vazifa YOZISH uchun EMAS — buning uchun task.create."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Vazifa ID (task.list bergan)"},
                "status": {"type": "string", "enum": [s.value for s in TaskStatus]},
                "priority": {"type": "string", "enum": [p.value for p in TaskPriority]},
                "title": {"type": "string"},
                "due_at": {"type": "string", "description": "Yangi muddat, ISO format"},
            },
            "required": ["task_id"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        from zet.workspace.repository import WorkspaceNotFoundError

        scope = self._require_scope()
        task_id = _parse_uuid(params.get("task_id"), field="task_id")
        if task_id is None:
            raise ToolError("`task_id` majburiy")

        fields: dict[str, object] = {}
        if params.get("status"):
            fields["status"] = TaskStatus(params["status"])
        if params.get("priority"):
            fields["priority"] = TaskPriority(params["priority"])
        if params.get("title"):
            fields["title"] = str(params["title"]).strip()
        if params.get("due_at"):
            fields["due_at"] = self._parse_dt(params.get("due_at"), field="due_at")
        if not fields:
            raise ToolError("Hech qanday o'zgarish berilmadi")

        async with scope() as repo:
            try:
                task = await repo.update_task(task_id, **fields)
            except WorkspaceNotFoundError as exc:
                raise ToolError(str(exc)) from exc
            return {"updated": True, "task": _task_dict(task, self)}


class TaskPulseTool(_WorkspaceTool):
    """TIZIM T06 "Kunlik puls"ning o'lchov qismi.

    Slaydda uch qadam bor: (1) doskani tekshir, (2) siljigan va turib
    qolganini AJRAT, (3) qaror kutayotganini yig'. 2-qadamni LLM'ga
    berish noto'g'ri bo'lardi — bu sof hisob, va LLM sanani noto'g'ri
    solishtirib "turib qolgan" ishni "siljigan" deb ko'rsatib yuborishi
    mumkin. Shu sabab ajratish SHU YERDA, kodda bajariladi; LLM'ga esa
    faqat uch ro'yxatni chiroyli gapga aylantirish qoladi.
    """

    @property
    def name(self) -> str:
        return "task.pulse"

    @property
    def description(self) -> str:
        return (
            "Doskaning kunlik pulsi: oxirgi kunda NIMA SILJIDI, nima TURIB QOLDI "
            "va nima EGA QARORINI KUTMOQDA — uchta tayyor ro'yxat. Kunlik/haftalik "
            "hisobot so'ralganda shu tooldan foydalan."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "since_hours": {
                    "type": "integer",
                    "description": "Necha soat orqaga qaralsin (default 24)",
                },
                "stale_days": {
                    "type": "integer",
                    "description": f"Necha kun qimirlamagan ish 'turib qolgan' (default {STALE_DAYS})",
                },
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        since_hours = max(1, min(int(params.get("since_hours", 24)), 24 * 30))
        stale_days = max(1, min(int(params.get("stale_days", STALE_DAYS)), 90))

        now = utcnow()
        since = now - timedelta(hours=since_hours)
        stale_before = now - timedelta(days=stale_days)

        async with scope() as repo:
            tasks = list(await repo.list_tasks(limit=MAX_LIMIT))
            projects = list(await repo.list_projects(status=ProjectStatus.ACTIVE))
            counts = await repo.project_task_counts()

            moved = [t for t in tasks if _updated(t) >= since]
            stuck = [
                t
                for t in tasks
                if t.status not in TERMINAL_TASK_STATUSES and _updated(t) < stale_before
            ]
            # "Qaror kutmoqda" = to'silgan ish (kimdir yo'lni ochishi
            # kerak) + muddati o'tib ketgan ish (ko'chirish yoki bekor
            # qilish — ikkalasi ham EGA qarori).
            waiting = [
                t
                for t in tasks
                if t.status is TaskStatus.BLOCKED
                or (
                    t.due_at is not None
                    and t.status not in TERMINAL_TASK_STATUSES
                    and _aware(t.due_at) < now
                )
            ]

            return {
                "generated_at": self._local(now),
                "window_hours": since_hours,
                "moved": [_task_dict(t, self) for t in moved],
                "stuck": [_task_dict(t, self) for t in stuck],
                "awaiting_decision": [_task_dict(t, self) for t in waiting],
                "summary": {
                    "moved": len(moved),
                    "stuck": len(stuck),
                    "awaiting_decision": len(waiting),
                    "open_total": sum(1 for t in tasks if t.status not in TERMINAL_TASK_STATUSES),
                },
                "projects": [_project_dict(p, counts.get(p.id, (0, 0)), self) for p in projects],
            }


def _updated(task: Task) -> datetime:
    """Vazifaning oxirgi qimirlagan payti (doim tz-aware)."""
    return _aware(task.updated_at or task.created_at)


def _aware(value: datetime) -> datetime:
    """Naiv sanani UTC deb belgilaydi.

    SQLite naiv `datetime` qaytaradi, Postgres esa tz-aware. Ularni
    aralashtirib solishtirish `TypeError` beradi — puls hisobi aynan
    shunday yiqilardi."""
    return value if value.tzinfo is not None else value.replace(tzinfo=ZoneInfo("UTC"))


# ── Loyihalar ─────────────────────────────────────────────────────


class ProjectListTool(_WorkspaceTool):
    """Loyihalar va ularning bajarilish foizi."""

    @property
    def name(self) -> str:
        return "project.list"

    @property
    def description(self) -> str:
        return (
            "Loyihalar ro'yxati va har birining bajarilish foizi (vazifalardan "
            "hisoblangan). 'Loyihalarim qanday ketyapti' savoliga shu tool javob beradi."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [s.value for s in ProjectStatus],
                    "description": "Faqat shu holatdagi loyihalar",
                }
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        status = ProjectStatus(params["status"]) if params.get("status") else None

        async with scope() as repo:
            projects = await repo.list_projects(status=status)
            counts = await repo.project_task_counts()
            return {
                "total": len(projects),
                "projects": [_project_dict(p, counts.get(p.id, (0, 0)), self) for p in projects],
            }


class ProjectCreateTool(_WorkspaceTool):
    """Yangi loyiha ochadi."""

    @property
    def name(self) -> str:
        return "project.create"

    @property
    def description(self) -> str:
        return "Yangi loyiha ochadi — vazifalarni guruhlash uchun."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Loyiha nomi"},
                "description": {"type": "string"},
                "due_at": {"type": "string", "description": "Tugash muddati, ISO format"},
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        name = str(params.get("name", "")).strip()
        if not name:
            raise ToolError("`name` bo'sh bo'lmasligi kerak")

        async with scope() as repo:
            project = await repo.create_project(
                name=name,
                description=str(params.get("description", "")),
                due_at=self._parse_dt(params.get("due_at"), field="due_at"),
            )
            return {"created": True, "project": _project_dict(project, (0, 0), self)}


# ── Kalendar ──────────────────────────────────────────────────────


class CalendarListTool(_WorkspaceTool):
    """Kelayotgan hodisalar."""

    @property
    def name(self) -> str:
        return "calendar.list"

    @property
    def description(self) -> str:
        return (
            "Kalendardagi hodisalar — kelgusi kunlar uchun. 'Bugun nima bor', "
            "'ertaga uchrashuv bormi', 'bu hafta jadval qanday' savollariga javob."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Necha kun oldinga qaralsin (default 7)",
                },
                "include_past_days": {
                    "type": "integer",
                    "description": "Necha kun orqaga ham qo'shilsin (default 0)",
                },
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        days = max(1, min(int(params.get("days", 7)), 365))
        past = max(0, min(int(params.get("include_past_days", 0)), 365))

        now = utcnow()
        async with scope() as repo:
            events = await repo.list_events(
                start=now - timedelta(days=past), end=now + timedelta(days=days)
            )
            return {
                "total": len(events),
                "from": self._local(now - timedelta(days=past)),
                "to": self._local(now + timedelta(days=days)),
                "events": [_event_dict(e, self) for e in events],
            }


class CalendarAddTool(_WorkspaceTool):
    """Kalendarga hodisa yozadi."""

    @property
    def name(self) -> str:
        return "calendar.add"

    @property
    def description(self) -> str:
        return (
            "Kalendarga hodisa yozadi — uchrashuv, qo'ng'iroq, eslatma. "
            "Boshlanish vaqti majburiy; davomiylik berilmasa 60 daqiqa olinadi."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Hodisa nomi"},
                "starts_at": {
                    "type": "string",
                    "description": "Boshlanish, ISO: 2026-08-14T15:00 (ega vaqt mintaqasida)",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Davomiyligi daqiqada (default 60)",
                },
                "description": {"type": "string"},
                "location": {"type": "string", "description": "Joy yoki havola"},
            },
            "required": ["title", "starts_at"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        title = str(params.get("title", "")).strip()
        if not title:
            raise ToolError("`title` bo'sh bo'lmasligi kerak")

        starts_at = self._parse_dt(params.get("starts_at"), field="starts_at")
        if starts_at is None:
            raise ToolError("`starts_at` majburiy")

        minutes = max(5, min(int(params.get("duration_minutes", 60)), 60 * 24))

        async with scope() as repo:
            event = await repo.create_event(
                title=title,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=minutes),
                description=str(params.get("description", "")),
                location=str(params.get("location", "")),
            )
            return {"created": True, "event": _event_dict(event, self)}


WORKSPACE_TOOL_CLASSES: tuple[type[_WorkspaceTool], ...] = (
    TaskListTool,
    TaskCreateTool,
    TaskUpdateTool,
    TaskPulseTool,
    ProjectListTool,
    ProjectCreateTool,
    CalendarListTool,
    CalendarAddTool,
)
"""Registry shu ro'yxatdan yuradi — yangi tool qo'shilsa bitta qator."""


__all__ = [
    "WORKSPACE_TOOL_CLASSES",
    "CalendarAddTool",
    "CalendarListTool",
    "ProjectCreateTool",
    "ProjectListTool",
    "TaskCreateTool",
    "TaskListTool",
    "TaskPulseTool",
    "TaskUpdateTool",
    "WorkspaceScope",
]
