"""Mission restart recovery — JB-10.

MUAMMO (JB-9 auditi ochib bergan gap): `mission` jadvali to'liq
DB-persistent, `MissionRepository` to'liq CRUD bilan, lekin PROCESS
QAYTA ISHGA TUSHGANDAN KEYIN hech kim mavjud non-terminal mission'larni
qayta yuritmaydi. Natija: EXECUTING/PLANNING/DISCOVERING/VERIFYING/
RECOVERING/UNDERSTANDING holatida "muzlab qolgan" mission'lar. Ular DB'da
bor, `GET /api/v1/missions/{id}` orqali ko'rinadi, lekin hech qachon
oldinga siljimaydi.

Bu — `load_pending_approvals`/`load_pending_runs` bilan bir xil
darajali gap edi, lekin Mission uchun bajarilmagan.

YECHIM: bu modul — `load_incomplete_missions()` — startup'da (mavjud
`lifespan()` ichida) chaqiriladi va:

    1. `MissionRepository.list(active_only=True)` orqali barcha
       non-terminal (COMPLETED/FAILED/CANCELLED emas) mission'larni
       o'qiydi.
    2. `WAITING_APPROVAL` holatidagilarni O'TKAZIB YUBORADI — ular
       allaqachon mavjud approval oqimi orqali qayta yuritiladi:
       `load_pending_approvals()` xotira ApprovalService'ni tiklaydi,
       foydalanuvchi `/approvals/{id}/approve` chertganda esa
       `mission_engine.run_to_completion(mission.id)` chaqiriladi
       (`api/routes/approvals.py:131`).
    3. Har qolgan mission uchun ALOHIDA asyncio task yaratadi. Task
       yangi DB sessiya ochib, `MissionEngine.run_to_completion(mid)`
       chaqiradi (JB-10'da `run_to_completion` UNDERSTANDING/VERIFYING
       holatlarini ham to'g'ri boshqara olsin deb tuzatildi —
       `mission.py`da).

XAVFSIZLIK QOIDALARI:

    - COMPLETED/FAILED/CANCELLED mission'lar HECH QACHON qayta ishga
      tushirilmaydi (`active_only=True` ularni filtrlab tashlaydi —
      `mission_repository.py:110-115`).
    - Har mission uchun in-process asyncio.Lock (dublikat resumer
      va parallel approval-triggered chaqiriqlar birga ishga
      tushmasin uchun). Multi-worker/multi-pod uchun DB advisory
      lock kerak bo'ladi — bu keyingi JB doirasi (audit halol
      belgilagan).
    - Fail-open: bir mission'ning yiqilishi startup'ni to'xtatmaydi,
      log yoziladi va boshqa mission'lar davom etadi.
    - `_ABSOLUTE_MAX_RESUME` — bir startup'da ko'p mission tiklamaslik
      chegarasi (10000). Kutilmagan buzuq holat yoki test dumidan
      himoya.

TASHRIFCHI TAMOYIL: bu qatlam YANGI Mission YARATMAYDI, yangi
ijro dvigateli emas, RecoveryEngine dublikati emas. U mavjud
`MissionEngine.run_to_completion()`ni CHAQIRADI — barcha xavfsizlik
darvozalari (killswitch, approvals, permissions, RecoveryEngine, memory,
audit) mavjud yo'lidan o'z-o'zidan o'tadi.

Bog'liq qarorlar:
    JB-9 §4 — Mission checkpointing (allaqachon bor)
    JB-10 §3 — Restart recovery
    A-01 — Mission holat mashinasi
    `run_checkpoint.py::load_pending_approvals` — bir xil dizayn naqshi
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.exc import SQLAlchemyError

from zet.db.bootstrap import get_or_create_owner
from zet.db.session import session_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from zet.core.mission import Mission, MissionEngine

log = structlog.get_logger(__name__)

_ABSOLUTE_MAX_RESUME = 10_000
"""Startup'da nechta mission qayta tiklanishi mumkinligi chegarasi —
kutilmagan buzuq holat yoki tegishli bug'dan himoya. Real jonli
tizimlarda odatda 10-100 tartibida non-terminal mission bo'ladi."""


