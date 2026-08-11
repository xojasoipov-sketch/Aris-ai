"""Kamera interfeysi — snapshot, RTSP, EZVIZ (Bo'lim 8).

ICameraProvider abstraktsiyasi — turli kamera tizimlari uchun yagona interfeys.
Produksiyada RTSP/EZVIZ drayverlar bilan almashtiriladi.

Kamera turlari:
    - StubCamera — test va development uchun (haqiqiy kameraga ulanmaydi)
    - RTSPCamera — RTSP/ONVIF orqali (Hikvision, Dahua) — produksiya
    - EZVIZCamera — EZVIZ Cloud API orqali — produksiya

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar + kamera/vision
    A-06 — capability token (kameraga ruxsat)
    A-05 — kamera matni UNTRUSTED
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class CameraSnapshot(BaseModel, frozen=True):
    """Kamera snapshot natijasi.

    Rasmni base64 kodlangan holda saqlaydi.
    Vision agent bu natijani tahlil qiladi.
    """

    camera_id: str
    """Kamera identifikatori."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Snapshot olingan vaqt."""

    image_b64: str = ""
    """Rasm base64 kodlangan (JPEG/PNG). Bo'sh = xato yoki stub."""

    width: int = 0
    """Rasm kengligi (piksel)."""

    height: int = 0
    """Rasm balandligi (piksel)."""

    format: str = "jpeg"
    """Rasm formati (jpeg, png)."""

    source: str = ""
    """Kamera manbasi (masalan: 'rtsp://...', 'ezviz', 'stub')."""

    error: str | None = None
    """Xato xabari (agar snapshot olinmagan bo'lsa)."""

    @property
    def has_image(self) -> bool:
        """Rasm mavjudmi."""
        return bool(self.image_b64) and self.error is None

    @property
    def image_bytes(self) -> bytes:
        """Base64 dan baytlarga.

        Returns:
            Rasm baytlari (bo'sh agar rasm yo'q).
        """
        if not self.image_b64:
            return b""
        return base64.b64decode(self.image_b64)

    @property
    def size_kb(self) -> float:
        """Rasm hajmi KB da."""
        if not self.image_b64:
            return 0.0
        return len(self.image_b64) * 3 / 4 / 1024


class CameraProvider(ABC):
    """Kamera provayder interfeysi (Abstract).

    Har bir kamera turi (RTSP, EZVIZ, Stub) bu interfeysni implement qiladi.

    Metodlar:
        snapshot() — joriy kadrni olish
        is_available() — kamera ulanganmi
        info() — kamera ma'lumotlari
    """

    @abstractmethod
    async def snapshot(self, camera_id: str) -> CameraSnapshot:
        """Kameradan joriy kadrni olish.

        Args:
            camera_id: Kamera identifikatori.

        Returns:
            CameraSnapshot — rasm yoki xato.
        """

    @abstractmethod
    async def is_available(self, camera_id: str) -> bool:
        """Kamera ulanganmi va ishlayaptimi.

        Args:
            camera_id: Kamera identifikatori.

        Returns:
            True agar kamera javob bersa.
        """

    @abstractmethod
    async def info(self, camera_id: str) -> dict[str, str]:
        """Kamera ma'lumotlari.

        Args:
            camera_id: Kamera identifikatori.

        Returns:
            Dict — nomi, modeli, manzili va boshqa ma'lumotlar.
        """


class StubCamera(CameraProvider):
    """Stub kamera — test va development uchun.

    Haqiqiy kameraga ulanmaydi. Sintetik snapshot qaytaradi.
    Produksiyada RTSP yoki EZVIZ bilan almashtiriladi.
    """

    # 1x1 piksel oq JPEG (minimal haqiqiy rasm)
    _STUB_IMAGE_B64: str = (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAs"
        "LDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zND"
        "L/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAx"
        "EB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAw"
        "IEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAk"
        "M2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZW"
        "ZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2"
        "t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8"
        "QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBA"
        "cFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLR"
        "ChYkNOEl8RcYI4Q/RFhHRUYnJCk6ODA5N0RXV1hkdHN0d3h5eoKEhYaHiI"
        "mKkpSVlpeYmZqio6SlpqeoqaqxsrO0tba3uLm6wsPExcbHyMnK0dLT1NXW"
        "19jZ2uHi4+Tl5ufo6erw8fLz9PX29/j5+v/aAAwDAQACEQMRAD8A/9k="
    )

    def __init__(self, *, available: bool = True) -> None:
        """Args:
        available: Stub kamera 'mavjud' deb hisoblanadimi.
        """
        self._available = available
        self._snapshot_count = 0

    async def snapshot(self, camera_id: str) -> CameraSnapshot:
        """Stub snapshot — sintetik rasm qaytaradi."""
        if not self._available:
            log.warning("camera.stub.unavailable", camera_id=camera_id)
            return CameraSnapshot(
                camera_id=camera_id,
                source="stub",
                error="Kamera mavjud emas (stub unavailable)",
            )

        self._snapshot_count += 1
        log.info(
            "camera.stub.snapshot",
            camera_id=camera_id,
            count=self._snapshot_count,
        )
        return CameraSnapshot(
            camera_id=camera_id,
            image_b64=self._STUB_IMAGE_B64,
            width=1,
            height=1,
            format="jpeg",
            source="stub",
        )

    async def is_available(self, _camera_id: str) -> bool:
        """Stub kamera mavjudligi."""
        return self._available

    async def info(self, camera_id: str) -> dict[str, str]:
        """Stub kamera ma'lumotlari."""
        return {
            "name": f"Stub Camera ({camera_id})",
            "model": "StubCamera v1",
            "source": "stub",
            "status": "available" if self._available else "unavailable",
        }

    @property
    def snapshot_count(self) -> int:
        """Olingan snapshotlar soni (test uchun)."""
        return self._snapshot_count
