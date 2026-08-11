"""Event Triggerlar — hodisaga asoslangan avtomatlashtirish (Bo'lim 9).

Triggerlar tashqi hodisalarga javob beradi:
    - WEBHOOK — tashqi xizmatdan HTTP callback
    - SCHEDULE — vaqt asosida (Scheduler bilan birgalikda)
    - DEVICE — qurilma hodisasi (masalan: kamera harakat aniqladi)
    - BUDGET — budjet chegarasi o'zgarganda
    - SYSTEM — tizim hodisasi (masalan: xatolik, sog'liq tekshiruvi)

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    V-26 — RunTrigger (qanday boshlanganini kuzatish)
    A-07 — tormozlar
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class TriggerType(StrEnum):
    """Trigger turi."""

    WEBHOOK = "webhook"
    """Tashqi HTTP callback."""

    SCHEDULE = "schedule"
    """Vaqt asosida (cron)."""

    DEVICE = "device"
    """Qurilma hodisasi."""

    BUDGET = "budget"
    """Budjet chegarasi."""

    SYSTEM = "system"
    """Tizim hodisasi."""


class TriggerCondition(BaseModel, frozen=True):
    """Trigger sharti — qachon ishga tushishi kerak.

    Oddiy key-operator-value sharti.
    Masalan: event_type == 'motion_detected' AND camera_id == 'cam1'
    """

    field: str
    """Tekshiriladigan maydon (masalan: 'event_type', 'camera_id')."""

    operator: str = "eq"
    """Taqqoslash operatori: 'eq', 'ne', 'contains', 'gt', 'lt'."""

    value: str = ""
    """Kutilayotgan qiymat."""

    def evaluate(self, data: dict[str, str]) -> bool:
        """Shartni tekshirish.

        Args:
            data: Hodisa ma'lumotlari

        Returns:
            True agar shart bajarilsa
        """
        actual = data.get(self.field, "")
        if self.operator == "eq":
            return actual == self.value
        if self.operator == "ne":
            return actual != self.value
        if self.operator == "contains":
            return self.value in actual
        if self.operator == "gt":
            try:
                return float(actual) > float(self.value)
            except ValueError:
                return False
        if self.operator == "lt":
            try:
                return float(actual) < float(self.value)
            except ValueError:
                return False
        return False


class EventTrigger(BaseModel, frozen=True):
    """Hodisaga asoslangan trigger.

    Bir nechta shartlar AND bilan birlashtiriladi.
    Barcha shartlar bajarilsa — agent ishga tushadi.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal trigger ID."""

    name: str = Field(min_length=1, max_length=100)
    """Trigger nomi."""

    trigger_type: TriggerType
    """Trigger turi."""

    agent_name: str = Field(min_length=1)
    """Ishga tushiriladigan agent nomi."""

    conditions: list[TriggerCondition] = Field(default_factory=list)
    """Shartlar ro'yxati (AND bilan birlashtiriladi)."""

    command_template: str = ""
    """Agentga yuboriladigan buyruq shabloni.

    Shablon ichida {event_type}, {camera_id} kabi o'zgaruvchilar ishlatilishi mumkin.
    """

    enabled: bool = True
    """Trigger yoqilganmi."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    fire_count: int = 0
    """Ishga tushishlar soni."""

    max_fires: int | None = None
    """Maksimal ishga tushishlar (None = cheksiz)."""

    cooldown_s: int = 0
    """Minimal vaqt oralig'i (sekundlarda) ikki ishga tushish orasida."""

    last_fired_at: datetime | None = None
    """Oxirgi ishga tushgan vaqt."""

    @property
    def is_active(self) -> bool:
        """Trigger faolmi."""
        if not self.enabled:
            return False
        return not (self.max_fires is not None and self.fire_count >= self.max_fires)

    def matches(self, event_data: dict[str, str]) -> bool:
        """Hodisa triggerni ishga tushiradimi.

        Args:
            event_data: Hodisa ma'lumotlari

        Returns:
            True agar barcha shartlar bajarilsa
        """
        if not self.is_active:
            return False
        if not self.conditions:
            return True  # Shartsiz trigger — har doim ishlaydi
        return all(c.evaluate(event_data) for c in self.conditions)

    def render_command(self, event_data: dict[str, str]) -> str:
        """Buyruq shablonini hodisa ma'lumotlari bilan to'ldirish.

        Args:
            event_data: Hodisa ma'lumotlari

        Returns:
            To'ldirilgan buyruq matni
        """
        if not self.command_template:
            return ""
        result = self.command_template
        for key, value in event_data.items():
            result = result.replace(f"{{{key}}}", value)
        return result


