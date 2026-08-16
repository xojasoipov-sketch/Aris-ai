"""Scheduled fire ledger — dublikat rejalashtirilgan ijroni oldini olish (JB-11).

MUAMMO (JB-10 auditi ochib bergan, JB-11 spec'i majburiy qilib qo'ygan):
`AutomationDaemon._last_fired_minute` — in-process dict. JB-10
`hydrate_last_fired_from_rules()` bilan uni `ScheduleRule.last_run_at`
(persistent) qiymatidan tiklashni QISMAN yechdi — bu "process qayta
ishga tushdi, boshqa daqiqada" holatini yopadi. Lekin ikkita HAQIQIY
xavf OCHIQ qolgan edi (JB-10'ning o'zi halol e'lon qilgan):

    1. Bir xil daqiqada process CRASH bo'lib qayta ko'tarilsa (yoki
       deploy paytida eski/yangi process bir lahza parallel ishlasa)
       — `_last_fired_minute` yangi process'da BO'SH, `last_run_at`
       esa faqat `_persist_state()` chaqirilgandan keyin yozilgan
       (fire va persist orasidagi tor oynada race bor).
    2. Kelajakda bir nechta worker/pod ishga tushsa — ular orasida
       HECH QANDAY umumiy holat yo'q.

YECHIM: `scheduled_fire(rule_id, minute_key)` jadvalida UNIQUE
constraint (`db/models/automation.py::ScheduledFire`). Fire qilishdan
OLDIN daemon shu qatorni yozishga urinadi. Muvaffaqiyatli bo'lsa —
HECH KIM bu (rule, daqiqa) juftligini hali da'vo qilmagan, fire
xavfsiz. `IntegrityError` (unique violation) — boshqa process/worker
ALLAQACHON da'vo qilgan, bu chaqiruv JIMGINA o'tkazib yuboriladi.

Bu — Postgres/SQLite'ning o'zi ta'minlaydigan ATOMIK "compare-and-set":
qo'shimcha tashqi lock xizmati (Redis, advisory lock) kerak emas.

Bog'liq qarorlar:
    JB-9/JB-10 — Scheduler/AutomationDaemon integratsiyasi
    JB-11 §10/§11/§28 — Scheduled Mission idempotency
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.bootstrap import get_or_create_owner
from zet.db.models.automation import ScheduledFire
from zet.db.session import session_scope

log = structlog.get_logger(__name__)


async def claim_fire(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    rule_id: str,
    minute_key: str,
) -> bool:
    """Bitta `(rule_id, minute_key)` juftligini atomik da'vo qiladi.

    Chaqiruvchi (`AutomationDaemon`) bu qatorni fire qilishdan OLDIN
    chaqirishi kerak. `False` qaytsa — chaqiruvchi FIRE QILMASLIGI
    kerak (boshqa process/worker allaqachon da'vo qilgan).

    NEGA `flush()` (commit emas): chaqiruvchining tashqi
    `session_scope` bloki committing qiladi — bu funksiya faqat
    joriy tranzaksiya ichida INSERT urinadi va `IntegrityError`ni
    ushlaydi. `flush()` DB'ga yozadi (constraint tekshiruvi shu yerda
    ishga tushadi) lekin commit qilmaydi — chaqiruvchi tashqi bloki
    yakunida commit bo'ladi.

    NEGA `begin_nested()` (SAVEPOINT), `session.rollback()` EMAS:
    chaqiruvchi sessiyada BOSHQA, shu funksiyaga aloqasi bo'lmagan
    ishlangan-lekin-hali-commit-qilinmagan o'zgarishlar bo'lishi
    mumkin (masalan owner yaratish). To'liq `session.rollback()`
    ULARNI HAM yo'q qilib yuborardi. SAVEPOINT faqat SHU muvaffaqiyatsiz
    INSERT urinishini bekor qiladi, sessiyaning qolgan holatini
    tegmasdan qoldiradi.
    """
    try:
        async with session.begin_nested():
            row = ScheduledFire(owner_id=owner_id, rule_id=rule_id, minute_key=minute_key)
            session.add(row)
            await session.flush()
    except IntegrityError:
        # Boshqa process/worker ALLAQACHON shu daqiqada shu qoidani
        # da'vo qilgan — `begin_nested()` bloki avtomatik ravishda
        # faqat SHU savepoint'ni bekor qiladi.
        log.info(
            "scheduled_fire.already_claimed",
            rule_id=rule_id,
            minute_key=minute_key,
        )
        return False
    return True


async def claim_fire_standalone(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner_external_id: str,
    rule_id: str,
    minute_key: str,
) -> bool:
    """`claim_fire()`ning o'z sessiyasini ochadigan versiyasi.

    `AutomationDaemon._run_once`dagi mavjud `session_scope(...)` naqshi
    bilan bir xil — daemon o'z sessiyasini ochib, shu funksiyani
    chaqiradi. Fail-open: DB yetib bo'lmasa `True` qaytadi (ya'ni
    "cheklovsiz fire qilinadi" — eski, JB-11'gacha bo'lgan xatti-harakat;
    dedup — QO'SHIMCHA xavfsizlik, uning yo'qligi tizimni butunlay
    to'xtatmasligi kerak).
    """
    try:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id=owner_external_id)
            return await claim_fire(
                session, owner_id=owner.id, rule_id=rule_id, minute_key=minute_key
            )
    except Exception:
        log.warning("scheduled_fire.claim_failed_fail_open", rule_id=rule_id)
        return True


__all__ = ["claim_fire", "claim_fire_standalone"]
