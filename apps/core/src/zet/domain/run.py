"""Run holati domen modeli.

DB `run` jadvalidagi holatni domen qatlamida ifodalash —
Orchestrator va API qatlami shu orqali ishlaydi.

Bog'liq qarorlar:
    A-01 — davomli holat mashinasi
    A-07 — run tormozlari (depth, budget, timeout)
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from zet.domain.command import Intent
from zet.domain.enums import RunStatus, RunTrigger, TaskClass
from zet.domain.plan import Plan


class RunLimits(BaseModel, frozen=True):
    """Run uchun chegaralar (A-07)."""

    max_steps: int = Field(default=20, ge=1)
    max_depth: int = Field(default=3, ge=1)
    timeout_s: int = Field(default=600, ge=1)
    budget_usd: float = Field(default=0.10, ge=0.0)


class RunState(BaseModel, frozen=True):
    """Run'ning joriy holati — Orchestrator va API uchun snapshot."""

    status: RunStatus = RunStatus.PENDING
    trigger: RunTrigger = RunTrigger.MANUAL
    task_class: TaskClass | None = None

    command_text: str = ""
    intent: Intent | None = None
    plan: Plan | None = None

    depth: int = Field(default=0, ge=0)
    spent_usd: float = Field(default=0.0, ge=0.0)
    limits: RunLimits = Field(default_factory=RunLimits)

    trace_id: str = ""
    verified_ok: bool | None = None
    error: str | None = None
    result_summary: str | None = None

    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    @property
    def is_autonomous(self) -> bool:
        return self.trigger is not RunTrigger.MANUAL

    @property
    def budget_remaining_usd(self) -> float:
        return max(0.0, self.limits.budget_usd - self.spent_usd)

    @property
    def budget_usage_ratio(self) -> float:
        if self.limits.budget_usd <= 0:
            return 1.0
        return self.spent_usd / self.limits.budget_usd
