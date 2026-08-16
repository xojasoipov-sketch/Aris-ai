"""MissionRepository testlari (Bo'lim 2, §2.2).

NEGA. WorkspaceRepository owner-scoping va _fresh/populate_existing
naqshlarini kiritdi; MissionRepository ham xuddi shu qoidalarga amal
qiladi. Bu testlar begona ega o'qib ololmasligini, holat mashinasi
majburiyligini va CASCADE join jadvalga to'g'ri ta'sir qilishini
qulflaydi.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.core.mission import (
    IllegalMissionTransitionError,
    Mission,
    MissionNotFoundError,
)
from zet.core.mission_repository import MissionRepository
from zet.db.base import utcnow
from zet.db.models import Owner
from zet.db.models.run import Run
from zet.domain.enums import MissionStatus, RunTrigger


@pytest.fixture
def repo(session: AsyncSession, owner: Owner) -> MissionRepository:
    return MissionRepository(session, owner_id=owner.id)


async def _make_run(session: AsyncSession, owner: Owner) -> Run:
    run = Run(
        owner_id=owner.id,
        trigger=RunTrigger.MANUAL,
        command_text="test",
        trace_id="trace",
    )
    session.add(run)
    await session.flush()
    return run


class TestOwnerIsolation:
    async def test_other_owner_cannot_read(self, session: AsyncSession, owner: Owner) -> None:
        mine = MissionRepository(session, owner_id=owner.id)
        created = await mine.create(Mission(owner_id=owner.id, objective="meniki"))

        stranger = MissionRepository(session, owner_id=uuid.uuid4())
        with pytest.raises(MissionNotFoundError):
            await stranger.get(created.id)


class TestListOrdering:
    async def test_ordered_by_priority_then_recency(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        low = await repo.create(Mission(owner_id=owner.id, objective="A", priority=3))
        high = await repo.create(Mission(owner_id=owner.id, objective="B", priority=8))
        mid = await repo.create(Mission(owner_id=owner.id, objective="C", priority=5))

        listed = await repo.list()

        assert [m.id for m in listed] == [high.id, mid.id, low.id]

    async def test_active_only_filters_terminal(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        a = await repo.create(Mission(owner_id=owner.id, objective="active"))
        b = await repo.create(Mission(owner_id=owner.id, objective="done"))
        await repo.set_status(b.id, MissionStatus.UNDERSTANDING)
        await repo.set_status(b.id, MissionStatus.DISCOVERING)
        await repo.set_status(b.id, MissionStatus.PLANNING)
        await repo.set_status(b.id, MissionStatus.EXECUTING)
        await repo.set_status(b.id, MissionStatus.VERIFYING)
        await repo.set_status(b.id, MissionStatus.COMPLETED)

        active = await repo.list(active_only=True)
        assert [m.id for m in active] == [a.id]


class TestStateMachine:
    async def test_illegal_transition_rejected(self, repo: MissionRepository, owner: Owner) -> None:
        m = await repo.create(Mission(owner_id=owner.id, objective="x"))

        with pytest.raises(IllegalMissionTransitionError):
            await repo.set_status(m.id, MissionStatus.EXECUTING)

        fresh = await repo.get(m.id)
        assert fresh.status is MissionStatus.RECEIVED

    async def test_legal_transition_updates_timestamp(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        m = await repo.create(Mission(owner_id=owner.id, objective="x"))
        before = m.updated_at

        updated = await repo.set_status(m.id, MissionStatus.UNDERSTANDING)

        assert updated.status is MissionStatus.UNDERSTANDING
        assert updated.updated_at >= before


class TestRunLinks:
    async def test_attach_and_list_runs_ordered_by_attempt(
        self, repo: MissionRepository, session: AsyncSession, owner: Owner
    ) -> None:
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        r1 = await _make_run(session, owner)
        r2 = await _make_run(session, owner)

        await repo.attach_run(mission.id, r1.id, attempt=1)
        await repo.attach_run(mission.id, r2.id, attempt=2)

        runs = await repo.list_runs(mission.id)
        assert runs == [r1.id, r2.id]

        # `find_by_run` teskari lookup
        found = await repo.find_by_run(r2.id)
        assert found is not None
        assert found.id == mission.id

    async def test_delete_cascades_join_but_keeps_runs(
        self, repo: MissionRepository, session: AsyncSession, owner: Owner
    ) -> None:
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        r1 = await _make_run(session, owner)
        await repo.attach_run(mission.id, r1.id, attempt=1)

        await repo.delete(mission.id)

        # Run yozuvi qoladi
        assert (await session.get(Run, r1.id)) is not None
        # Mission topilmaydi
        with pytest.raises(MissionNotFoundError):
            await repo.get(mission.id)


class TestRecoveryLease:
    """JB-11 §12/§13 — DB-native "compare-and-set" mission egaligi."""

    async def test_claim_succeeds_on_unclaimed_mission(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))

        claimed = await repo.try_claim(mission.id, owner_token="worker-A")

        assert claimed is True
        fresh = await repo.get(mission.id)
        assert fresh.claimed_by == "worker-A"
        assert fresh.claim_expires_at is not None

    async def test_second_claim_from_different_worker_fails(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        """§12 — Worker B bir xil mission'ni Worker A ushlab turganda ola olmaydi."""
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        assert await repo.try_claim(mission.id, owner_token="worker-A") is True

        claimed_by_b = await repo.try_claim(mission.id, owner_token="worker-B")

        assert claimed_by_b is False
        # HAQIQIY holat — hali ham worker-A'niki, worker-B bosib o'tmagan.
        fresh = await repo.get(mission.id)
        assert fresh.claimed_by == "worker-A"

    async def test_release_clears_claim(self, repo: MissionRepository, owner: Owner) -> None:
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        await repo.try_claim(mission.id, owner_token="worker-A")

        await repo.release_claim(mission.id, owner_token="worker-A")

        fresh = await repo.get(mission.id)
        assert fresh.claimed_by is None
        assert fresh.claim_expires_at is None

    async def test_release_by_wrong_owner_is_noop(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        """Xato worker "release" chaqirsa — boshqa worker'ning yangi
        claim'ini o'chirib qo'ymasligi kerak (lost-update himoyasi)."""
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        await repo.try_claim(mission.id, owner_token="worker-A")

        # worker-B (hech qachon claim qilmagan) release chaqiradi.
        await repo.release_claim(mission.id, owner_token="worker-B")

        # worker-A'ning claim'i TEGILMAGAN qoldi.
        fresh = await repo.get(mission.id)
        assert fresh.claimed_by == "worker-A"

    async def test_claim_after_release_succeeds(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        await repo.try_claim(mission.id, owner_token="worker-A")
        await repo.release_claim(mission.id, owner_token="worker-A")

        claimed = await repo.try_claim(mission.id, owner_token="worker-B")

        assert claimed is True

    async def test_expired_lease_can_be_reclaimed(
        self, repo: MissionRepository, owner: Owner
    ) -> None:
        """§13 — CRASH bo'lgan worker mission'ni abadiy qulflab qo'ymaydi."""
        mission = await repo.create(Mission(owner_id=owner.id, objective="x"))
        # Muddati allaqachon O'TGAN lease bilan da'vo qilamiz (0 soniya).
        assert await repo.try_claim(mission.id, owner_token="crashed-worker", lease_seconds=0)

        # Biroz vaqt o'tishini kutmasdan ham — lease_seconds=0 darhol tugagan.
        import asyncio

        await asyncio.sleep(0.01)

        claimed = await repo.try_claim(mission.id, owner_token="worker-B")

        assert claimed is True
        fresh = await repo.get(mission.id)
        assert fresh.claimed_by == "worker-B"


class TestCountByStatus:
    async def test_counts_by_status(self, repo: MissionRepository, owner: Owner) -> None:
        await repo.create(Mission(owner_id=owner.id, objective="a"))
        await repo.create(Mission(owner_id=owner.id, objective="b"))
        m3 = await repo.create(Mission(owner_id=owner.id, objective="c"))
        await repo.set_status(m3.id, MissionStatus.UNDERSTANDING)

        counts = await repo.count_by_status()
        assert counts[MissionStatus.RECEIVED] == 2
        assert counts[MissionStatus.UNDERSTANDING] == 1


class TestContextRoundTrip:
    async def test_context_dict_preserved(self, repo: MissionRepository, owner: Owner) -> None:
        m = await repo.create(
            Mission(
                owner_id=owner.id,
                objective="x",
                context={"project_id": "abc", "notes": [1, 2, 3]},
            )
        )
        fresh = await repo.get(m.id)
        assert fresh.context == {"project_id": "abc", "notes": [1, 2, 3]}


class TestDeadlineField:
    async def test_deadline_stored_as_utc(self, repo: MissionRepository, owner: Owner) -> None:
        dl = utcnow() + timedelta(hours=1)
        m = await repo.create(Mission(owner_id=owner.id, objective="x", deadline=dl))
        fresh = await repo.get(m.id)
        assert fresh.deadline is not None
        assert fresh.deadline.tzinfo == UTC
        assert abs((fresh.deadline - dl).total_seconds()) < 1


def _now() -> datetime:
    return utcnow()
