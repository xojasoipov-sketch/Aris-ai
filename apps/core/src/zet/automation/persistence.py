"""Avtomatlashtirish holatini saqlash va tiklash (Z48.2).

NEGA KERAK BO'LDI.

`AutomationEngine` `lru_cache` singleton — ya'ni TO'LIQ XOTIRADA.
Ega TIZIM retseptini yoqsa (masalan T06 "Kunlik puls"), u ishlaydi,
lekin konteyner qayta ishga tushishi bilan jimgina yo'qoladi. Railway
redeploy yetarli.

Bu soxta tugmadan ham yomonroq: soxta tugma darhol ko'rinadi, bu esa
bir necha kun ISHLAYDI va keyin sababsiz to'xtaydi — ega buni faqat
hisobot kelmaganda sezadi.

FAIL-OPEN. Baza yo'q yoki yiqilgan bo'lsa ZET baribir ishga tushadi:
saqlash ham, tiklash ham xatoni yutadi va faqat log yozadi. Sabab —
avtomatlashtirish ZET'ning YADROSI emas: uning tufayli butun tizim
ishga tushmay qolishi ancha yomonroq bo'lardi.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.automation.engine import AutomationEngine
from zet.automation.scheduler import ScheduleRule
from zet.automation.triggers import EventTrigger
from zet.automation.watcher import WatchRule
from zet.db.models.automation import AutomationState
from zet.db.session import session_scope

log = structlog.get_logger(__name__)


def snapshot(engine: AutomationEngine) -> dict[str, list[dict[str, Any]]]:
    """Dvigatelning hozirgi holatini JSON'ga aylantiradi.

    `mode="json"` MAJBURIY: qoidalarda `datetime` va `StrEnum`
    maydonlari bor, xom `model_dump()` esa ularni Python obyekti
    sifatida qoldiradi va JSON ustuniga yozishda yiqiladi.
    """
    return {
        "schedules": [r.model_dump(mode="json") for r in engine.scheduler.list_rules()],
        "triggers": [t.model_dump(mode="json") for t in engine.triggers.list_triggers()],
        "watchers": [w.model_dump(mode="json") for w in engine.watchers.list_rules()],
    }


def restore(engine: AutomationEngine, data: dict[str, list[dict[str, Any]]]) -> int:
    """Snapshot'ni dvigatelga qaytaradi. Tiklangan qoidalar sonini beradi.

    Har bir yozuv ALOHIDA tiklanadi: bitta buzuq qator (eski format,
    qo'lda tahrirlangan JSON) qolgan hammasini yo'qotmasligi kerak.
    """
    restored = 0
    for raw in data.get("schedules", []):
        try:
            engine.add_schedule(ScheduleRule.model_validate(raw))
            restored += 1
        except Exception:
            log.warning("automation.restore_skipped", kind="schedule", raw=raw)
    for raw in data.get("triggers", []):
        try:
            engine.add_trigger(EventTrigger.model_validate(raw))
            restored += 1
        except Exception:
            log.warning("automation.restore_skipped", kind="trigger", raw=raw)
    for raw in data.get("watchers", []):
        try:
            engine.add_watch(WatchRule.model_validate(raw))
            restored += 1
        except Exception:
            log.warning("automation.restore_skipped", kind="watcher", raw=raw)
    return restored


class AutomationStore:
    """Bitta egaga tegishli avtomatlashtirish snapshot'i."""

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def _row(self) -> AutomationState | None:
        stmt = select(AutomationState).where(AutomationState.owner_id == self._owner_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def save(self, engine: AutomationEngine) -> None:
        """Butun holatni yozadi (mavjud qatorni almashtiradi)."""
        data = snapshot(engine)
        row = await self._row()
        if row is None:
            row = AutomationState(owner_id=self._owner_id)
            self._session.add(row)
        row.schedules = data["schedules"]
        row.triggers = data["triggers"]
        row.watchers = data["watchers"]
        await self._session.flush()

    async def load(self, engine: AutomationEngine) -> int:
        """Saqlangan holatni dvigatelga tiklaydi."""
        row = await self._row()
        if row is None:
            return 0
        return restore(
            engine,
            {
                "schedules": row.schedules or [],
                "triggers": row.triggers or [],
                "watchers": row.watchers or [],
            },
        )


async def persist_automation(
    engine: AutomationEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_external_id: str,
) -> None:
    """Holatni saqlash — xatoni YUTADI (fail-open).

    Chaqiruvchi route allaqachon qoidani xotiraga qo'shgan va egaga
    muvaffaqiyat qaytargan bo'ladi. Saqlash yiqilgani uchun so'rovni
    500 qilish noto'g'ri: qoida haqiqatan ishlaydi, faqat qayta ishga
    tushishdan omon qolmaydi. Bu log'da ko'rinadi.
    """
    from zet.db.bootstrap import get_or_create_owner

    try:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id=owner_external_id)
            await AutomationStore(session, owner_id=owner.id).save(engine)
    except Exception:
        log.warning("automation.persist_failed")


async def load_automation(
    engine: AutomationEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_external_id: str,
) -> int:
    """Holatni tiklash — xatoni YUTADI (fail-open)."""
    from zet.db.bootstrap import get_or_create_owner

    try:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id=owner_external_id)
            count = await AutomationStore(session, owner_id=owner.id).load(engine)
    except Exception:
        log.warning("automation.load_failed")
        return 0
    else:
        if count:
            log.info("automation.restored", count=count)
        return count


__all__ = [
    "AutomationStore",
    "load_automation",
    "persist_automation",
    "restore",
    "snapshot",
]
