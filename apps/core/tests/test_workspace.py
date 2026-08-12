"""Ish maydoni repozitoriysi testlari (Z46).

NEGA BU TESTLAR BOR.

`/projects`, `/tasks`, `/calendar` sahifalari ortida BACKEND YO'Q edi —
uchalasi ham frontend fayli ichidagi qotirilgan massivdan chizilardi:

    PROJECTS = [{ name: "ZET Core", progress: 78 }, ...]
    INITIAL  = [{ title: "SMM strategiyani yangilash", time: "10:00" }, ...]

Vazifani "bajarildi" deb belgilash faqat brauzer xotirasida qolardi va
sahifani yangilashda yo'qolardi. Bu testlar shu jadvallar haqiqatan
saqlashini va progress SON HISOBLANISHINI (qotirilgan foiz emas)
qulflaydi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models import Owner
from zet.domain.workspace import ProjectStatus, TaskPriority, TaskStatus
from zet.workspace.repository import WorkspaceNotFoundError, WorkspaceRepository


@pytest.fixture
def repo(session: AsyncSession, owner: Owner) -> WorkspaceRepository:
    return WorkspaceRepository(session, owner_id=owner.id)


class TestProjects:
    async def test_created_project_is_persisted(self, repo: WorkspaceRepository) -> None:
        created = await repo.create_project(name="ZET Core", description="Yadro")

        found = await repo.get_project(created.id)

        assert found.name == "ZET Core"
        assert found.status is ProjectStatus.ACTIVE

    async def test_list_filters_by_status(self, repo: WorkspaceRepository) -> None:
        await repo.create_project(name="Faol")
        await repo.create_project(name="Arxiv", status=ProjectStatus.ARCHIVED)

        active = await repo.list_projects(status=ProjectStatus.ACTIVE)

        assert [p.name for p in active] == ["Faol"]

    async def test_update_changes_only_given_fields(self, repo: WorkspaceRepository) -> None:
        project = await repo.create_project(name="Eski", description="tavsif")

        updated = await repo.update_project(project.id, name="Yangi")

        assert updated.name == "Yangi"
        assert updated.description == "tavsif"

    async def test_missing_project_raises(self, repo: WorkspaceRepository) -> None:
        import uuid

        with pytest.raises(WorkspaceNotFoundError):
            await repo.get_project(uuid.uuid4())

    async def test_deleting_project_keeps_its_tasks(self, repo: WorkspaceRepository) -> None:
        """`SET NULL` — loyihani o'chirish egani ishidan ayirmaydi."""
        project = await repo.create_project(name="Vaqtinchalik")
        task = await repo.create_task(title="Muhim ish", project_id=project.id)

        await repo.delete_project(project.id)

        survivor = await repo.get_task(task.id)
        assert survivor.title == "Muhim ish"
        assert survivor.project_id is None


class TestProgressIsComputed:
    """Progress vazifalardan HISOBLANADI — qotirilgan foiz emas."""

    async def test_counts_reflect_task_statuses(self, repo: WorkspaceRepository) -> None:
        project = await repo.create_project(name="Loyiha")
        await repo.create_task(title="1", project_id=project.id, status=TaskStatus.DONE)
        await repo.create_task(title="2", project_id=project.id, status=TaskStatus.DONE)
        await repo.create_task(title="3", project_id=project.id)

        counts = await repo.project_task_counts()

        assert counts[project.id] == (3, 2)

    async def test_project_without_tasks_is_absent(self, repo: WorkspaceRepository) -> None:
        """Vazifasiz loyiha 0% bo'lishi kerak, 100% emas."""
        project = await repo.create_project(name="Bo'sh")

        counts = await repo.project_task_counts()

        assert project.id not in counts


class TestTasks:
    async def test_default_status_and_priority(self, repo: WorkspaceRepository) -> None:
        task = await repo.create_task(title="Yangi ish")

        assert task.status is TaskStatus.TODO
        assert task.priority is TaskPriority.MEDIUM
        assert task.done_at is None

    async def test_marking_done_sets_done_at(self, repo: WorkspaceRepository) -> None:
        task = await repo.create_task(title="Ish")

        updated = await repo.update_task(task.id, status=TaskStatus.DONE)

        assert updated.done_at is not None

    async def test_reopening_clears_done_at(self, repo: WorkspaceRepository) -> None:
        """Aks holda "bajarildi" sanasi eski qiymatda qotib qolardi."""
        task = await repo.create_task(title="Ish", status=TaskStatus.DONE)
        assert task.done_at is not None

        reopened = await repo.update_task(task.id, status=TaskStatus.IN_PROGRESS)

        assert reopened.done_at is None

    async def test_done_at_is_not_overwritten_on_unrelated_edit(
        self, repo: WorkspaceRepository
    ) -> None:
        task = await repo.create_task(title="Ish")
        done = await repo.update_task(task.id, status=TaskStatus.DONE)
        first_done_at = done.done_at

        renamed = await repo.update_task(task.id, title="Boshqa nom")

        assert renamed.done_at == first_done_at

    async def test_list_filters_by_project(self, repo: WorkspaceRepository) -> None:
        a = await repo.create_project(name="A")
        b = await repo.create_project(name="B")
        await repo.create_task(title="a-ish", project_id=a.id)
        await repo.create_task(title="b-ish", project_id=b.id)

        tasks = await repo.list_tasks(project_id=a.id)

        assert [t.title for t in tasks] == ["a-ish"]

    async def test_delete_removes_the_task(self, repo: WorkspaceRepository) -> None:
        task = await repo.create_task(title="O'chiriladi")

        await repo.delete_task(task.id)

        with pytest.raises(WorkspaceNotFoundError):
            await repo.get_task(task.id)


class TestCalendar:
    async def test_range_filter_excludes_outside_events(
        self, repo: WorkspaceRepository
    ) -> None:
        base = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        await repo.create_event(title="Ichkarida", starts_at=base)
        await repo.create_event(title="Tashqarida", starts_at=base + timedelta(days=40))

        events = await repo.list_events(start=base - timedelta(days=1), end=base + timedelta(days=1))

        assert [e.title for e in events] == ["Ichkarida"]

    async def test_events_are_ordered_by_start(self, repo: WorkspaceRepository) -> None:
        base = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        await repo.create_event(title="Keyin", starts_at=base + timedelta(hours=2))
        await repo.create_event(title="Avval", starts_at=base)

        events = await repo.list_events()

        assert [e.title for e in events] == ["Avval", "Keyin"]


class TestOwnerIsolation:
    """Boshqa egaga tegishli yozuv qaytmasligi kerak."""

    async def test_other_owner_cannot_read(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        import uuid

        mine = WorkspaceRepository(session, owner_id=owner.id)
        project = await mine.create_project(name="Meniki")

        stranger = WorkspaceRepository(session, owner_id=uuid.uuid4())

        with pytest.raises(WorkspaceNotFoundError):
            await stranger.get_project(project.id)
