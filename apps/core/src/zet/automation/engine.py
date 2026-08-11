"""Automation Engine — markaziy avtomatlashtirish dvigatel (Bo'lim 9).

Scheduler, Trigger va Workflow komponentlarini birlashtiradi.
Hodisalarni qabul qiladi va mos triggerlarni ishga tushiradi.

Xavfsizlik:
    - Har bir avtonom run: budjet 40% chegara (ADR-0006)
    - Maxsus RunTrigger (SCHEDULE, WEBHOOK, EVENT) — kuzatish uchun
    - Har bir run uchun A-07 tormozlar (max_steps, timeout, budget)

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    ADR-0006 — avtonom budjet ulushi
    A-07 — run tormozlari
    V-26 — RunTrigger (boshlanish sababi)
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field

from zet.automation.scheduler import Scheduler, ScheduleRule
from zet.automation.triggers import EventTrigger, TriggerRegistry
from zet.automation.workflow import WorkflowChain, WorkflowRunner, WorkflowStep

log = structlog.get_logger(__name__)


class AutomationEvent(BaseModel, frozen=True):
    """Avtomatlashtirish hodisasi.

    Engine ga kiritiladi va mos triggerlar qidiriladi.
    """

    event_type: str = Field(min_length=1)
    """Hodisa turi (masalan: 'motion_detected', 'budget_warning')."""

    source: str = ""
    """Hodisa manbasi (masalan: 'camera.cam1', 'budget.daily')."""

    data: dict[str, str] = Field(default_factory=dict)
    """Hodisa ma'lumotlari (key-value)."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Hodisa vaqti."""


class AutomationAction(BaseModel, frozen=True):
    """Engine chiqishi — bajarilishi kerak bo'lgan harakat.

    Engine haqiqiy agentlarni BAJARMAYDI — faqat nima qilish kerakligini qaytaradi.
    Orchestrator bu amallarni bajaradi.
    """

    agent_name: str
    """Ishga tushiriladigan agent."""

    command: str = ""
    """Agent buyrug'i."""

    trigger_id: str = ""
    """Ishga tushirgan trigger ID."""

    trigger_name: str = ""
    """Trigger nomi (log uchun)."""

    event_type: str = ""
    """Hodisa turi."""


class AutomationEngine:
    """Markaziy avtomatlashtirish dvigatel.

    Komponentlar: Scheduler + TriggerRegistry + WorkflowRunner
    Hodisalarni qabul qiladi, mos triggerlarni topadi, amallar qaytaradi.
    """

    def __init__(self) -> None:
        self.scheduler = Scheduler()
        self.triggers = TriggerRegistry()
        self.workflows = WorkflowRunner()
        self._event_log: list[AutomationEvent] = []

    def add_schedule(self, rule: ScheduleRule) -> ScheduleRule:
        """Jadval qoidasi qo'shish."""
        return self.scheduler.add_rule(rule)

    def add_trigger(self, trigger: EventTrigger) -> EventTrigger:
        """Trigger qo'shish."""
        return self.triggers.add(trigger)

    def create_workflow(
        self,
        *,
        name: str,
        steps: list[WorkflowStep],
        description: str = "",
    ) -> WorkflowChain:
        """Workflow yaratish."""
        return self.workflows.create(name=name, steps=steps, description=description)

    def process_event(self, event: AutomationEvent) -> list[AutomationAction]:
        """Hodisani qayta ishlash — mos triggerlarni topish va amallar qaytarish.

        Args:
            event: Kiritilgan hodisa

        Returns:
            Bajarilishi kerak bo'lgan amallar ro'yxati
        """
        self._event_log.append(event)

        # Hodisa ma'lumotlariga event_type ni qo'shish
        event_data = {"event_type": event.event_type, "source": event.source}
        event_data.update(event.data)

        matching = self.triggers.find_matching(event_data)
        actions: list[AutomationAction] = []

        for trigger in matching:
            command = trigger.render_command(event_data)
            action = AutomationAction(
                agent_name=trigger.agent_name,
                command=command,
                trigger_id=trigger.id,
                trigger_name=trigger.name,
                event_type=event.event_type,
            )
            actions.append(action)
            self.triggers.record_fire(trigger.id)

            log.info(
                "automation.trigger_fired",
                trigger_id=trigger.id,
                trigger_name=trigger.name,
                agent=trigger.agent_name,
                event_type=event.event_type,
            )

        return actions

    def get_due_schedules(self) -> list[ScheduleRule]:
        """Vaqti kelgan jadval qoidalarini olish.

        Haqiqiy cron matching produksiyada APScheduler bilan qilinadi.
        Bu metod faqat faol qoidalarni qaytaradi (Orchestrator uchun).
        """
        return self.scheduler.active_rules

    @property
    def stats(self) -> dict[str, dict[str, int]]:
        """Umumiy statistika."""
        return {
            "schedules": self.scheduler.stats,
            "triggers": self.triggers.stats,
            "workflows": self.workflows.stats,
            "events_processed": {"total": len(self._event_log)},
        }

    @property
    def event_count(self) -> int:
        """Qayta ishlangan hodisalar soni."""
        return len(self._event_log)
