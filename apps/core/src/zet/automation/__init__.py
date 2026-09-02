"""Avtomatlashtirish moduli — jadval, trigger, workflow (Bo'lim 9).

Komponentlar:
    - ScheduleRule: cron asosida vaqtli ishga tushirish
    - EventTrigger: hodisaga asoslangan triggerlar
    - WorkflowChain: ketma-ket agent zanjiri
    - AutomationEngine: barchasini boshqaruvchi dvigatel

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    A-07 — tormozlar (har bir run uchun)
    V-32 — majburiy approval (xavfli operatsiyalar)
    ADR-0006 — budjet chegaralari
"""

from zet.automation.cron import is_due
from zet.automation.engine import AutomationEngine
from zet.automation.executor import AgentUnavailableError, WorkflowExecutor, run_agent_command
from zet.automation.scheduler import ScheduleRule, ScheduleStatus
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType
from zet.automation.workflow import WorkflowChain, WorkflowStatus, WorkflowStep

__all__ = [
    "AgentUnavailableError",
    "AutomationEngine",
    "EventTrigger",
    "ScheduleRule",
    "ScheduleStatus",
    "TriggerCondition",
    "TriggerType",
    "WorkflowChain",
    "WorkflowExecutor",
    "WorkflowStatus",
    "WorkflowStep",
    "is_due",
    "run_agent_command",
]
