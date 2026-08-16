"""Approval TTL sweep testlari (JB-12 §27).

AUDIT TOPILMASI: `ApprovalService.expire_all_pending()` to'g'ri yozilgan,
lekin HECH QAYERDAN (daemon/tick/startup) chaqirilmasdi — modul
docstring'ining "Fail-closed: TTL tugasa → EXPIRED → run CANCELLED"
da'vosi HAQIQATDA hech qanday ishlayotgan kod yo'li orqali
ta'minlanmagan edi. Bu testlar `sweep_expired_approvals()`ni (yangi
chaqiruvchi, core/recovery.py) HAQIQIY vaqt/mission bilan tekshiradi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from zet.core.approval_expiry import sweep_expired_approvals
from zet.core.mission import Mission, MissionEngine
from zet.core.mission_repository import MissionRepository
from zet.db.models import Owner
from zet.domain.enums import MissionStatus, PermissionLevel
from zet.security.approvals import ApprovalService


class TestSweepExpiredApprovals:
    async def test_expired_pending_becomes_expired(self) -> None:
        approvals = ApprovalService(ttl_minutes=30)
        past = datetime.now(UTC) - timedelta(hours=1)
        req = approvals.request_approval(
            run_id=__import__("uuid").uuid4(),
            reason="test",
            requested_permission=PermissionLevel.WRITE,
            now=past,
        )

        count = await sweep_expired_approvals(approvals)

        assert count == 1
        assert approvals.get(req.id).status.value == "expired"

    async def test_non_expired_pending_untouched(self) -> None:
        approvals = ApprovalService(ttl_minutes=30)
        req = approvals.request_approval(
            run_id=__import__("uuid").uuid4(),
            reason="test",
            requested_permission=PermissionLevel.WRITE,
        )

        count = await sweep_expired_approvals(approvals)

        assert count == 0
        assert approvals.get(req.id).status.value == "pending"

    async def test_no_pending_returns_zero(self) -> None:
        approvals = ApprovalService(ttl_minutes=30)
        count = await sweep_expired_approvals(approvals)
        assert count == 0

    async def test_mission_level_expiry_cancels_mission(
        self, session: Any, owner: Owner, session_factory: Any
    ) -> None:
        """HAQIQIY DB: mission-level tasdiq muddati tugasa — mission CANCELLED."""
        approvals = ApprovalService(ttl_minutes=30)
        repo = MissionRepository(session, owner_id=owner.id)
        mission = await repo.create(Mission(owner_id=owner.id, objective="expiry test"))
        for s in (MissionStatus.UNDERSTANDING, MissionStatus.DISCOVERING, MissionStatus.PLANNING):
            await repo.set_status(mission.id, s)
        mission = await repo.get(mission.id)

        past = datetime.now(UTC) - timedelta(hours=1)
        # `request_approval` ichida `now` parametri o'tgan vaqtga qo'yiladi
        # — TTL'ni orqaga surish uchun (real production'da bu shunchaki
        # vaqt o'tishi bilan sodir bo'ladi).
        req = approvals.request_approval(
            run_id=mission.id,
            mission_id=mission.id,
            reason="risk",
            requested_permission=PermissionLevel.WRITE,
            now=past,
        )
        await repo.update(mission.id, pending_approval_id=req.id)
        await repo.set_status(mission.id, MissionStatus.WAITING_APPROVAL)
        await session.commit()

        async def _mission_engine_factory(sess: Any) -> MissionEngine:
            return MissionEngine(
                repository=MissionRepository(sess, owner_id=owner.id),
                capability_registry=object(),  # type: ignore[arg-type]
                context_engine=object(),  # type: ignore[arg-type]
                planner=object(),  # type: ignore[arg-type]
                orchestrator=object(),  # type: ignore[arg-type]
                approvals=approvals,
            )

        count = await sweep_expired_approvals(
            approvals,
            mission_engine_factory=_mission_engine_factory,
            session_factory=session_factory,
        )

        assert count == 1
        fresh = await repo.get(mission.id)
        assert fresh.status == MissionStatus.CANCELLED

    async def test_run_level_expiry_does_not_crash_without_mission_factory(self) -> None:
        """Run-level (mission_id=None) muddati tugashi — fabrika berilmasa
        ham xavfsiz (faqat EXPIRED, mission-cancel urinilmaydi)."""
        approvals = ApprovalService(ttl_minutes=30)
        past = datetime.now(UTC) - timedelta(hours=1)
        req = approvals.request_approval(
            run_id=__import__("uuid").uuid4(),
            reason="test",
            requested_permission=PermissionLevel.WRITE,
            now=past,
        )

        count = await sweep_expired_approvals(approvals)

        assert count == 1
        assert approvals.get(req.id).status.value == "expired"
