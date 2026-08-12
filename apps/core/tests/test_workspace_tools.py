"""Ish maydoni tool'lari testlari (Z48).

NEGA BU TESTLAR BOR.

Z46 doskani BAZAGA yozdi va brauzerga ochdi, lekin ZET o'zi unga yeta
olmasdi — registry'da vazifa/kalendar tooli yo'q edi. Natijada ikkita
TIZIM retsepti ("Ovozdan rejaga", "Kunlik puls") `MISSING_CAPABILITY`
bo'lib turardi: jadval bor, yo'l yo'q.

Bu testlar uch narsani qulflaydi:

  1. Tool'lar HAQIQIY bazaga yozadi va o'qiydi (stub emas).
  2. Ulanmagan tool JIMGINA BO'SH RO'YXAT qaytarmaydi — ochiq xato
     beradi. Aks holda "doska ulanmagan" va "doskada ish yo'q" bir xil
     ko'rinib, ZET egaga "hech qanday vazifa yo'q" deb yolg'on aytardi.
  3. `task.pulse` siljigan/turib qolgan/qaror kutayotganni KODDA
     ajratadi — bu sanani solishtirish, LLM ishi emas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.base import utcnow
from zet.db.models import Owner
from zet.domain.workspace import TaskStatus
from zet.tools.builtin.workspace_tools import (
    CalendarAddTool,
    CalendarListTool,
    ProjectListTool,
    TaskCreateTool,
    TaskListTool,
    TaskPulseTool,
    TaskUpdateTool,
    WorkspaceScope,
)
from zet.workspace.repository import WorkspaceRepository


@pytest.fixture
def scope(session: AsyncSession, owner: Owner) -> WorkspaceScope:
    """Test sessiyasini tool kutgan kontekst fabrikasiga o'raydi.

    Ishlab chiqarishda har chaqiruv o'z sessiyasini ochadi; testda esa
    bitta sessiya qayta ishlatiladi, shunda tool yozgan narsani test
    to'g'ridan-to'g'ri ko'ra oladi."""

    @asynccontextmanager
    async def _scope() -> AsyncIterator[WorkspaceRepository]:
        yield WorkspaceRepository(session, owner_id=owner.id)

    return _scope


class TestUnwiredToolsFailLoudly:
    """Ulanmagan tool bo'sh javob emas, XATO qaytaradi."""

    async def test_task_list_without_scope_reports_error(self) -> None:
        result = await TaskListTool().execute({})

        assert result.success is False
        assert "ulanmagan" in (result.error or "")

    async def test_calendar_add_without_scope_reports_error(self) -> None:
        result = await CalendarAddTool().execute(
            {"title": "Uchrashuv", "starts_at": "2026-08-14T15:00"}
        )

        assert result.success is False

    def test_connected_flag_follows_scope(self, scope: WorkspaceScope) -> None:
        assert TaskListTool().connected is False
        assert TaskListTool(scope=scope).connected is True


class TestTaskTools:
    async def test_created_task_is_readable_back(self, scope: WorkspaceScope) -> None:
        created = await TaskCreateTool(scope=scope).execute(
            {"title": "SMM rejasini yozish", "priority": "high"}
        )
        listed = await TaskListTool(scope=scope).execute({})

        assert created.success is True
        assert listed.output is not None
        titles = [t["title"] for t in listed.output["tasks"]]
        assert "SMM rejasini yozish" in titles

    async def test_status_filter_narrows_result(self, scope: WorkspaceScope) -> None:
        tool = TaskCreateTool(scope=scope)
        await tool.execute({"title": "Ochiq ish"})
        created = await tool.execute({"title": "Bajarilgan ish"})
        assert created.output is not None
        await TaskUpdateTool(scope=scope).execute(
            {"task_id": created.output["task"]["id"], "status": "done"}
        )

        done = await TaskListTool(scope=scope).execute({"status": "done"})

        assert done.output is not None
        assert [t["title"] for t in done.output["tasks"]] == ["Bajarilgan ish"]

    async def test_naive_due_date_is_read_in_owner_timezone(
        self, scope: WorkspaceScope, session: AsyncSession, owner: Owner
    ) -> None:
        """Mintaqasiz sana UTC emas, EGA mintaqasida tushuniladi.

        UTC deb olish jimgina 5 soatlik xatoga olib kelardi: "ertaga
        09:00" ertalabki ish o'rniga tushdan keyin chiqardi."""
        result = await TaskCreateTool(scope=scope, tz="Asia/Tashkent").execute(
            {"title": "Ertalabki qo'ng'iroq", "due_at": "2026-08-14T09:00"}
        )

        assert result.output is not None
        stored = await WorkspaceRepository(session, owner_id=owner.id).get_task(
            __import__("uuid").UUID(result.output["task"]["id"])
        )
        assert stored.due_at is not None
        # Toshkent UTC+5 — 09:00 mahalliy = 04:00 UTC.
        assert stored.due_at.astimezone(UTC).hour == 4

    async def test_bad_date_is_reported_not_silently_dropped(self, scope: WorkspaceScope) -> None:
        result = await TaskCreateTool(scope=scope).execute(
            {"title": "Ish", "due_at": "kelasi payshanba"}
        )

        assert result.success is False
        assert "due_at" in (result.error or "")

    async def test_update_of_missing_task_reports_error(self, scope: WorkspaceScope) -> None:
        result = await TaskUpdateTool(scope=scope).execute(
            {"task_id": "00000000-0000-0000-0000-000000000001", "status": "done"}
        )

        assert result.success is False

    def test_write_tools_are_not_idempotent(self) -> None:
        """Ikki marta chaqirilsa ikkita yozuv paydo bo'ladi.

        Executor idempotent tool natijasini qayta ishlatadi — vazifa
        yaratishda bu xato bo'lardi."""
        assert TaskCreateTool().idempotent is False
        assert CalendarAddTool().idempotent is False
        assert TaskListTool().idempotent is True


