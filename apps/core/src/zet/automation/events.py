"""Avtomatlashtirish hodisa kontraktlari (Bo'lim 9).

`AutomationEvent` va `AutomationAction` ilgari `engine.py` ichida edi.
Ular alohida modulga ko'chirildi, chunki `watcher.py` hodisa ishlab
chiqaradi va `engine.py` esa watcher'ni so'raydi — bir-birini import
qilsa aylanma bog'liqlik chiqardi.

`engine.py` ikkalasini qayta eksport qiladi, shuning uchun eski
`from zet.automation.engine import AutomationEvent` yozuvlari ishlayveradi.

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    V-26 — RunTrigger (boshlanish sababi)
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AutomationEvent(BaseModel, frozen=True):
    """Avtomatlashtirish hodisasi.

    Engine ga kiritiladi va mos triggerlar qidiriladi.
    """

    event_type: str = Field(min_length=1)
    """Hodisa turi (masalan: 'motion_detected', 'watch.crm.new_leads')."""

    source: str = ""
    """Hodisa manbasi (masalan: 'camera.cam1', 'watcher.a1b2c3')."""

    data: dict[str, str] = Field(default_factory=dict)
    """Hodisa ma'lumotlari (key-value)."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Hodisa vaqti."""


class AutomationAction(BaseModel, frozen=True):
    """Engine chiqishi — bajarilishi kerak bo'lgan harakat.

    Engine haqiqiy agentlarni BAJARMAYDI — faqat nima qilish kerakligini qaytaradi.
    Chaqiruvchi (route yoki daemon) bu amallarni `run_agent_command()` bilan bajaradi.
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


__all__ = ["AutomationAction", "AutomationEvent"]
