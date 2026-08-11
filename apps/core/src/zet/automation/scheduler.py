"""Jadval (Scheduler) — cron asosida vaqtli vazifalar (Bo'lim 9).

Har bir ScheduleRule bitta agentni belgilangan vaqtda ishga tushiradi.
Produksiyada APScheduler yoki oddiy asyncio loop bilan ishlatiladi.

Xavfsizlik:
    - Har bir scheduled run: RunTrigger.SCHEDULE (avtonom) → budjet 40% chegara
    - Max intervali: 1 minut (juda tez ishlashni oldini olish)
    - Har bir rule alohida enable/disable qilinadi

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    A-07 — run tormozlari
    ADR-0006 — avtonom budjet ulushi (40%)
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

# Oddiy cron field validatsiyasi (5-field: min hour dom month dow)
_CRON_FIELD = (
    r"(\*(/[0-9]{1,2})?|[0-9]{1,2}(-[0-9]{1,2})?(,[0-9]{1,2}(-[0-9]{1,2})?)*(/[0-9]{1,2})?)"
)
_CRON_PATTERN = re.compile(
    rf"^{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}$"
)


class ScheduleStatus(StrEnum):
    """Jadval holati."""

    ACTIVE = "active"
    """Faol — ishga tushiriladi."""

    PAUSED = "paused"
    """To'xtatilgan — ishga tushmaydi."""

    DISABLED = "disabled"
    """O'chirilgan — qayta tiklanmaguncha ishlamaydi."""


