"""Mission Pydantic model testlari (Bo'lim 2, §2.2).

Mission — Pydantic v2 modeli. `from_attributes=True` ORM qatorlaridan
toza konvertatsiyani ta'minlaydi; `model_dump()` round-trip esa
JSON serializatsiya oqimini (repository JSON ustunlarga yozadi) qulflaydi.
"""

from __future__ import annotations

import uuid

from zet.core.mission import Mission, MissionTask
from zet.domain.enums import MissionStatus, PermissionLevel, RiskLevel, StepStatus


class TestMissionDefaults:
    def test_generates_uuid_and_timestamps(self) -> None:
        mission = Mission(owner_id=uuid.uuid4(), objective="sayt qur")

        assert isinstance(mission.id, uuid.UUID)
        assert mission.created_at is not None
        assert mission.updated_at is not None
        assert mission.status is MissionStatus.RECEIVED
        assert mission.risk_level is RiskLevel.LOW
        assert mission.priority == 5

    def test_collections_default_to_empty(self) -> None:
        mission = Mission(owner_id=uuid.uuid4(), objective="ish")

        assert mission.constraints == []
        assert mission.tasks == []
        assert mission.tools == []
        assert mission.run_ids == []
        assert mission.memory_updates == []
        assert mission.context == {}


class TestMissionRoundTrip:
    def test_model_dump_and_validate_preserves_enums(self) -> None:
        original = Mission(
            owner_id=uuid.uuid4(),
            objective="biznes ochish",
            risk_level=RiskLevel.HIGH,
            status=MissionStatus.PLANNING,
            permissions_required=[PermissionLevel.WRITE, PermissionLevel.EXECUTE],
            tasks=[
                MissionTask(
                    position=0,
                    title="reja tuz",
                    tool="planner",
                    status=StepStatus.PENDING,
                )
            ],
        )

        dumped = original.model_dump(mode="json")
        restored = Mission.model_validate(dumped)

        assert restored.risk_level is RiskLevel.HIGH
        assert restored.status is MissionStatus.PLANNING
        assert restored.permissions_required == [
            PermissionLevel.WRITE,
            PermissionLevel.EXECUTE,
        ]
        assert restored.tasks[0].tool == "planner"
        assert restored.tasks[0].status is StepStatus.PENDING
