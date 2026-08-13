"""Run / Plan / Step — davomli holat mashinasi (A-01).

Holat **bazada** saqlanadi, xotirada emas: protsess qayta ishga tushsa ish davom etadi,
va approval oqimni soatlarga to'xtatishi mumkin.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from zet.domain.enums import (
    PermissionLevel,
    RunStatus,
    RunTrigger,
    StepStatus,
    TaskClass,
    TrustLevel,
)


class Run(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta buyruq sikli: intent -> reja -> bajarish -> tekshirish."""

    __tablename__ = "run"
    __table_args__ = (
        CheckConstraint("depth >= 0", name="depth_non_negative"),
        CheckConstraint("spent_usd >= 0", name="spent_non_negative"),
        Index("ix_run_status_created", "status", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL"), default=None, index=True
    )
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL"), default=None, index=True
    )
    """Agent trigger'i orqali tug'ilgan run — `depth` shu zanjir uzunligi (A-07)."""

    trigger: Mapped[RunTrigger] = mapped_column(default=RunTrigger.MANUAL)
    command_text: Mapped[str] = mapped_column(Text)
    status: Mapped[RunStatus] = mapped_column(default=RunStatus.PENDING, index=True)

    intent: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    task_class: Mapped[TaskClass | None] = mapped_column(default=None)

    # A-07 tormozlari
    depth: Mapped[int] = mapped_column(Integer, default=0)
    budget_usd: Mapped[float] = mapped_column(default=0.10)
    spent_usd: Mapped[float] = mapped_column(default=0.0)

    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    verified_ok: Mapped[bool | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    result_summary: Mapped[str | None] = mapped_column(Text, default=None)

    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)

    completed_steps: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    """HIGH #2 audit fix (KONSOLIDATSIYA v2 — bo'lim D2). Position (string
    kalit, JSON talabi) -> serializatsiya qilingan `StepResult`.

    NEGA: `Orchestrator._run_plan()` har chaqiruvda (shu jumladan
    `resume()`, tasdiqdan keyin) YANGI bo'sh `ExecutionContext` yaratardi
    — rejaning BOSHIDAN qayta bajarardi. Idempotent bo'lmagan WRITE/
    EXECUTE qadam (masalan xabar yuborish) tasdiqdan keyingi resume'da
    IKKINCHI marta bajarilib qolardi. Endi har DONE qadam shu ustunga
    yoziladi va keyingi `execute_plan()` chaqiruvi ularni QAYTA
    BAJARMAY, faqat natijasini tiklaydi (`core/run_checkpoint.py::
    persist_step_result`/`load_completed_steps`).

    Faqat approval-pauza + resume() ssenariysini qamraydi (Executor
    ikkita batch orasida — TO'LIQ atomik chegara — to'xtaydi); ixtiyoriy
    jarayon-o'rtasida-halokat (batch ICHIDA) qayta tiklashni QAMRAB
    OLMAYDI — bu alohida, kattaroq ish (per-step DB yozuvi bilan bir
    vaqtda commit, Task #57 ruhida)."""

    plan_snapshot: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    """`zet.domain.plan.Plan` (Pydantic)ning `model_dump(mode="json")`
    nusxasi — HIGH #2 audit fixni TO'LIQ yopish uchun MAJBURIY topilma.

    NEGA: `completed_steps` (yuqorida) o'zi YETARLI EMAS edi — sinash
    chog'ida aniqlandi: `RunRecord.plan` HECH QACHON hech qanday DB
    ustuniga yozilmagan (pastdagi `plan: Mapped[Plan | None] =
    relationship(...)` — bu `db/models/run.py::Plan`/`Step` ORM
    jadvallariga, ular hech qachon to'ldirilmaydi, B1 audit'da
    tasdiqlangan). Natija: real protsess restart'idan keyin
    `load_pending_runs()` `RunRecord(plan=None)` tiklardi va
    `Orchestrator.resume()` DARHOL `OrchestratorError("Reja mavjud
    emas")` bilan yiqilardi — `completed_steps` checkpoint'i hech qachon
    ISHLATILMAS EDI, chunki `resume()`ning o'ziga yetib bormas edi.

    `Plan`/`PlanStep` frozen Pydantic BaseModel — JSON serializatsiya
    to'g'ridan-to'g'ri, maxsus kod kerak emas."""

    plan: Mapped[Plan | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False
    )

    @property
    def is_autonomous(self) -> bool:
        return self.trigger is not RunTrigger.MANUAL


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rejaning saqlangan nusxasi. Har bir run'da ko'pi bilan bitta reja."""

    __tablename__ = "plan"
    __table_args__ = (UniqueConstraint("run_id", name="one_plan_per_run"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Planner qaytargan xom JSON — debug va qayta o'ynatish uchun."""

    run: Mapped[Run] = relationship(back_populates="plan")
    steps: Mapped[list[Step]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="Step.position",
    )


class Step(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Rejaning bitta qadami."""

    __tablename__ = "step"
    __table_args__ = (
        UniqueConstraint("plan_id", "position", name="unique_position_per_plan"),
        CheckConstraint("attempt >= 0", name="attempt_non_negative"),
        Index("ix_step_plan_status", "plan_id", "status"),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plan.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)

    tool_name: Mapped[str | None] = mapped_column(String(64), default=None)
    agent_name: Mapped[str | None] = mapped_column(String(64), default=None)
    permission_required: Mapped[PermissionLevel] = mapped_column(default=PermissionLevel.READ)
    trust_context: Mapped[TrustLevel] = mapped_column(default=TrustLevel.OWNER)
    """Qadamning kirish konteksti qayerdan kelgani — A-05 qarori shunga tayanadi."""

    expected_outcome: Mapped[str | None] = mapped_column(Text, default=None)
    depends_on: Mapped[list[str]] = mapped_column(default=list)
    """Oldingi qadamlarning `position` qiymatlari (DAG qirralari)."""

    status: Mapped[StepStatus] = mapped_column(default=StepStatus.PENDING)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)

    plan: Mapped[Plan] = relationship(back_populates="steps")
