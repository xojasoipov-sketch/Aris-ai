"""Daily Schedule — kunlik avtonom jadval (Bo'lim 12, V-35).

Eganing kunlik hayotiga mos jadval:
    08:00 — Ertalabki brifing (haftalik reja, bugungi vazifalar)
    09:00 — Biznes monitoring (CRM, buyurtmalar, to'lovlar)
    12:00 — SMM monitoring (postlar, statistika, javoblar)
    18:00 — Vazifa hisoboti (bajarilgan, kutilayotgan, muammolar)
    21:00 — Kunlik xulosa (umumiy natijalar, ertangi reja)

Xavfsizlik:
    - Har bir scheduled run: RunTrigger.SCHEDULE
    - Avtonom budjet ulushi: 40% (ADR-0006)
    - Max concurrent: 1 (bir vaqtda bitta scheduled run)

Bog'liq qarorlar:
    V-35 — kunlik avtonom jadval
    ADR-0006 — avtonom budjet ulushi
    Bo'lim 9 — Scheduler
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import structlog

log = structlog.get_logger(__name__)


class ScheduleSlot(StrEnum):
    """Jadval vaqtlari."""

    MORNING_BRIEF = "08:00"
    """Ertalabki brifing."""

    BUSINESS_CHECK = "09:00"
    """Biznes monitoring."""

    SMM_CHECK = "12:00"
    """SMM monitoring."""

    TASK_REPORT = "18:00"
    """Vazifa hisoboti."""

    DAILY_SUMMARY = "21:00"
    """Kunlik xulosa."""


@dataclass(frozen=True)
class DailyTask:
    """Kunlik jadval vazifasi."""

    slot: ScheduleSlot
    """Vaqt sloti."""

    agent_name: str
    """Ishga tushiriladigan agent."""

    command: str
    """Agent buyruq matni."""

    description: str = ""
    """Tavsif."""

    enabled: bool = True
    """Yoqilganmi."""

    cron_expr: str = ""
    """Cron ifodasi."""


# ── Default kunlik jadval ──────────────────────────────────────────

DEFAULT_DAILY_SCHEDULE: list[DailyTask] = [
    DailyTask(
        slot=ScheduleSlot.MORNING_BRIEF,
        agent_name="ceo",
        command="Ertalabki brifing tayyorla: haftalik reja, bugungi vazifalar, muhim eslatmalar",
        description="Ertalabki brifing — kun rejasi",
        cron_expr="0 8 * * *",
    ),
    DailyTask(
        slot=ScheduleSlot.BUSINESS_CHECK,
        agent_name="operations",
        command="Biznes monitoring: CRM holati, yangi buyurtmalar, to'lovlar, muammolar",
        description="Biznes monitoring — CRM va to'lovlar",
        cron_expr="0 9 * * *",
    ),
    DailyTask(
        slot=ScheduleSlot.SMM_CHECK,
        agent_name="smm",
        command="SMM monitoring: postlar statistikasi, javob kerak bo'lgan xabarlar, engagement",
        description="SMM monitoring — ijtimoiy tarmoqlar",
        cron_expr="0 12 * * *",
    ),
    DailyTask(
        slot=ScheduleSlot.TASK_REPORT,
        agent_name="operations",
        command="Vazifa hisoboti: bajarilganlar, kutilayotganlar, muammolar, bloklovchilar",
        description="Vazifa hisoboti — kun davomida bajarilgan ishlar",
        cron_expr="0 18 * * *",
    ),
    DailyTask(
        slot=ScheduleSlot.DAILY_SUMMARY,
        agent_name="ceo",
        command="Kunlik xulosa: umumiy natijalar, xarajatlar, ertangi reja, muhim masalalar",
        description="Kunlik xulosa — kun yakunlari",
        cron_expr="0 21 * * *",
    ),
]


@dataclass
class DailyScheduleManager:
    """Kunlik jadval boshqaruvchisi.

    Default jadvalni saqlaydi va boshqaradi.
    Produksiyada Scheduler (Bo'lim 9) bilan integratsiya qilinadi.
    """

    tasks: list[DailyTask] = field(default_factory=lambda: list(DEFAULT_DAILY_SCHEDULE))
    """Joriy jadval vazifalari."""

    def get_task(self, slot: ScheduleSlot) -> DailyTask | None:
        """Belgilangan vaqt uchun vazifa olish."""
        for task in self.tasks:
            if task.slot == slot:
                return task
        return None

    def list_enabled(self) -> list[DailyTask]:
        """Yoqilgan vazifalar."""
        return [t for t in self.tasks if t.enabled]

    def list_all(self) -> list[DailyTask]:
        """Barcha vazifalar."""
        return list(self.tasks)

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        return {
            "total": len(self.tasks),
            "enabled": sum(1 for t in self.tasks if t.enabled),
            "disabled": sum(1 for t in self.tasks if not t.enabled),
        }
