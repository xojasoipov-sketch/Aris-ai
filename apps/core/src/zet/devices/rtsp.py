"""RtspCamera — RTSP/ONVIF oqim orqali snapshot (Bo'lim 8).

NEGA. Hikvision ISAPI HTTP endpointi faqat Hikvision markali qurilma
uchun ishlaydi (jonli tekshirilgan). Dahua, Uniview, TP-Link Tapo va
boshqa RTSP standartini qo'llaydigan har qanday kamera uchun umumiy
yo'l — RTSP oqimidan bir kadr olish. `opencv-python` esa RTSP+H.264/H.265
dekoderini butun tarmoq bilan birga tayyor beradi — ffmpeg'ni alohida
o'rnatish va boshqarish shart emas.

QIYIN QAROR. `opencv-python` ~90 MB va Wheels'da OS-ga bog'liq
bo'lgan native kutubxonalar bor. Shu sabab u loyihaning MAJBURIY
bog'liqligi EMAS — `pyproject.toml`ga qo'shilmagan. Foydalanuvchi
RTSP kamerani ulashini xohlasa `pip install opencv-python-headless`
(server uchun ~50 MB, headless — GTK/Qt bog'liqligi yo'q) bajaradi.
Ilova bunday kutubxonasiz ham normal ishlaydi: `RtspCamera` yaratilishi
xato bermaydi, faqat `snapshot()` chaqirilganda tushunarli izoh
qaytariladi ("opencv-python not installed — pip install
opencv-python-headless"). Bu Hikvision yo'liga zid emas — ega ikkalasidan
birini tanlaydi.

XAVFSIZLIK. RTSP URL'ida `rtsp://user:pass@host/...` ko'rinishida parol
ochiq bo'lishi mumkin — log'ga to'liq URL yozilmaydi (parolni yashiramiz).

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar + kamera/vision (gap-analysis §6 MISSING)
    A-05 — kamera tasviri UNTRUSTED
    A-06 — capability token (kamera ruxsati)
"""

from __future__ import annotations

import asyncio
import base64
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog

from zet.devices.camera import CameraProvider, CameraSnapshot

log = structlog.get_logger(__name__)

# Modul yuklanayotgan payt `opencv-python` bo'lmasligi mumkin —
# import xatosini yutamiz, chunki paket tanlab o'rnatiladi. `snapshot`
# chaqirilganda tekshirib, tushunarli xato qaytaramiz.
try:  # pragma: no cover - import branch depends on environment
    import cv2 as _cv2_default  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _cv2_default = None  # type: ignore[assignment]


_MISSING_CV2_MSG = "opencv-python not installed — pip install opencv-python-headless"


