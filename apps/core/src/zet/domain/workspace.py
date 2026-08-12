"""Ish maydoni domeni — loyiha, vazifa, kalendar hodisasi (Z46).

NEGA BU FAYL KERAK BO'LDI.

Frontend'da `/projects`, `/tasks`, `/calendar` sahifalari bor edi, lekin
ular ORTIDA HECH NARSA YO'Q edi — har uchalasi fayl ichida qotirilgan
massivdan chizilardi. Ega buni to'g'ri baholadi: "ko'p joyi soxta".

Backend'da bu uchtasi uchun jadval ham, endpoint ham yo'q edi:

    db/models/ → agent, cost, crm, memory, owner, run, security, tool
                 (task/project/event YO'Q)

`docs/12-AUTONOMY-GAP.md` buni allaqachon eng arzon g'alaba deb
belgilagan: `task_board` tashqi API talab qilmaydi va ikkita TIZIM
retseptini (T02, T06) ochadi.

Bog'liq qarorlar:
    V-13 — xotira qatlamlari (`MemoryLayer.TASK`/`PROJECT` shu bilan mos)
    A-01 — holat bazaga saqlanadi
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ProjectStatus(StrEnum):
    """Loyiha holati."""

    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"
    ARCHIVED = "archived"


class TaskStatus(StrEnum):
    """Vazifa holati — kanban ustunlari."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    """Vazifa muhimligi."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


TERMINAL_TASK_STATUSES: Final[frozenset[TaskStatus]] = frozenset(
    {TaskStatus.DONE, TaskStatus.CANCELLED}
)
"""Yakunlangan holatlar — `progress` hisobida va "bugungi ish"da chiqmaydi."""


PRIORITY_ORDER: Final[dict[TaskPriority, int]] = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}
"""Saralash tartibi — kichik son = yuqori muhimlik.

Alifbo bo'yicha saralash noto'g'ri chiqadi ("high" < "low" < "medium"
< "urgent"), shuning uchun aniq tartib kerak."""


__all__ = [
    "PRIORITY_ORDER",
    "TERMINAL_TASK_STATUSES",
    "ProjectStatus",
    "TaskPriority",
    "TaskStatus",
]
