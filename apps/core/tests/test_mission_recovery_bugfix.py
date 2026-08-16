"""JB-11 BUG FIX — `build_orchestrator_for_session` regressiya testi.

MUAMMO (JB-11 auditi ochib bergan, avvalgi JB-10 e'lonini yolg'onga
chiqargan): `api/app.py`ning mission-recovery startup kodi
`get_orchestrator()`ni FastAPI DI konteksti TASHQARISIDA (`lifespan()`
ichida) bare chaqirardi. `get_orchestrator` HAR bir parametrni
`Depends(get_xxx)` bilan default qiladi — bare chaqiruvda `settings`
parametri `Depends`ning O'ZIGA bog'lanadi, keyingi `settings.run_max_usd`
o'qish `AttributeError` beradi. Bu xato `except Exception:
log.warning(...)` bilan JIMGINA yutilardi — ya'ni JB-10'dan beri
Mission restart recovery HECH QACHON haqiqatda ishlamagan (faqat log
darajasida "muvaffaqiyatsiz" ko'rinardi, aniq sabab yo'q edi).

Bu testlar `build_orchestrator_for_session()` (yangi, FastAPI DI'siz
qo'lda-qurish yordamchisi) HAQIQATDA ishlashini — Telegram bilan bir
xil naqsh, lekin endi qayta ishlatiladigan — isbotlaydi. Fake emas:
haqiqiy `deps.py` singleton'lari bilan.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.api.deps import (
    build_mission_engine_for_session,
    build_orchestrator_for_session,
    get_approval_service,
)
from zet.config import get_settings
from zet.core.mission import Mission, MissionEngine
from zet.core.mission_recovery import load_incomplete_missions
from zet.core.mission_repository import MissionRepository
from zet.core.orchestrator import Orchestrator
from zet.db.models import Owner
from zet.domain.enums import MissionStatus


class TestBuildOrchestratorForSession:
    """Asosiy regressiya dalili: bu funksiya `AttributeError` bermaydi."""

    async def test_returns_real_orchestrator_without_raising(
        self, session: AsyncSession
    ) -> None:
        settings = get_settings()

        # ESKI (buzuq) kod: `get_orchestrator()` — bu yerda `AttributeError`
        # berardi. YANGI kod — real Settings obyekti bilan, xatosiz.
        orchestrator = await build_orchestrator_for_session(session, settings)

        assert isinstance(orchestrator, Orchestrator)
        # Haqiqatdan ham ishlaydigan komponent — `.tool_registry` mavjud
        # va bo'sh emas (JB-4 tool-scoping mission.py'da shundan foydalanadi).
        assert orchestrator.tool_registry.tool_names()

    async def test_can_build_mission_engine_from_it(self, session: AsyncSession) -> None:
        """To'liq zanjir: Orchestrator → MissionEngine — `app.py`dagi
        `_mission_engine_factory` bilan AYNAN bir xil."""
        settings = get_settings()
        orchestrator = await build_orchestrator_for_session(session, settings)

        engine = await build_mission_engine_for_session(
            session, orchestrator, get_approval_service()
        )

        assert isinstance(engine, MissionEngine)


class TestRealMissionRecoveryEndToEnd:
    """`load_incomplete_missions` — HAQIQIY (fake emas) factory bilan.

    JB-10'ning `test_mission_recovery.py`dagi testlari FAKE MissionEngine
    stub'idan foydalanadi — bu aynan `build_orchestrator_for_session`
    bug'ini USHLAY OLMAGAN edi (fake hech qachon `settings.run_max_usd`ni
    o'qimaydi). Bu test `app.py`ning HAQIQIY kodini takrorlaydi.
    """

    async def test_incomplete_mission_resumed_via_real_factory_chain(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # MUHIM: `build_mission_engine_for_session` (production kodi)
        # o'zining owner'ini `settings.owner_id` orqali (GLOBAL, yagona
        # ega — bu tizim bir-egali arxitektura) hal qiladi — `owner`
        # fixture'ning tasodifiy external_id'siga EMAS. Mission ham shu
        # AYNAN owner ostida yaratilishi kerak — aks holda ikkita HAR
        # XIL owner qatori paydo bo'lib, `MissionNotFoundError` beradi
        # (owner-scoped query — V-14).
        from zet.db.bootstrap import get_or_create_owner

        settings = get_settings()
        prod_owner = await get_or_create_owner(session, external_id=settings.owner_id)

        repo = MissionRepository(session, owner_id=prod_owner.id)
        pending = await repo.create(
            Mission(owner_id=prod_owner.id, objective="noyob-test-maqsad-jb11-bugfix")
        )
        for s in (
            MissionStatus.UNDERSTANDING,
            MissionStatus.DISCOVERING,
            MissionStatus.PLANNING,
        ):
            await repo.set_status(pending.id, s)
        await session.commit()

        async def _mission_engine_factory(sess: AsyncSession) -> MissionEngine:
            # `app.py`dagi `_mission_engine_factory` bilan SO'ZMA-SO'Z bir xil.
            orch = await build_orchestrator_for_session(sess, settings)
            return await build_mission_engine_for_session(
                sess, orch, get_approval_service()
            )

        n = await load_incomplete_missions(
            session_factory,
            _mission_engine_factory,
            owner_external_id=settings.owner_id,
        )

        assert n == 1

        # Spawn qilingan fon task tugashini kutamiz (haqiqiy LLM/tool
        # chaqiruvlari yo'q — FakeProvider orqaga moslik, capability
        # topilmasa mission FAILED/CANCELLED bo'lishi ham "resume ishladi"
        # degani, MUHIMI: hech qanday AttributeError chiqmadi).
        for _ in range(50):
            await asyncio.sleep(0.05)
            async with session_factory() as check_session:
                fresh_repo = MissionRepository(check_session, owner_id=prod_owner.id)
                fresh = await fresh_repo.get(pending.id)
                if fresh.status != MissionStatus.PLANNING:
                    break
        else:
            fresh = await MissionRepository(session, owner_id=prod_owner.id).get(pending.id)

        # Spawn qilingan fon task'ning `finally: release_claim(...)`
        # qadami hali tugamagan bo'lishi mumkin (status allaqachon
        # o'zgargan, lekin claim bo'shatish keyingi session_scope
        # chaqiruvi). Test funksiyasi tugab, `engine` fixture
        # dispose() qilinishidan OLDIN uni kutamiz — aks holda
        # "connection deleted before being closed" ogohlantirishi
        # (test gigienasi, HAQIQIY xato emas).
        from zet.core import mission_recovery as _mr_module

        pending_tasks = [t for t in _mr_module._active_resume_tasks if not t.done()]
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        # KRITIK DALIL: mission PLANNING'da MUZLAB QOLMADI — oldinga
        # siljidi (COMPLETED/FAILED/WAITING_APPROVAL — istalgani, faqat
        # "hech narsa bo'lmadi" emas). Bu — `AttributeError` endi
        # chiqmayotganining bevosita isboti.
        assert fresh.status != MissionStatus.PLANNING


def _unused() -> uuid.UUID:  # pragma: no cover — faqat import tekshiruvi uchun
    return uuid.uuid4()
