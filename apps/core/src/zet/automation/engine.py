"""Automation Engine — markaziy avtomatlashtirish dvigatel (Bo'lim 9).

Scheduler, Trigger, Watcher va Workflow komponentlarini birlashtiradi.
Hodisalarni qabul qiladi va mos triggerlarni ishga tushiradi.

Agentning "uyg'onish" xususiyatlari (yangi zip) shu yerda uchrashadi:
    1. Vaqt      → `Scheduler` (cron)
    2. Xodisa    → `TriggerRegistry` (webhook / tashqi hodisa)
    3. Kuzatuv   → `WatcherRegistry` (metrikani o'zi o'lchaydi)
    4. Navbat    → `TriggerType.AGENT_HANDOFF` (agent tugagach keyingisi)
    5. Mustaqillik → `automation/goal.py` (maqsad tsikli)

Watcher ham, handoff ham oxir-oqibat `AutomationEvent` chiqaradi va
`process_event()` dan o'tadi — ya'ni beshta xususiyat uchun bitta
xavfsizlik yo'li bor, beshta emas.

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

import structlog

from zet.automation.events import AutomationAction, AutomationEvent
from zet.automation.scheduler import Scheduler, ScheduleRule
from zet.automation.triggers import EventTrigger, TriggerRegistry
from zet.automation.watcher import MetricRegistry, WatcherRegistry, WatchRule
from zet.automation.workflow import WorkflowChain, WorkflowRunner, WorkflowStep

log = structlog.get_logger(__name__)


class AutomationEngine:
    """Markaziy avtomatlashtirish dvigatel.

    Komponentlar: Scheduler + TriggerRegistry + WorkflowRunner
    Hodisalarni qabul qiladi, mos triggerlarni topadi, amallar qaytaradi.
    """

    def __init__(self) -> None:
        self.scheduler = Scheduler()
        self.triggers = TriggerRegistry()
        self.workflows = WorkflowRunner()
        self.watchers = WatcherRegistry()
        self.metrics = MetricRegistry()
        self._event_log: list[AutomationEvent] = []

    def add_schedule(self, rule: ScheduleRule) -> ScheduleRule:
        """Jadval qoidasi qo'shish."""
        return self.scheduler.add_rule(rule)

    def add_trigger(self, trigger: EventTrigger) -> EventTrigger:
        """Trigger qo'shish."""
        return self.triggers.add(trigger)

    def add_watch(self, rule: WatchRule) -> WatchRule:
        """Kuzatuv qoidasi qo'shish (3-xususiyat)."""
        return self.watchers.add(rule)

    async def poll_watchers(self) -> list[AutomationAction]:
        """Barcha kuzatuv qoidalarini o'lchash va signal bergani uchun amal qaytarish.

        Watcher hodisa ishlab chiqaradi, hodisa esa oddiy trigger yo'lidan
        o'tadi — shu sabab watcher uchun alohida xavfsizlik yo'li yo'q.
        """
        actions: list[AutomationAction] = []
        for event in await self.watchers.poll(self.metrics):
            actions.extend(self.process_event(event))
        return actions

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

        matching = self.triggers.find_matching(event_data, now=event.timestamp)
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
            "watchers": self.watchers.stats,
            "events_processed": {"total": len(self._event_log)},
        }

    @property
    def event_count(self) -> int:
        """Qayta ishlangan hodisalar soni."""
        return len(self._event_log)


__all__ = ["AutomationAction", "AutomationEngine", "AutomationEvent"]
