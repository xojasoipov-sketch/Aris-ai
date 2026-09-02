"""MissionEngine.execute() ijroni HAQIQATAN cheklaydimi? (JB-4)

Audit topilmasi: `mission.tools` (compose() aniqlagan kerakli toollar)
faqat ma'lumot uchun saqlanardi — ijro har doim TO'LIQ global tool
registry orqali borardi, tanlov "o'lik metadata" edi.

Bu testlar `Orchestrator.start()`ga UZATILGAN `tool_registry_override`
haqiqatan `mission.tools`ga mos torroq registry ekanini tekshiradi —
nafaqat "chaqirildi", balki "TO'G'RI qamrov bilan chaqirildi".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from zet.core.mission import MissionEngine
from zet.core.mission_repository import MissionRepository
from zet.db.models import Owner
from zet.db.models.run import Run
from zet.domain.enums import MissionStatus, PermissionLevel, RiskLevel, RunStatus, RunTrigger
from zet.security.approvals import ApprovalService
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


class _StubTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> str:
        return "ok"


@dataclass
class _FakeBundle:
    capabilities: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions_required: list[PermissionLevel] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    tool_agents: dict[str, str] = field(default_factory=dict)


class _FakeCapabilityRegistry:
    def __init__(self, bundle: _FakeBundle) -> None:
        self._bundle = bundle

    def compose(self, objective: str, context: dict[str, Any]) -> _FakeBundle:
        return self._bundle


class _FakeContextEngine:
    async def discover(self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]) -> Any:
        class _Empty:
            def to_dict(self) -> dict[str, Any]:
                return {}

        return _Empty()


@dataclass
class _FakeRunRecord:
    run_id: uuid.UUID
    status: RunStatus = RunStatus.DONE
    verified_ok: bool | None = True
    pending_approval_id: uuid.UUID | None = None
    error: str | None = None
    result_summary: str | None = "bajarildi"


class _RecordingOrchestrator:
    """`tool_registry_override`ni AYNAN ushlab qoladi — mock emas, DALIL."""

    def __init__(self, session: Any, owner: Owner, *, full_registry: ToolRegistry) -> None:
        self._session = session
        self._owner = owner
        self.tool_registry = full_registry
        self.received_overrides: list[ToolRegistry | None] = []
        self._queued: list[_FakeRunRecord] = []

    def queue(self, record: _FakeRunRecord) -> None:
        self._queued.append(record)

    async def start(
        self,
        command: Any,
        *,
        dry_run: bool = False,
        intent: Any = None,
        tool_registry_override: ToolRegistry | None = None,
    ) -> _FakeRunRecord:
        self.received_overrides.append(tool_registry_override)
        record = self._queued.pop(0)
        run = Run(
            id=record.run_id,
            owner_id=self._owner.id,
            trigger=RunTrigger.MANUAL,
            command_text=str(getattr(command, "text", "x")),
            trace_id="trace",
        )
        self._session.add(run)
        await self._session.flush()
        return record


def _full_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name in ["note.write", "web.search", "shell.exec", "telegram.channel_post"]:
        reg.register(_StubTool(name))
    return reg


class TestExecutionIsScopedToMissionTools:
    async def test_override_is_a_real_subset_of_mission_tools(
        self, session: Any, owner: Owner
    ) -> None:
        full = _full_registry()
        orch = _RecordingOrchestrator(session, owner, full_registry=full)
        bundle = _FakeBundle(tools=["note.write", "web.search"])
        repo = MissionRepository(session, owner_id=owner.id)
        engine = MissionEngine(
            repository=repo,
            capability_registry=_FakeCapabilityRegistry(bundle),
            context_engine=_FakeContextEngine(),
            planner=object(),
            orchestrator=orch,  # type: ignore[arg-type]
            approvals=ApprovalService(),
        )
        run_id = uuid.uuid4()
        orch.queue(_FakeRunRecord(run_id=run_id))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert len(orch.received_overrides) == 1
        override = orch.received_overrides[0]
        assert override is not None
        # ENG MUHIM DALIL: override FAQAT mission.tools'ni ko'radi —
        # to'liq registrydagi "shell.exec"/"telegram.channel_post" YO'Q.
        assert sorted(override.tool_names()) == ["note.write", "web.search"]
        assert not override.has("shell.exec")
        assert not override.has("telegram.channel_post")

    async def test_empty_mission_tools_uses_full_registry(
        self, session: Any, owner: Owner
    ) -> None:
        """Fail-open: `mission.tools` bo'sh bo'lsa cheklov qo'yilmaydi."""
        full = _full_registry()
        orch = _RecordingOrchestrator(session, owner, full_registry=full)
        bundle = _FakeBundle(tools=[])
        repo = MissionRepository(session, owner_id=owner.id)
        engine = MissionEngine(
            repository=repo,
            capability_registry=_FakeCapabilityRegistry(bundle),
            context_engine=_FakeContextEngine(),
            planner=object(),
            orchestrator=orch,  # type: ignore[arg-type]
            approvals=ApprovalService(),
        )
        run_id = uuid.uuid4()
        orch.queue(_FakeRunRecord(run_id=run_id))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        await engine.run_to_completion(m.id)

        assert orch.received_overrides == [None]