# ── Per-mission in-process lock ───────────────────────────────────
#
# NEGA modul-darajasidagi dict: `load_incomplete_missions` bir marta
# chaqiriladi (startup'da), lekin natijaviy spawn qilingan task'lar
# fon rejimida ishlaydi va ular bilan parallel ravishda foydalanuvchi
# `POST /approvals/{id}/approve` chertsa — mavjud kod ham
# `run_to_completion(mission.id)` chaqiradi (`api/routes/approvals.py:
# 131`). Ikkalasi bir vaqtda bir mission'ni HAYDAB ketishi:
# duplicate side effects, race'lar. Modul-darajasidagi lock bu
# muammoni bitta process ichida yechadi. Multi-pod uchun DB advisory
# lock — kelasi JB.
_mission_locks: dict[uuid.UUID, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(mission_id: uuid.UUID) -> asyncio.Lock:
    """`mission_id`ga mos Lock qaytaradi (yaratilmagan bo'lsa yaratadi)."""
    async with _locks_guard:
        lock = _mission_locks.get(mission_id)
        if lock is None:
            lock = asyncio.Lock()
            _mission_locks[mission_id] = lock
        return lock


async def acquire_mission_lock(mission_id: uuid.UUID) -> asyncio.Lock:
    """API va CLI uchun ham foydalanish uchun umumiy lock accessor.

    JB-10 §33: parallel mission drayvchi'larini oldini oladi (masalan
    resumer va approval endpoint bir vaqtda). `async with` ichida
    ishlatiladi:

        lock = await acquire_mission_lock(mid)
        async with lock:
            await mission_engine.run_to_completion(mid)
    """
    return await _lock_for(mission_id)


# ── Session-factory tipi va callback ───────────────────────────────
MissionEngineFactory = Callable[["AsyncSession"], Awaitable["MissionEngine"]]
"""So'rov chegaralanmagan session bilan MissionEngine quruvchi.

Har mission uchun yangi session ochilishi kerak — request-scoped
`get_mission_orchestrator` DI FastAPI Depends'iga bog'langan va
resumer'da to'g'ridan-to'g'ri ishlatib bo'lmaydi."""


async def _resume_one(
    mission: Mission,
    session_factory: async_sessionmaker[AsyncSession],
    engine_factory: MissionEngineFactory,
) -> None:
    """Bitta mission'ni `run_to_completion` orqali oldinga siljitadi.

    Fail-open: bu task'ning yiqilishi boshqa task'larga ta'sir
    qilmaydi. Har mission'ga o'z lock'i, o'z session'i.
    """
    lock = await acquire_mission_lock(mission.id)
    try:
        async with lock, session_scope(session_factory) as session:
            engine = await engine_factory(session)
            await engine.run_to_completion(mission.id)
        log.info(
            "mission_recovery.resumed",
            mission_id=str(mission.id),
            initial_status=mission.status.value,
        )
    except Exception as exc:
        # Bitta mission yiqilsa boshqalar davom etsin. Xato log'da
        # ko'rinadi va foydalanuvchi HTTP orqali holatni ko'ra oladi.
        log.warning(
            "mission_recovery.resume_failed",
            mission_id=str(mission.id),
            error=str(exc),
        )


async def load_incomplete_missions(
    session_factory: async_sessionmaker[AsyncSession],
    engine_factory: MissionEngineFactory,
    *,
    owner_external_id: str,
) -> int:
    """Startup'da non-terminal mission'larni topib qayta yuritadi.

    Args:
        session_factory: DB sessiya factory (asosiy AsyncSessionMaker).
        engine_factory: har mission uchun `MissionEngine` quruvchi
            (session'ni oladi). Bu `get_mission_orchestrator`ga
            o'xshash, faqat DI Depends'siz.
        owner_external_id: ega tashqi id (mavjud `owner_id` sozlamasi).

    Returns:
        Qayta yuritish uchun spawn qilingan mission'lar soni.

    Fail-open: DB o'qish yiqilsa 0 qaytaradi va startup davom etadi.
    Har mission alohida task, bir-biriga ta'sir qilmaydi. HECH QANDAY
    terminal mission (COMPLETED/FAILED/CANCELLED) qayta tushirilmaydi —
    `MissionRepository.list(active_only=True)` ularni chetlab o'tadi.

    `WAITING_APPROVAL` mission'lar ATAYLAB spawn QILINMAYDI: ular
    allaqachon `load_pending_approvals` + `/approvals/{id}/approve`
    oqimi orqali qayta tiklanadi.
    """
    from zet.core.mission_repository import MissionRepository
    from zet.domain.enums import MissionStatus

    try:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id=owner_external_id)
            repo = MissionRepository(session, owner_id=owner.id)
            missions = await repo.list(active_only=True, limit=_ABSOLUTE_MAX_RESUME)
    except SQLAlchemyError:
        log.warning("mission_recovery.load_failed_db")
        return 0
    except Exception:
        log.warning("mission_recovery.load_failed_unexpected")
        return 0

    if not missions:
        return 0

    # WAITING_APPROVAL — mavjud approval oqimi mas'uliyati.
    # Terminal holatlar (COMPLETED/FAILED/CANCELLED) allaqachon
    # `active_only=True` orqali filtrlangan — bu yerda ikkinchi bor
    # tekshirish shart emas, lekin logga aniq ko'rinsin uchun:
    to_resume = [m for m in missions if m.status != MissionStatus.WAITING_APPROVAL]
    waiting_approval = len(missions) - len(to_resume)

    if not to_resume:
        log.info(
            "mission_recovery.nothing_to_resume",
            total=len(missions),
            waiting_approval=waiting_approval,
        )
        return 0

    log.warning(
        "mission_recovery.spawning_resumes",
        total=len(missions),
        to_resume=len(to_resume),
        waiting_approval=waiting_approval,
    )

    # Task'lar fon rejimida ishga tushadi. Startup ularni KUTMAYDI —
    # bir necha mission'ning har biri sekin bo'lishi mumkin (LLM
    # chaqiruvlari, tool ijrolari), API'ni bloklamaslik kerak.
    #
    # `asyncio.create_task` reference'ini yo'qotmaslik uchun global set:
    # aks holda GC task'larni yig'ib olishi mumkin (Python 3.11+ mashhur
    # naqsh). Task tugagach o'zi discard qiladi.
    for mission in to_resume:
        task = asyncio.create_task(
            _resume_one(mission, session_factory, engine_factory),
            name=f"mission-resume-{mission.id}",
        )
        _active_resume_tasks.add(task)
        task.add_done_callback(_active_resume_tasks.discard)

    return len(to_resume)


# GC'ga tushmasin uchun aktiv resume task'larga havola saqlaymiz.
_active_resume_tasks: set[asyncio.Task[None]] = set()


__all__ = [
    "MissionEngineFactory",
    "acquire_mission_lock",
    "load_incomplete_missions",
]
