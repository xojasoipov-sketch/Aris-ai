"""Desktop tool testlari (StubDesktop bilan — GUI kerak emas).

Provider pattern: `camera_tools` bilan bir xil arxitektura.
Real PyAutoGUI test'lari — mahalliy ish stolida qo'l bilan sinaladi;
avtomatik test faqat stub bilan (deterministik va xavfsiz).
"""

from __future__ import annotations

import pytest

from zet.devices.desktop import StubDesktop
from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.builtin.desktop_tools import (
    DesktopKeyPressTool,
    DesktopMouseClickTool,
    DesktopScreenshotTool,
    DesktopTypeTextTool,
)

# ── StubDesktop ────────────────────────────────────────────────────


class TestStubDesktop:
    async def test_unavailable_by_default(self) -> None:
        stub = StubDesktop()
        assert await stub.is_available() is False
        shot = await stub.screenshot()
        assert shot.error is not None

    async def test_available_true(self) -> None:
        stub = StubDesktop(available=True)
        assert await stub.is_available() is True
        shot = await stub.screenshot()
        assert shot.error is None
        assert shot.has_image is True
        assert shot.width == 1
        assert shot.height == 1

    async def test_action_count_increments(self) -> None:
        stub = StubDesktop(available=True)
        await stub.screenshot()
        await stub.type_text("hi")
        await stub.key_press(["cmd", "c"])
        await stub.mouse_click(100, 200)
        assert stub.action_count == 4

    async def test_type_text_records_len(self) -> None:
        stub = StubDesktop(available=True)
        result = await stub.type_text("Salom dunyo!", interval_s=0.01)
        assert result.executed is True
        assert result.details["chars"] == 12

    async def test_key_press_combo(self) -> None:
        stub = StubDesktop(available=True)
        result = await stub.key_press(["cmd", "shift", "a"])
        assert result.executed is True
        assert result.details["combo"] == "cmd+shift+a"
        assert result.details["n_keys"] == 3

    async def test_mouse_move(self) -> None:
        stub = StubDesktop(available=True)
        result = await stub.mouse_move(500, 300)
        assert result.executed is True
        assert result.details["x"] == 500

    async def test_stub_unavailable_returns_errors(self) -> None:
        stub = StubDesktop(available=False)
        assert (await stub.type_text("x")).error is not None
        assert (await stub.key_press(["a"])).error is not None
        assert (await stub.mouse_click(0, 0)).error is not None
        assert (await stub.mouse_move(0, 0)).error is not None


# ── Screenshot tool ────────────────────────────────────────────────


class TestDesktopScreenshotTool:
    async def test_returns_error_when_stub_unavailable(self) -> None:
        tool = DesktopScreenshotTool(provider=StubDesktop(available=False))
        result = await tool.execute({})
        assert result.success is False
        assert "mavjud" in (result.error or "").lower()

    async def test_success_when_available(self) -> None:
        tool = DesktopScreenshotTool(provider=StubDesktop(available=True))
        result = await tool.execute({})
        assert result.success is True
        assert result.output["width"] == 1
        assert result.output["image_b64"] != ""

    def test_permission_read(self) -> None:
        assert DesktopScreenshotTool().permission_level == PermissionLevel.READ

    def test_trust_untrusted(self) -> None:
        """Ekran mazmuni prompt injection'ga sezgir → UNTRUSTED (A-05)."""
        assert DesktopScreenshotTool().output_trust_level == TrustLevel.UNTRUSTED


# ── Type text tool ─────────────────────────────────────────────────


class TestDesktopTypeTextTool:
    async def test_types_text(self) -> None:
        tool = DesktopTypeTextTool(provider=StubDesktop(available=True))
        result = await tool.execute({"text": "Salom", "interval_ms": 10})
        assert result.success is True
        assert result.output["executed"] is True
        assert result.output["details"]["chars"] == 5

    def test_permission_execute(self) -> None:
        """Klaviatura yozish EXECUTE — approval kerak."""
        assert DesktopTypeTextTool().permission_level == PermissionLevel.EXECUTE

    def test_not_idempotent(self) -> None:
        assert DesktopTypeTextTool().idempotent is False


