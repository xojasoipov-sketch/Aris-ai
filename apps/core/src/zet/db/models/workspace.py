"""Ish maydoni DB modellari — loyiha, vazifa, kalendar (Z46).

`/projects`, `/tasks`, `/calendar` sahifalari ORTIDA hech narsa yo'q
edi — uchalasi ham frontend fayli ichidagi qotirilgan massivdan
chizilardi. Bu jadvallar shu bo'shliqni yopadi.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
    V-13 — xotira qatlamlari (`MemoryLayer.TASK`/`PROJECT` bilan mos)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin, enum_column
from zet.domain.workspace import ProjectStatus, TaskPriority, TaskStatus


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Loyiha — vazifalarni guruhlaydi."""

    __tablename__ = "project"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[ProjectStatus] = mapped_column(
        enum_column(ProjectStatus), default=ProjectStatus.ACTIVE, index=True
    )
    color: Mapped[str] = mapped_column(String(16), default="")
    """UI uchun ixtiyoriy rang belgisi (masalan `#4C8DFF`)."""

    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    __table_args__ = (Index("ix_project_owner_status", "owner_id", "status"),)


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Vazifa — kanban kartochkasi."""

    __tablename__ = "task"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        # `SET NULL` — loyiha o'chirilsa vazifa YO'QOLMAYDI, faqat
        # bog'lanishini yo'qotadi. `CASCADE` bo'lsa bitta loyihani
        # o'chirish ega ishini jimgina yo'q qilib yuborardi.
        ForeignKey("project.id", ondelete="SET NULL"),
        default=None,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus), default=TaskStatus.TODO, index=True
    )
    priority: Mapped[TaskPriority] = mapped_column(
        enum_column(TaskPriority), default=TaskPriority.MEDIUM, index=True
    )
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None, index=True)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    assigned_agent: Mapped[str] = mapped_column(String(64), default="")
    """Qaysi agentga biriktirilgan (`agent.name`). Bo'sh — ega o'zi.

    ForeignKey EMAS: agentlar registry'da ham (kod) yashaydi, jadvalda
    ham; qattiq bog'lash agent nomi o'zgarganda vazifani yiqitardi."""

    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL"), default=None
    )
    """Qaysi run bu vazifani yaratdi (ZET o'zi qo'shgan bo'lsa)."""

    __table_args__ = (
        Index("ix_task_owner_status", "owner_id", "status"),
        Index("ix_task_owner_due", "owner_id", "due_at"),
    )


class CalendarEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Kalendar hodisasi.

    Bu ZET'ning ICHKI kalendari — Google Calendar integratsiyasi
    ALOHIDA ish (`docs/12-AUTONOMY-GAP.md` §7, `calendar` imkoniyati).
    Ichki kalendar tashqi API'siz ham ishlaydi, tashqisi ulanganda esa
    shu jadvalga sinxronlanadi.
    """

    __tablename__ = "calendar_event"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), default=None, index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)

    external_id: Mapped[str] = mapped_column(String(200), default="")
    """Tashqi kalendar (Google) hodisa ID'si — dublikatning oldini oladi."""

    __table_args__ = (Index("ix_calendar_event_owner_start", "owner_id", "starts_at"),)
