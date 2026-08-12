"""Desktop qurilma interfeysi — ekran + klaviatura + sichqoncha (Bo'lim 11).

`DesktopProvider` abstraktsiyasi — turli implementatsiyalar uchun yagona
interfeys. Server ZET Linux'da ishlayotgan bo'lsa, `StubDesktop` (fake)
qaytariladi; ZET foydalanuvchining shaxsiy Mac/Windows kompyuteri ustida
ishlayotgan bo'lsa, `PyAutoGUIDesktop` haqiqiy GUI'ga ta'sir qiladi.

Qurilma turlari:
    - StubDesktop — test/development uchun, hech nima qilmaydi
    - PyAutoGUIDesktop — pyautogui + mss (haqiqiy, mahalliy ish stoli)

Xavfsizlik (kritik!):
    - Screenshot READ + UNTRUSTED (A-05): ekran mazmuni tashqi kelib
      chiquvchi bo'lishi mumkin (parolli maydonlar, kredit kartalar, ...)
    - key_press / mouse_click / type_text = EXECUTE + approval majburiy
      (V-32) — bu tool'lar butun kompyuterni boshqara oladi
    - A-07: qadam sonini cheklash — bir agent 10 dan ortiq klaviatura
      qadamini bir yugurishda amalga oshira olmaydi (Runtime tomonida)

Bog'liq qarorlar:
    Bo'lim 11 — Desktop control (mac/Win)
    A-05 — screenshot UNTRUSTED
    V-32 — publish/execute har doim approval
    A-07 — avtomatlashtirish tormozlari
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class Screenshot(BaseModel, frozen=True):
    """Ekran snapshoti."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    image_b64: str = ""
    """Rasm base64 (PNG). Bo'sh = xato yoki stub."""
    width: int = 0
    height: int = 0
    format: str = "png"
    source: str = ""
    error: str | None = None

    @property
    def has_image(self) -> bool:
        return bool(self.image_b64) and self.error is None

    @property
    def image_bytes(self) -> bytes:
        if not self.image_b64:
            return b""
        return base64.b64decode(self.image_b64)


class DesktopActionResult(BaseModel, frozen=True):
    """Klaviatura/sichqoncha harakati natijasi."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action: str
    """Harakat turi: 'type_text', 'key_press', 'mouse_click', 'mouse_move'."""
    executed: bool = False
    details: dict[str, str | int] = Field(default_factory=dict)
    error: str | None = None


class DesktopProvider(ABC):
    """Desktop qurilma provayder interfeysi."""

    @abstractmethod
    async def screenshot(self) -> Screenshot:
        """Butun ekranning snapshoti."""

    @abstractmethod
    async def type_text(self, text: str, interval_s: float = 0.02) -> DesktopActionResult:
        """Matn yozish (kursor joylashuvida).

        Args:
            text: Yoziladigan matn.
            interval_s: Har bir tugmalar orasidagi kechikish (default 20 ms).
        """

    @abstractmethod
    async def key_press(self, keys: list[str]) -> DesktopActionResult:
        """Klaviatura tugmalari bosish (birgalikda = hotkey).

        Args:
            keys: Tugmalar (masalan ['cmd', 'c']). Bir tugma → oddiy bosish.
                Ko'p → birga bosiladi.
        """

    @abstractmethod
    async def mouse_click(
        self, x: int, y: int, *, button: str = "left", clicks: int = 1
    ) -> DesktopActionResult:
        """Sichqoncha bosish berilgan koordinatada.

        Args:
            x, y: Ekran koordinatalari (piksel, chapdan-yuqoridan).
            button: 'left', 'right', 'middle'.
            clicks: Nechta bosish (2 = double-click).
        """

    @abstractmethod
    async def mouse_move(self, x: int, y: int, *, duration_s: float = 0.1) -> DesktopActionResult:
        """Sichqonchani berilgan koordinataga siljitish."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Desktop drayveri mavjudmi (GUI muhit borligi)."""


class StubDesktop(DesktopProvider):
    """Stub desktop — hech qanday haqiqiy harakat qilmaydi.

    Ishlatiladi:
        - Server muhitida (headless Linux) — GUI yo'q
        - Test'larda — deterministik va xavfsiz
        - Foydalanuvchi mahalliy ish stolida ishga tushirmaguncha default
    """

    # 1x1 shaffof PNG (minimal haqiqiy rasm)
    _STUB_PNG_B64: str = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="

    def __init__(self, *, available: bool = False) -> None:
        """Args:
        available: Stub 'mavjud' deb hisoblanadimi (default: yo'q).
            Test'larda `True` bering.
        """
        self._available = available
        self._action_count = 0

    async def screenshot(self) -> Screenshot:
        if not self._available:
            return Screenshot(
                source="stub",
                error="Desktop mavjud emas (stub unavailable)",
            )
        self._action_count += 1
        log.info("desktop.stub.screenshot", count=self._action_count)
        return Screenshot(
            image_b64=self._STUB_PNG_B64,
            width=1,
            height=1,
            format="png",
            source="stub",
        )

    async def type_text(self, text: str, interval_s: float = 0.02) -> DesktopActionResult:
        if not self._available:
            return DesktopActionResult(action="type_text", error="stub unavailable")
        self._action_count += 1
        log.info("desktop.stub.type_text", chars=len(text), count=self._action_count)
        return DesktopActionResult(
            action="type_text",
            executed=True,
            details={"chars": len(text), "interval_ms": int(interval_s * 1000)},
        )

    async def key_press(self, keys: list[str]) -> DesktopActionResult:
        if not self._available:
            return DesktopActionResult(action="key_press", error="stub unavailable")
        self._action_count += 1
        log.info("desktop.stub.key_press", keys="+".join(keys), count=self._action_count)
        return DesktopActionResult(
            action="key_press",
            executed=True,
            details={"combo": "+".join(keys), "n_keys": len(keys)},
        )

    async def mouse_click(
        self, x: int, y: int, *, button: str = "left", clicks: int = 1
    ) -> DesktopActionResult:
        if not self._available:
            return DesktopActionResult(action="mouse_click", error="stub unavailable")
        self._action_count += 1
        log.info("desktop.stub.mouse_click", x=x, y=y, button=button, clicks=clicks)
        return DesktopActionResult(
            action="mouse_click",
            executed=True,
            details={"x": x, "y": y, "button": button, "clicks": clicks},
        )

    async def mouse_move(self, x: int, y: int, *, duration_s: float = 0.1) -> DesktopActionResult:
        if not self._available:
            return DesktopActionResult(action="mouse_move", error="stub unavailable")
        self._action_count += 1
        log.info("desktop.stub.mouse_move", x=x, y=y)
        return DesktopActionResult(
            action="mouse_move",
            executed=True,
            details={"x": x, "y": y, "duration_ms": int(duration_s * 1000)},
        )

    async def is_available(self) -> bool:
        return self._available

    @property
    def action_count(self) -> int:
        return self._action_count


__all__ = [
    "DesktopActionResult",
    "DesktopProvider",
    "Screenshot",
    "StubDesktop",
]
