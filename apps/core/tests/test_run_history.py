"""`GET /api/v1/runs` — run tarixi (bazadan) testlari.

NEGA BU TESTLAR BOR. Endpoint DB'dagi `run` jadvalidan to'g'ridan-to'g'ri
o'qiydi (xotiradagi `Orchestrator.run_store`ga bog'liq emas) — shuning
uchun `test_device_api.py`/`test_run_checkpoint.py` naqshi bilan real
in-memory sqlite'ga qatorlar yozib, HTTP orqali tekshiramiz:

    - tartib: eng yangi run birinchi (`created_at DESC`)
    - `tools_used`: `completed_steps`dan `tool_result.tool_name`,
      TAKRORSIZ, position tartibida
    - `steps_total`: `plan_snapshot["steps"]` uzunligi, bo'lmasa
      `steps_done` bilan bir xil
    - `limit`/`offset` sahifalash
    - egalar orasida izolyatsiya — boshqa eganing run'i ko'rinmaydi
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.app import create_app
from zet.api.deps import get_db_session
from zet.config import get_settings
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.run import Run as RunRow
from zet.domain.enums import RunStatus

_BASE_TIME = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)


@pytest.fixture()
def client(session: AsyncSession) -> TestClient:
    """HTTP klient — bitta in-memory sessiya barcha so'rovlar uchun.

    Naqsh `test_device_api.py`dagi bilan bir xil: `get_db_session`
    real sessiyaga almashtiriladi, `get_config` esa o'zgarmaydi
    (default `settings.owner_id` — egalar izolyatsiyasini sinash uchun
    aynan shu qiymat kerak).
    """
    app = create_app()

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = _session_override
    return TestClient(app, raise_server_exceptions=False)


def _step_result(
    *, status: str = "done", tool_name: str | None, cost_usd: float = 0.001
) -> dict[str, Any]:
    """`run_checkpoint.py::_serialize_step_result()` formatiga mos yozuv."""
    return {
        "status": status,
        "output": "natija",
        "error": None,
        "retries": 0,
        "cost_usd": cost_usd,
        "tool_result": (
            {
                "tool_name": tool_name,
                "success": True,
                "output": "ok",
                "error": None,
            }
            if tool_name is not None
            else None
        ),
    }


async def _make_run(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    command_text: str,
    status: RunStatus = RunStatus.DONE,
    created_at: datetime,
    completed_steps: dict[str, Any] | None = None,
    plan_snapshot: dict[str, Any] | None = None,
    spent_usd: float = 0.0,
    result_summary: str | None = None,
    error: str | None = None,
    finished_at: datetime | None = None,
) -> RunRow:
    row = RunRow(
        owner_id=owner_id,
        command_text=command_text,
        status=status,
        trace_id=f"trace-{command_text}",
        spent_usd=spent_usd,
        result_summary=result_summary,
        error=error,
        created_at=created_at,
        finished_at=finished_at,
        completed_steps=completed_steps,
        plan_snapshot=plan_snapshot,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


class TestRunHistoryOrdering:
    async def test_returns_runs_newest_first(
        self, client: TestClient, session: AsyncSession
    ) -> None:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)

        await _make_run(
            session,
            owner_id=owner.id,
            command_text="birinchi",
            created_at=_BASE_TIME,
        )
        await _make_run(
            session,
            owner_id=owner.id,
            command_text="ikkinchi",
            created_at=_BASE_TIME + timedelta(minutes=5),
        )
        await _make_run(
            session,
            owner_id=owner.id,
            command_text="uchinchi",
            created_at=_BASE_TIME + timedelta(minutes=10),
        )

        resp = client.get("/api/v1/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert [r["command_text"] for r in data] == ["uchinchi", "ikkinchi", "birinchi"]


class TestRunHistoryFields:
    async def test_tools_used_deduped_in_position_order(
        self, client: TestClient, session: AsyncSession
    ) -> None:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)

        completed_steps = {
            "2": _step_result(tool_name="note.write"),
            "0": _step_result(tool_name="time.now"),
            # tool'siz fikrlash qadami — tool_result yo'q
            "1": _step_result(tool_name=None),
            # takrorlangan tool — natijada faqat bitta marta chiqadi
            "3": _step_result(tool_name="time.now"),
        }
        plan_snapshot = {"steps": [{"position": i} for i in range(4)]}

        await _make_run(
            session,
            owner_id=owner.id,
            command_text="tool ishlatuvchi run",
            created_at=_BASE_TIME,
            completed_steps=completed_steps,
            plan_snapshot=plan_snapshot,
            spent_usd=0.0123456,
            result_summary="Bajarildi",
            finished_at=_BASE_TIME + timedelta(minutes=1),
        )

        resp = client.get("/api/v1/runs")
        assert resp.status_code == 200
        [entry] = resp.json()

        assert entry["tools_used"] == ["time.now", "note.write"], (
            "position tartibida, takrorsiz bo'lishi kerak"
        )
        assert entry["steps_done"] == 4
        assert entry["steps_total"] == 4
        assert entry["cost_usd"] == 0.012346  # round(., 6)
        assert entry["result_summary"] == "Bajarildi"
        assert entry["status"] == "done"
        assert entry["finished_at"] is not None

    async def test_steps_total_falls_back_to_steps_done_without_plan(
        self, client: TestClient, session: AsyncSession
    ) -> None:
        """`plan_snapshot` yo'q holat — o'ylab topilgan son emas, `steps_done`ga teng."""
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)

        await _make_run(
            session,
            owner_id=owner.id,
            command_text="rejasiz run",
            created_at=_BASE_TIME,
            completed_steps={"0": _step_result(tool_name="time.now")},
            plan_snapshot=None,
        )

        resp = client.get("/api/v1/runs")
        [entry] = resp.json()
        assert entry["steps_done"] == 1
        assert entry["steps_total"] == 1

    async def test_no_completed_steps_gives_empty_state(
        self, client: TestClient, session: AsyncSession
    ) -> None:
        """Hech qanday checkpoint yozuvi yo'q — bo'sh holat, xato emas."""
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)

        await _make_run(
            session,
            owner_id=owner.id,
            command_text="yangi boshlangan run",
            status=RunStatus.PENDING,
            created_at=_BASE_TIME,
        )

        resp = client.get("/api/v1/runs")
        [entry] = resp.json()
        assert entry["steps_done"] == 0
        assert entry["steps_total"] == 0
        assert entry["tools_used"] == []
        assert entry["result_summary"] is None
        assert entry["error"] is None
        assert entry["finished_at"] is None


class TestRunHistoryPagination:
    async def test_limit_and_offset(self, client: TestClient, session: AsyncSession) -> None:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)

        for i in range(5):
            await _make_run(
                session,
                owner_id=owner.id,
                command_text=f"run-{i}",
                created_at=_BASE_TIME + timedelta(minutes=i),
            )

        first_page = client.get("/api/v1/runs?limit=2&offset=0").json()
        assert [r["command_text"] for r in first_page] == ["run-4", "run-3"]

        second_page = client.get("/api/v1/runs?limit=2&offset=2").json()
        assert [r["command_text"] for r in second_page] == ["run-2", "run-1"]

    async def test_default_limit_is_20(self, client: TestClient, session: AsyncSession) -> None:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)

        for i in range(25):
            await _make_run(
                session,
                owner_id=owner.id,
                command_text=f"run-{i}",
                created_at=_BASE_TIME + timedelta(minutes=i),
            )

        resp = client.get("/api/v1/runs")
        assert len(resp.json()) == 20

    async def test_limit_out_of_range_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/v1/runs?limit=101")
        assert resp.status_code == 422

        resp = client.get("/api/v1/runs?limit=0")
        assert resp.status_code == 422

        resp = client.get("/api/v1/runs?offset=-1")
        assert resp.status_code == 422


class TestRunHistoryOwnerIsolation:
    async def test_other_owners_runs_not_visible(
        self, client: TestClient, session: AsyncSession
    ) -> None:
        settings = get_settings()
        my_owner = await get_or_create_owner(session, external_id=settings.owner_id)
        other_owner = await get_or_create_owner(session, external_id="boshqa-ega-xyz")

        await _make_run(
            session,
            owner_id=my_owner.id,
            command_text="mening run'im",
            created_at=_BASE_TIME,
        )
        await _make_run(
            session,
            owner_id=other_owner.id,
            command_text="boshqa eganing run'i",
            created_at=_BASE_TIME + timedelta(minutes=1),
        )

        resp = client.get("/api/v1/runs")
        data = resp.json()
        assert [r["command_text"] for r in data] == ["mening run'im"]
