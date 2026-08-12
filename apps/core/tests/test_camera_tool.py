"""CameraSnapshotTool testlari (gap-analysis #8/#11)."""

from __future__ import annotations

from zet.devices.camera import CameraProvider, CameraSnapshot, StubCamera
from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.builtin.camera import CameraSnapshotTool


class _FailingCamera(CameraProvider):
    async def snapshot(self, camera_id: str) -> CameraSnapshot:
        return CameraSnapshot(camera_id=camera_id, source="failing", error="Ulanib bo'lmadi")

    async def is_available(self, _camera_id: str) -> bool:
        return False

    async def info(self, camera_id: str) -> dict[str, str]:
        return {"name": camera_id}


class TestCameraSnapshotTool:
    def test_properties(self) -> None:
        tool = CameraSnapshotTool()
        assert tool.name == "camera.snapshot"
        assert tool.permission_level == PermissionLevel.READ
        assert tool.output_trust_level == TrustLevel.UNTRUSTED
        assert tool.idempotent is False

    def test_defaults_to_stub_camera(self) -> None:
        tool = CameraSnapshotTool()
        assert isinstance(tool._provider, StubCamera)

    async def test_snapshot_success(self) -> None:
        tool = CameraSnapshotTool(provider=StubCamera())
        result = await tool.execute({"camera_id": "front-door"})
        assert result.success
        assert result.output["has_image"] is True
        assert result.output["camera_id"] == "front-door"
        assert result.output["media_type"] == "image/jpeg"
        assert result.output["image_b64"]

    async def test_snapshot_untrusted(self) -> None:
        tool = CameraSnapshotTool(provider=StubCamera())
        result = await tool.execute({"camera_id": "x"})
        assert result.trust_level == TrustLevel.UNTRUSTED

    async def test_unavailable_camera_returns_error(self) -> None:
        tool = CameraSnapshotTool(provider=_FailingCamera())
        result = await tool.execute({"camera_id": "broken"})
        assert not result.success
        assert "Ulanib bo'lmadi" in result.error
