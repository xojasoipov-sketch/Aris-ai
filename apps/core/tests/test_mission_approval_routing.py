"""Mission-level approval marshrutlash testlari (JB-12).

AUDIT TOPILMASI (HIGH funksional bug): Telegram `_approval_runner`
(`api/deps.py`) mission-level tasdiqlarni (`request_approval(run_id=
mission.id, mission_id=mission.id)` orqali yozilgan) HECH TEKSHIRMASDAN
klassik `orchestrator.approve()`/`.resume()` yo'liga yuborardi —
`RunStore.get(mission_id)` esa mission.id'ni HECH QACHON topolmasdi
(`RunNotFoundError`), natijada Telegram'da ✅/❌ bosilganda foydalanuvchi
umumiy "Xato: ..." xabarini ko'rardi, mission esa abadiy WAITING_APPROVAL
holatida qolib ketardi. Bir xil so'rov REST orqali esa TO'G'RI ishlardi
(`api/routes/approvals.py::approve()` allaqachon mission_id tarmoqlanishiga
ega edi) — lekin uning REJECT egizagi xuddi shu klassdagi bug'ga ega edi
(hech qanday tarmoqlanish yo'q edi).

Bu testlar HAQIQIY DB + HAQIQIY MissionEngine/ApprovalService bilan —
mock emas — ikkala yo'l (Telegram, REST) endi mission-level approve/reject'ni
TO'G'RI qayta ishlashini isbotlaydi.

MUHIM (JB-11'da bir marta topilgan, bu yerda ham amal qiladi):
`build_mission_engine_for_session()`/`build_orchestrator_for_session()`
o'zining owner'ini `settings.owner_id` orqali (GLOBAL, yagona-egali
arxitektura) hal qiladi — pytest `owner` fixture'ning tasodifiy
`external_id`'siga EMAS. Shuning uchun test mission'lari HAQIQIY
production owner (`get_or_create_owner(session, external_id=settings.
owner_id)`) ostida yaratiladi.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.core.mission import Mission, MissionEngine
from zet.core.mission_repository import MissionRepository
from zet.db.bootstrap import get_or_create_owner
from zet.db.models import Owner
from zet.domain.enums import MissionStatus
from zet.security.approvals import ApprovalService


async def _mission_awaiting_approval(
    session: AsyncSession, prod_owner: Owner, approvals: ApprovalService, orchestrator: Any
) -> tuple[MissionRepository, Mission]:
    """Haqiqiy WAITING_APPROVAL mission'ni tayyorlaydi (real DB yozuvi bilan,
    PRODUCTION owner ostida — `build_mission_engine_for_session` shuni kutadi)."""
    repo = MissionRepository(session, owner_id=prod_owner.id)
    engine = MissionEngine(
        repository=repo,
        capability_registry=object(),  # type: ignore[arg-type]
        context_engine=object(),  # type: ignore[arg-type]
        planner=object(),  # type: ignore[arg-type]
        orchestrator=orchestrator,
        approvals=approvals,
    )
    mission = await repo.create(
        Mission(owner_id=prod_owner.id, objective="approval routing test")
    )
    for s in (MissionStatus.UNDERSTANDING, MissionStatus.DISCOVERING, MissionStatus.PLANNING):
        await repo.set_status(mission.id, s)
    mission = await repo.get(mission.id)
    mission = await engine.request_approval(mission)
    await session.commit()
    assert mission.status == MissionStatus.WAITING_APPROVAL
    return repo, mission


class TestTelegramApprovalRunnerMissionLevel:
    """`_approval_runner` (Telegram) — mission-level approve/reject."""

    async def test_approve_resumes_mission_not_generic_error(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        monkeypatch: Any,
    ) -> None:
        import zet.api.deps as deps

        monkeypatch.setattr(deps, "get_session_factory", lambda: session_factory)
        deps.get_telegram_bot.cache_clear()

        approvals = deps.get_approval_service()
        settings = deps.get_settings()
        prod_owner = await get_or_create_owner(session, external_id=settings.owner_id)
        orchestrator = await deps.build_orchestrator_for_session(session, settings)
        repo, mission = await _mission_awaiting_approval(
            session, prod_owner, approvals, orchestrator
        )

        bot = deps.get_telegram_bot()
        approval_runner = bot.handler._ctx.approval_runner
        assert approval_runner is not None

        result = await approval_runner("approve", str(mission.id))

        # KRITIK DALIL: eski xatti-harakatda bu "Xato: ..." bo'lardi.
        assert "Xato:" not in result.text
        assert result.run_status != "waiting_approval"

        fresh = await repo.get(mission.id)
        assert fresh.status != MissionStatus.WAITING_APPROVAL

    async def test_reject_cancels_mission_not_generic_error(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        monkeypatch: Any,
    ) -> None:
        import zet.api.deps as deps

        monkeypatch.setattr(deps, "get_session_factory", lambda: session_factory)
        deps.get_telegram_bot.cache_clear()

        approvals = deps.get_approval_service()
        settings = deps.get_settings()
        prod_owner = await get_or_create_owner(session, external_id=settings.owner_id)
        orchestrator = await deps.build_orchestrator_for_session(session, settings)
        repo, mission = await _mission_awaiting_approval(
            session, prod_owner, approvals, orchestrator
        )

        bot = deps.get_telegram_bot()
        approval_runner = bot.handler._ctx.approval_runner

        result = await approval_runner("reject", str(mission.id))

        assert "Xato:" not in result.text
        fresh = await repo.get(mission.id)
        assert fresh.status == MissionStatus.CANCELLED


class TestRestApprovalsRejectMissionLevel:
    """REST `/approvals/{id}/reject` — mission-level (yangi tuzatilgan bug)."""

    async def test_reject_route_cancels_mission(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        monkeypatch: Any,
    ) -> None:
        import zet.api.routes.approvals as approvals_route
        from zet.api import deps

        monkeypatch.setattr(approvals_route, "get_session_factory", lambda: session_factory)

        approvals = ApprovalService()
        settings = deps.get_settings()
        prod_owner = await get_or_create_owner(session, external_id=settings.owner_id)
        orchestrator = await deps.build_orchestrator_for_session(session, settings)
        orchestrator._approvals = approvals  # type: ignore[attr-defined]
        repo, mission = await _mission_awaiting_approval(
            session, prod_owner, approvals, orchestrator
        )

        pending = approvals.pending_for_run(mission.id)
        assert len(pending) == 1
        approval_id = pending[0].id

        body = approvals_route.ApprovalDecisionRequest(note="Kerak emas")
        response = await approvals_route.reject(str(approval_id), body, orchestrator)

        assert response.run_status == "cancelled"
        fresh = await repo.get(mission.id)
        assert fresh.status == MissionStatus.CANCELLED
