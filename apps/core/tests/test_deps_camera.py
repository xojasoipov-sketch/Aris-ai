"""api/deps.get_tool_registry() — kamera provider tanlash mantiqi."""

from __future__ import annotations

import pytest

from zet.api import deps as api_deps
from zet.config import get_settings
from zet.devices.camera import StubCamera
from zet.devices.hikvision import HikvisionCamera


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    get_settings.cache_clear()
    api_deps.get_tool_registry.cache_clear()
    yield
    get_settings.cache_clear()
    api_deps.get_tool_registry.cache_clear()


class TestCameraProviderSelection:
    def test_stub_camera_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZET_HIKVISION_HOST", raising=False)
        registry = api_deps.get_tool_registry()
        tool = registry.get("camera.snapshot")
        assert isinstance(tool._provider, StubCamera)

    def test_hikvision_camera_when_fully_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_HIKVISION_HOST", "192.168.1.64")
        monkeypatch.setenv("ZET_HIKVISION_USERNAME", "admin")
        monkeypatch.setenv("ZET_HIKVISION_PASSWORD", "secret")
        registry = api_deps.get_tool_registry()
        tool = registry.get("camera.snapshot")
        assert isinstance(tool._provider, HikvisionCamera)

    def test_stub_when_partially_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Faqat host bor, username/password yo'q — hali StubCamera."""
        monkeypatch.setenv("ZET_HIKVISION_HOST", "192.168.1.64")
        monkeypatch.delenv("ZET_HIKVISION_USERNAME", raising=False)
        monkeypatch.delenv("ZET_HIKVISION_PASSWORD", raising=False)
        registry = api_deps.get_tool_registry()
        tool = registry.get("camera.snapshot")
        assert isinstance(tool._provider, StubCamera)