class ScheduleRule(BaseModel, frozen=True):
    """Jadval qoidasi — agentni belgilangan vaqtda ishga tushirish.

    5-field cron formatida: minute hour day_of_month month day_of_week
    Masalan: '0 9 * * 1-5' — har kuni soat 9 da, dushanba-juma

    Maxsus shortcutlar:
        '@hourly'  → '0 * * * *'
        '@daily'   → '0 0 * * *'
        '@weekly'  → '0 0 * * 0'
        '@monthly' → '0 0 1 * *'
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal jadval ID."""

    name: str = Field(min_length=1, max_length=100)
    """Jadval nomi (masalan: 'Kunlik hisobot')."""

    agent_name: str = Field(min_length=1)
    """Ishga tushiriladigan agent nomi."""

    cron_expr: str
    """Cron ifodasi (5-field yoki shortcut)."""

    command: str = ""
    """Agentga yuboriladigan buyruq matni."""

    status: ScheduleStatus = ScheduleStatus.ACTIVE
    """Jadval holati."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    last_run_at: datetime | None = None
    """Oxirgi ishga tushgan vaqt."""

    run_count: int = 0
    """Jami ishga tushishlar soni."""

    max_runs: int | None = None
    """Maksimal ishga tushishlar (None = cheksiz)."""

    @property
    def normalized_cron(self) -> str:
        """Cron ifodani normallash (shortcutlarni ochish)."""
        shortcuts = {
            "@hourly": "0 * * * *",
            "@daily": "0 0 * * *",
            "@weekly": "0 0 * * 0",
            "@monthly": "0 0 1 * *",
        }
        return shortcuts.get(self.cron_expr, self.cron_expr)

    @property
    def is_active(self) -> bool:
        """Jadval faolmi."""
        if self.status != ScheduleStatus.ACTIVE:
            return False
        return not (self.max_runs is not None and self.run_count >= self.max_runs)


def validate_cron(expr: str) -> bool:
    """Cron ifodani validatsiya qilish.

    Args:
        expr: Cron ifodasi (5-field yoki shortcut)

    Returns:
        True agar yaroqli bo'lsa
    """
    shortcuts = {"@hourly", "@daily", "@weekly", "@monthly"}
    if expr in shortcuts:
        return True
    return bool(_CRON_PATTERN.match(expr))


class Scheduler:
    """Jadvallar boshqaruvchisi (in-memory).

    Produksiyada DB bilan almashtiriladi.
    """

    def __init__(self) -> None:
        self._rules: dict[str, ScheduleRule] = {}

    def add_rule(self, rule: ScheduleRule) -> ScheduleRule:
        """Yangi jadval qoidasi qo'shish.

        Args:
            rule: Jadval qoidasi

        Returns:
            Saqlangan qoida

        Raises:
            ValueError: Cron ifodasi noto'g'ri
        """
        if not validate_cron(rule.cron_expr):
            msg = f"Noto'g'ri cron ifodasi: '{rule.cron_expr}'"
            raise ValueError(msg)

        self._rules[rule.id] = rule
        log.info(
            "schedule.added",
            id=rule.id,
            name=rule.name,
            agent=rule.agent_name,
            cron=rule.normalized_cron,
        )
        return rule

    def get_rule(self, rule_id: str) -> ScheduleRule | None:
        """Jadval qoidasini olish."""
        return self._rules.get(rule_id)

    def list_rules(self, *, status: ScheduleStatus | None = None) -> list[ScheduleRule]:
        """Barcha jadval qoidalari."""
        if status is None:
            return list(self._rules.values())
        return [r for r in self._rules.values() if r.status == status]

    def pause_rule(self, rule_id: str) -> ScheduleRule | None:
        """Jadval qoidasini to'xtatish."""
        old = self._rules.get(rule_id)
        if old is None:
            return None
        updated = ScheduleRule(
            id=old.id,
            name=old.name,
            agent_name=old.agent_name,
            cron_expr=old.cron_expr,
            command=old.command,
            status=ScheduleStatus.PAUSED,
            created_at=old.created_at,
            last_run_at=old.last_run_at,
            run_count=old.run_count,
            max_runs=old.max_runs,
        )
        self._rules[rule_id] = updated
        log.info("schedule.paused", id=rule_id)
        return updated

    def resume_rule(self, rule_id: str) -> ScheduleRule | None:
        """Jadval qoidasini qayta boshlash."""
        old = self._rules.get(rule_id)
        if old is None:
            return None
        updated = ScheduleRule(
            id=old.id,
            name=old.name,
            agent_name=old.agent_name,
            cron_expr=old.cron_expr,
            command=old.command,
            status=ScheduleStatus.ACTIVE,
            created_at=old.created_at,
            last_run_at=old.last_run_at,
            run_count=old.run_count,
            max_runs=old.max_runs,
        )
        self._rules[rule_id] = updated
        log.info("schedule.resumed", id=rule_id)
        return updated

    def record_run(self, rule_id: str) -> ScheduleRule | None:
        """Ishga tushish yozuvini qo'shish (run_count++, last_run_at yangilash)."""
        old = self._rules.get(rule_id)
        if old is None:
            return None
        updated = ScheduleRule(
            id=old.id,
            name=old.name,
            agent_name=old.agent_name,
            cron_expr=old.cron_expr,
            command=old.command,
            status=old.status,
            created_at=old.created_at,
            last_run_at=datetime.now(UTC),
            run_count=old.run_count + 1,
            max_runs=old.max_runs,
        )
        self._rules[rule_id] = updated
        return updated

    def remove_rule(self, rule_id: str) -> bool:
        """Jadval qoidasini o'chirish."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            log.info("schedule.removed", id=rule_id)
            return True
        return False

    @property
    def active_rules(self) -> list[ScheduleRule]:
        """Faol qoidalar."""
        return [r for r in self._rules.values() if r.is_active]

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        rules = list(self._rules.values())
        return {
            "total": len(rules),
            "active": sum(1 for r in rules if r.status == ScheduleStatus.ACTIVE),
            "paused": sum(1 for r in rules if r.status == ScheduleStatus.PAUSED),
            "disabled": sum(1 for r in rules if r.status == ScheduleStatus.DISABLED),
        }