def _redact_url(url: str) -> str:
    """RTSP URL'idan foydalanuvchi/parolni olib tashlaydi (log uchun).

    `rtsp://admin:Secret123@192.168.1.10/stream` → `rtsp://192.168.1.10/stream`.
    Log'da parol ko'rinmasin — kamera IP'si va yo'li qoladi.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class RtspCamera(CameraProvider):
    """Umumiy RTSP kamera drayveri — `opencv-python` orqali.

    Bir instansiya bitta RTSP oqimiga (bitta kamera) mos. `snapshot()`
    oqimni ochadi, birinchi yangi kadrni oladi va JPEG qilib qaytaradi.
    Uzun ushlab turmaydi — har snapshot mustaqil ulanish.

    Konstruktor argumentlari:
        rtsp_url: to'liq RTSP havola (`rtsp://...`). Foydalanuvchi/parol
            bo'lsa URL'ning o'zida bo'ladi.
        timeout_s: kadr ochish/olish uchun umumiy vaqt chegarasi.
        cv2_module: tashqi `cv2` moduli (test uchun mock qilish).
            Berilmasa — modul yuklanayotgan paytda topilgan `cv2`.
    """

    def __init__(
        self,
        *,
        rtsp_url: str,
        timeout_s: int = 10,
        cv2_module: ModuleType | None = None,
    ) -> None:
        self._rtsp_url = rtsp_url
        self._timeout_s = timeout_s
        # `cv2_module` argumenti orqali test paytida modulni almashtiramiz.
        # `object` tipida saqlaymiz — cv2 yo'q bo'lsa None; borligi
        # tekshirilgach istifoda qilamiz.
        self._cv2: Any = cv2_module if cv2_module is not None else _cv2_default

    @property
    def is_available_backend(self) -> bool:
        """`opencv-python` yuklanganmi (drayver mavjudmi)."""
        return self._cv2 is not None

    def _grab_frame_sync(self) -> tuple[bytes | None, str | None, int, int]:
        """Bloklanuvchi kadr olish — thread'da chaqiriladi.

        Returns:
            (jpeg_bytes | None, error | None, width, height).
        """
        cv2 = self._cv2
        # `cv2.CAP_FFMPEG` — RTSP oqimlari uchun barqaror backend.
        capture = cv2.VideoCapture(self._rtsp_url, cv2.CAP_FFMPEG)
        try:
            if not capture.isOpened():
                return None, "RTSP oqim ochilmadi (URL yoki tarmoq)", 0, 0
            success, frame = capture.read()
            if not success or frame is None:
                return None, "Kadr olinmadi (bo'sh oqim yoki dekoder xatosi)", 0, 0
            encoded, buffer = cv2.imencode(".jpg", frame)
            if not encoded:
                return None, "Kadrni JPEG'ga kodlab bo'lmadi", 0, 0
            height, width = frame.shape[0], frame.shape[1]
            return bytes(buffer.tobytes()), None, int(width), int(height)
        finally:
            capture.release()

    async def snapshot(self, camera_id: str) -> CameraSnapshot:
        """RTSP oqimidan joriy kadrni oladi."""
        source = f"rtsp:{_redact_url(self._rtsp_url)}"
        if self._cv2 is None:
            log.warning("camera.rtsp.snapshot", camera_id=camera_id, error="no-cv2")
            return CameraSnapshot(
                camera_id=camera_id,
                source=source,
                error=_MISSING_CV2_MSG,
            )

        log.info("camera.rtsp.snapshot", camera_id=camera_id, source=source)
        try:
            jpeg, error, width, height = await asyncio.wait_for(
                asyncio.to_thread(self._grab_frame_sync),
                timeout=float(self._timeout_s),
            )
        except TimeoutError:
            log.warning("camera.rtsp.timeout", camera_id=camera_id, source=source)
            return CameraSnapshot(
                camera_id=camera_id,
                source=source,
                error=f"RTSP oqim {self._timeout_s}s ichida javob bermadi",
            )
        except Exception as exc:
            log.warning("camera.rtsp.error", camera_id=camera_id, error=str(exc))
            return CameraSnapshot(
                camera_id=camera_id,
                source=source,
                error=f"RTSP xatosi: {exc}",
            )

        if jpeg is None:
            return CameraSnapshot(
                camera_id=camera_id,
                source=source,
                error=error or "Noma'lum RTSP xatosi",
            )

        return CameraSnapshot(
            camera_id=camera_id,
            image_b64=base64.b64encode(jpeg).decode(),
            width=width,
            height=height,
            format="jpeg",
            source=source,
        )

    async def is_available(self, camera_id: str) -> bool:
        """Snapshot olib ko'rish orqali mavjudligini tekshiradi."""
        snapshot = await self.snapshot(camera_id)
        return snapshot.has_image

    async def info(self, camera_id: str) -> dict[str, str]:
        """Kamera ma'lumotlari (statik — RTSP metadata so'ramaydi)."""
        return {
            "name": f"RTSP ({_redact_url(self._rtsp_url)})",
            "model": "Generic RTSP",
            "source": "rtsp",
            "camera_id": camera_id,
            "backend": "opencv" if self._cv2 is not None else "unavailable",
        }


__all__ = ["RtspCamera"]