class TriggerRegistry:
    """Trigger registri (in-memory).

    Produksiyada DB bilan almashtiriladi.
    """

    def __init__(self) -> None:
        self._triggers: dict[str, EventTrigger] = {}

    def add(self, trigger: EventTrigger) -> EventTrigger:
        """Yangi trigger qo'shish."""
        self._triggers[trigger.id] = trigger
        log.info(
            "trigger.added",
            id=trigger.id,
            name=trigger.name,
            type=trigger.trigger_type.value,
            agent=trigger.agent_name,
        )
        return trigger

    def get(self, trigger_id: str) -> EventTrigger | None:
        """Trigger olish."""
        return self._triggers.get(trigger_id)

    def list_triggers(self, *, trigger_type: TriggerType | None = None) -> list[EventTrigger]:
        """Triggerlar ro'yxati."""
        if trigger_type is None:
            return list(self._triggers.values())
        return [t for t in self._triggers.values() if t.trigger_type == trigger_type]

    def find_matching(self, event_data: dict[str, str]) -> list[EventTrigger]:
        """Hodisaga mos triggerlarni topish.

        Args:
            event_data: Hodisa ma'lumotlari

        Returns:
            Mos kelgan triggerlar ro'yxati
        """
        return [t for t in self._triggers.values() if t.matches(event_data)]

    def record_fire(self, trigger_id: str) -> EventTrigger | None:
        """Ishga tushish yozuvini qo'shish."""
        old = self._triggers.get(trigger_id)
        if old is None:
            return None
        updated = EventTrigger(
            id=old.id,
            name=old.name,
            trigger_type=old.trigger_type,
            agent_name=old.agent_name,
            conditions=old.conditions,
            command_template=old.command_template,
            enabled=old.enabled,
            created_at=old.created_at,
            fire_count=old.fire_count + 1,
            max_fires=old.max_fires,
            cooldown_s=old.cooldown_s,
            last_fired_at=datetime.now(UTC),
        )
        self._triggers[trigger_id] = updated
        return updated

    def disable(self, trigger_id: str) -> EventTrigger | None:
        """Triggerni o'chirish."""
        old = self._triggers.get(trigger_id)
        if old is None:
            return None
        updated = EventTrigger(
            id=old.id,
            name=old.name,
            trigger_type=old.trigger_type,
            agent_name=old.agent_name,
            conditions=old.conditions,
            command_template=old.command_template,
            enabled=False,
            created_at=old.created_at,
            fire_count=old.fire_count,
            max_fires=old.max_fires,
            cooldown_s=old.cooldown_s,
            last_fired_at=old.last_fired_at,
        )
        self._triggers[trigger_id] = updated
        log.info("trigger.disabled", id=trigger_id)
        return updated

    def remove(self, trigger_id: str) -> bool:
        """Triggerni o'chirish."""
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            log.info("trigger.removed", id=trigger_id)
            return True
        return False

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        triggers = list(self._triggers.values())
        return {
            "total": len(triggers),
            "active": sum(1 for t in triggers if t.is_active),
            "disabled": sum(1 for t in triggers if not t.enabled),
        }