class TestTaskPulse:
    """T06 "Kunlik puls" — uchta ro'yxat kodda ajratiladi."""

    async def test_recent_task_counts_as_moved(self, scope: WorkspaceScope) -> None:
        await TaskCreateTool(scope=scope).execute({"title": "Bugungi ish"})

        pulse = await TaskPulseTool(scope=scope).execute({})

        assert pulse.output is not None
        assert pulse.output["summary"]["moved"] == 1
        assert pulse.output["summary"]["stuck"] == 0

    async def test_old_open_task_counts_as_stuck(
        self, scope: WorkspaceScope, session: AsyncSession, owner: Owner
    ) -> None:
        repo = WorkspaceRepository(session, owner_id=owner.id)
        task = await repo.create_task(title="Unutilgan ish")
        task.updated_at = utcnow() - timedelta(days=10)
        await session.flush()

        pulse = await TaskPulseTool(scope=scope).execute({})

        assert pulse.output is not None
        assert [t["title"] for t in pulse.output["stuck"]] == ["Unutilgan ish"]

    async def test_finished_old_task_is_not_stuck(
        self, scope: WorkspaceScope, session: AsyncSession, owner: Owner
    ) -> None:
        """Bajarilgan ish qanchalik eski bo'lsa ham "turib qolgan" emas."""
        repo = WorkspaceRepository(session, owner_id=owner.id)
        task = await repo.create_task(title="Eski, lekin bajarilgan", status=TaskStatus.DONE)
        task.updated_at = utcnow() - timedelta(days=30)
        await session.flush()

        pulse = await TaskPulseTool(scope=scope).execute({})

        assert pulse.output is not None
        assert pulse.output["stuck"] == []

    async def test_blocked_and_overdue_await_owner_decision(
        self, scope: WorkspaceScope, session: AsyncSession, owner: Owner
    ) -> None:
        repo = WorkspaceRepository(session, owner_id=owner.id)
        await repo.create_task(title="To'silgan", status=TaskStatus.BLOCKED)
        await repo.create_task(title="Muddati o'tgan", due_at=datetime(2020, 1, 1, tzinfo=UTC))

        pulse = await TaskPulseTool(scope=scope).execute({})

        assert pulse.output is not None
        waiting = {t["title"] for t in pulse.output["awaiting_decision"]}
        assert waiting == {"To'silgan", "Muddati o'tgan"}


class TestProjectAndCalendar:
    async def test_project_progress_is_computed_from_tasks(
        self, scope: WorkspaceScope, session: AsyncSession, owner: Owner
    ) -> None:
        """Progress QOTIRILGAN foiz emas — vazifalardan hisoblanadi."""
        repo = WorkspaceRepository(session, owner_id=owner.id)
        project = await repo.create_project(name="ZET Core")
        await repo.create_task(title="1", project_id=project.id, status=TaskStatus.DONE)
        await repo.create_task(title="2", project_id=project.id)

        result = await ProjectListTool(scope=scope).execute({})

        assert result.output is not None
        assert result.output["projects"][0]["progress"] == 50

    async def test_event_gets_default_duration(self, scope: WorkspaceScope) -> None:
        created = await CalendarAddTool(scope=scope, tz="UTC").execute(
            {"title": "Qo'ng'iroq", "starts_at": "2026-08-14T15:00"}
        )

        assert created.output is not None
        event = created.output["event"]
        assert event["starts_at"].startswith("2026-08-14T15:00")
        assert event["ends_at"].startswith("2026-08-14T16:00")

    async def test_calendar_list_covers_only_requested_window(
        self, scope: WorkspaceScope, session: AsyncSession, owner: Owner
    ) -> None:
        repo = WorkspaceRepository(session, owner_id=owner.id)
        await repo.create_event(title="Yaqin", starts_at=utcnow() + timedelta(days=2))
        await repo.create_event(title="Uzoq", starts_at=utcnow() + timedelta(days=60))

        result = await CalendarListTool(scope=scope).execute({"days": 7})

        assert result.output is not None
        assert [e["title"] for e in result.output["events"]] == ["Yaqin"]