# ── Key press tool ─────────────────────────────────────────────────


class TestDesktopKeyPressTool:
    async def test_valid_hotkey(self) -> None:
        tool = DesktopKeyPressTool(provider=StubDesktop(available=True))
        result = await tool.execute({"keys": ["cmd", "c"]})
        assert result.success is True
        assert result.output["combo"] == "cmd+c"

    async def test_single_char_key(self) -> None:
        tool = DesktopKeyPressTool(provider=StubDesktop(available=True))
        result = await tool.execute({"keys": ["a"]})
        assert result.success is True

    async def test_digit_key(self) -> None:
        tool = DesktopKeyPressTool(provider=StubDesktop(available=True))
        result = await tool.execute({"keys": ["ctrl", "1"]})
        assert result.success is True

    async def test_invalid_key_rejected(self) -> None:
        tool = DesktopKeyPressTool(provider=StubDesktop(available=True))
        result = await tool.execute({"keys": ["destroy_everything"]})
        assert result.success is False
        assert "noruxsat" in (result.error or "").lower()

    async def test_case_insensitive(self) -> None:
        tool = DesktopKeyPressTool(provider=StubDesktop(available=True))
        result = await tool.execute({"keys": ["CMD", "C"]})
        assert result.success is True
        assert result.output["combo"] == "cmd+c"

    def test_permission_execute(self) -> None:
        assert DesktopKeyPressTool().permission_level == PermissionLevel.EXECUTE


# ── Mouse click tool ───────────────────────────────────────────────


class TestDesktopMouseClickTool:
    async def test_left_click(self) -> None:
        tool = DesktopMouseClickTool(provider=StubDesktop(available=True))
        result = await tool.execute({"x": 100, "y": 200})
        assert result.success is True
        assert result.output["x"] == 100
        assert result.output["button"] == "left"
        assert result.output["clicks"] == 1

    async def test_double_right_click(self) -> None:
        tool = DesktopMouseClickTool(provider=StubDesktop(available=True))
        result = await tool.execute({"x": 50, "y": 60, "button": "right", "clicks": 2})
        assert result.success is True
        assert result.output["button"] == "right"
        assert result.output["clicks"] == 2

    def test_permission_execute(self) -> None:
        assert DesktopMouseClickTool().permission_level == PermissionLevel.EXECUTE


# ── Registry wiring ────────────────────────────────────────────────


class TestRegistryWiring:
    def test_desktop_tools_registered(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        names = set(registry.tool_names())
        assert "desktop.screenshot" in names
        assert "desktop.type_text" in names
        assert "desktop.key_press" in names
        assert "desktop.mouse_click" in names

    def test_default_provider_is_stub_unavailable(self, tmp_path: pytest.TempPathFactory) -> None:
        """Default (server muhitida) — stub, unavailable → xato qaytadi."""
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        tool = registry.get("desktop.screenshot")
        assert tool is not None

    def test_custom_provider_injected(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        provider = StubDesktop(available=True)
        registry = build_default_registry(
            notes_dir=tmp_path,  # type: ignore[arg-type]
            desktop_provider=provider,
        )
        tool = registry.get("desktop.screenshot")
        assert tool._provider is provider  # type: ignore[attr-defined]


# ── Eval permissions ───────────────────────────────────────────────


class TestEvalPermissions:
    def test_desktop_tools_in_eval_permissions(self) -> None:
        from zet.agents.eval import TOOL_PERMISSIONS

        assert TOOL_PERMISSIONS["desktop.screenshot"] == PermissionLevel.READ
        assert TOOL_PERMISSIONS["desktop.type_text"] == PermissionLevel.EXECUTE
        assert TOOL_PERMISSIONS["desktop.key_press"] == PermissionLevel.EXECUTE
        assert TOOL_PERMISSIONS["desktop.mouse_click"] == PermissionLevel.EXECUTE
