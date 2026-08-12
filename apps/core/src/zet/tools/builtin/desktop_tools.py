"""Desktop control tool'lari (Bo'lim 11: Mac/Win boshqaruv).

Screenshot READ + UNTRUSTED. Klaviatura/sichqoncha EXECUTE + approval.

Provider pattern: `DesktopProvider` (camera bilan bir xil arxitektura).
Server headless Linux'da → `StubDesktop`. Foydalanuvchi mahalliy Mac/Win'da
ZET ishga tushirsa → `PyAutoGUIDesktop` (keyingi bosqichda qo'shiladi).

Tool ro'yxati:
    - desktop.screenshot (READ, UNTRUSTED) — butun ekranning snapshoti
    - desktop.type_text (EXECUTE, approval) — matn yozish (kursorda)
    - desktop.key_press (EXECUTE, approval) — hotkey (masalan cmd+c)
    - desktop.mouse_click (EXECUTE, approval) — koordinatada bosish

Xavfsizlik:
    - Barcha WRITE/EXECUTE tool'lar approval bilan (V-32).
    - Screenshot ma'lumoti UNTRUSTED — LLM prompt injection'iga sezgir
      (masalan "ignore all previous instructions" yozilgan ekran).
    - Runtime kollibrator kompyuter boshqarish qadamlarini cheklaydi
      (default: 10 qadam/yugurish, A-07).

Bog'liq qarorlar:
    Bo'lim 11 — Desktop control
    A-05 — screenshot UNTRUSTED
    V-32 — publish/execute approval
"""

from __future__ import annotations

from typing import Any

from zet.devices.desktop import DesktopProvider, StubDesktop
from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

# Xavfsiz tugmalar ro'yxati (pyautogui bilan mos kelishi kerak — hozircha stub)
_ALLOWED_KEYS = {
    # Modifier
    "ctrl",
    "cmd",
    "command",
    "alt",
    "option",
    "shift",
    "win",
    "super",
    "meta",
    # Harakat
    "enter",
    "return",
    "tab",
    "space",
    "backspace",
    "delete",
    "esc",
    "escape",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
    # Function
    "f1",
    "f2",
    "f3",
    "f4",
    "f5",
    "f6",
    "f7",
    "f8",
    "f9",
    "f10",
    "f11",
    "f12",
}
# Harflar/raqamlar dinamik tekshiriladi (a-z, 0-9)


def _validate_key(key: str) -> str:
    """Tugma nomini normalize + validatsiya."""
    k = key.strip().lower()
    if not k:
        raise ToolError("bo'sh tugma nomi")
    if k in _ALLOWED_KEYS:
        return k
    if len(k) == 1 and (k.isalnum() or k in "-=[]\\;',./`"):
        return k
    raise ToolError(f"noruxsat tugma: {key}")


class DesktopScreenshotTool(Tool):
    """Butun ekranning snapshoti — READ, UNTRUSTED."""

    def __init__(self, *, provider: DesktopProvider | None = None) -> None:
        self._provider = provider or StubDesktop()

    @property
    def name(self) -> str:
        return "desktop.screenshot"

    @property
    def description(self) -> str:
        return "Butun ekranning snapshotini olish (PNG, base64). UNTRUSTED chiqadi."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    async def _execute(self, _params: dict[str, Any]) -> dict[str, Any]:
        shot = await self._provider.screenshot()
        if shot.error:
            raise ToolError(shot.error)
        return {
            "image_b64": shot.image_b64,
            "width": shot.width,
            "height": shot.height,
            "format": shot.format,
            "timestamp": shot.timestamp.isoformat(),
            "source": f"desktop.screenshot ({shot.source})",
        }


class DesktopTypeTextTool(Tool):
    """Klaviaturada matn yozish (kursor joylashuvida) — EXECUTE, approval."""

    def __init__(self, *, provider: DesktopProvider | None = None) -> None:
        self._provider = provider or StubDesktop()

    @property
    def name(self) -> str:
        return "desktop.type_text"

    @property
    def description(self) -> str:
        return "Matn kursor joylashuvida yoziladi. Har bir tugma orasidagi kechikish sozlanadi."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Yoziladigan matn",
                    "minLength": 1,
                    "maxLength": 5000,
                },
                "interval_ms": {
                    "type": "integer",
                    "description": "Har tugma orasidagi kechikish (ms, default 20)",
                    "minimum": 0,
                    "maximum": 500,
                    "default": 20,
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.SYSTEM

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        text = params["text"]
        interval_ms = int(params.get("interval_ms", 20))
        result = await self._provider.type_text(text, interval_s=interval_ms / 1000.0)
        if result.error:
            raise ToolError(result.error)
        return {
            "executed": result.executed,
            "action": result.action,
            "details": result.details,
            "timestamp": result.timestamp.isoformat(),
            "source": "desktop.type_text",
        }


class DesktopKeyPressTool(Tool):
    """Klaviatura tugmalari bosish (hotkey) — EXECUTE, approval."""

    def __init__(self, *, provider: DesktopProvider | None = None) -> None:
        self._provider = provider or StubDesktop()

    @property
    def name(self) -> str:
        return "desktop.key_press"

    @property
    def description(self) -> str:
        return "Klaviatura tugmalari bosish. Ro'yxat: ['cmd','c'] = cmd+c. Xavfli tugmalar rad etiladi."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "description": "Tugmalar ro'yxati (bir vaqtda bosiladi)",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                },
            },
            "required": ["keys"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.SYSTEM

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_keys = params["keys"]
        # Har bir tugma normalize + validatsiya
        keys = [_validate_key(k) for k in raw_keys]

        result = await self._provider.key_press(keys)
        if result.error:
            raise ToolError(result.error)
        return {
            "executed": result.executed,
            "action": result.action,
            "combo": "+".join(keys),
            "details": result.details,
            "timestamp": result.timestamp.isoformat(),
            "source": "desktop.key_press",
        }


class DesktopMouseClickTool(Tool):
    """Sichqoncha bosish berilgan koordinatada — EXECUTE, approval."""

    def __init__(self, *, provider: DesktopProvider | None = None) -> None:
        self._provider = provider or StubDesktop()

    @property
    def name(self) -> str:
        return "desktop.mouse_click"

    @property
    def description(self) -> str:
        return "Sichqoncha bosish (x,y). Chap/o'ng/o'rta tugma, single/double click."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "X koordinata (piksel, chapdan)",
                    "minimum": 0,
                    "maximum": 10000,
                },
                "y": {
                    "type": "integer",
                    "description": "Y koordinata (piksel, yuqoridan)",
                    "minimum": 0,
                    "maximum": 10000,
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "default": 1,
                    "description": "1 = single, 2 = double, 3 = triple",
                },
            },
            "required": ["x", "y"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.EXECUTE

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.SYSTEM

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        x = int(params["x"])
        y = int(params["y"])
        button = params.get("button", "left")
        clicks = int(params.get("clicks", 1))

        result = await self._provider.mouse_click(x, y, button=button, clicks=clicks)
        if result.error:
            raise ToolError(result.error)
        return {
            "executed": result.executed,
            "action": result.action,
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
            "timestamp": result.timestamp.isoformat(),
            "source": "desktop.mouse_click",
        }


__all__ = [
    "DesktopKeyPressTool",
    "DesktopMouseClickTool",
    "DesktopScreenshotTool",
    "DesktopTypeTextTool",
]
