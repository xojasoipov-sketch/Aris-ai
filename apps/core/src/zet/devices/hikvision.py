"""HikvisionCamera — Hikvision ISAPI orqali snapshot (Bo'lim 8).

Hikvision kameralar to'g'ridan-to'g'ri HTTP orqali joriy kadrni JPEG
sifatida qaytaradi — RTSP oqimini ochish yoki FFmpeg/OpenCV kabi og'ir
kutubxonalar shart emas:

    GET http://<host>/ISAPI/Streaming/channels/<channel>/picture
    (HTTP Digest Authentication bilan)

Bu — foydalanuvchining aniq talabi (Hikvision kameralar) uchun eng oddiy,
eng ishonchli yo'l: `httpx.DigestAuth` allaqachon standart kutubxonada bor,
tarmoq xatolarini mock qilib test qilish oson (respx).

To'liq RTSP oqim (video, harakat aniqlash real-time) — kelajakdagi vazifa;
bu klass faqat "joriy kadrni ol" (snapshot) ehtiyojini yopadi — Vision
agentning asosiy senariylari ("Kamerada nima bo'ldi?") uchun yetarli.

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar + kamera/vision (gap-analysis #8)
    A-05 — kamera matni/tasviri UNTRUSTED
"""

from __future__ import annotations

import base64

import httpx
import structlog

from zet.devices.camera import CameraProvider, CameraSnapshot

log = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT_S = 10.0
_DEFAULT_CHANNEL = 1


class HikvisionCamera(CameraProvider):
    """Hikvision ISAPI snapshot endpointi orqali ulanish.

    Bir `HikvisionCamera` instansi — bitta fizik kamera/NVR kanaliga mos.
    `snapshot(camera_id)`dagi `camera_id` faqat log/audit uchun ishlatiladi
    (qaysi kamera so'ralganini bildiradi) — ulanish parametrlari
    konstruktorda beriladi.
    """

    def __init__(
        self,
        *,
        host: str,
        username: str,
        password: str,
        channel: int = _DEFAULT_CHANNEL,
        use_https: bool = False,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        """Args:
        host: kamera/NVR IP manzili yoki hostname (port bilan, masalan "192.168.1.64:80")
        username: ISAPI foydalanuvchi nomi (odatda "admin")
        password: ISAPI paroli
        channel: kanal raqami (NVR uchun 101, 201, ... — bitta kamera uchun 1)
        use_https: HTTPS orqali ulanish (default: HTTP — mahalliy tarmoqda odatiy)
        client: tashqi httpx klient (test uchun)
        timeout_s: so'rov timeout'i
        """
        self._host = host
        self._username = username
        self._password = password
        self._channel = channel
        self._scheme = "https" if use_https else "http"
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=f"{self._scheme}://{self._host}")
        return self._client

    async def aclose(self) -> None:
        """HTTP klientni yopish (agar biz yaratgan bo'lsak)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def snapshot(self, camera_id: str) -> CameraSnapshot:
        """ISAPI orqali joriy kadrni oladi."""
        path = f"/ISAPI/Streaming/channels/{self._channel}/picture"
        try:
            response = await self._get_client().get(
                path,
                auth=httpx.DigestAuth(self._username, self._password),
                timeout=self._timeout_s,
            )
        except httpx.TimeoutException:
            log.warning("camera.hikvision.timeout", host=self._host, camera_id=camera_id)
            return CameraSnapshot(
                camera_id=camera_id,
                source=f"hikvision:{self._host}",
                error="Kamera javob bermadi (timeout)",
            )
        except httpx.HTTPError as exc:
            log.warning("camera.hikvision.error", host=self._host, error=str(exc))
            return CameraSnapshot(
                camera_id=camera_id,
                source=f"hikvision:{self._host}",
                error=f"Ulanish xatosi: {exc}",
            )

        if response.status_code == 401:
            return CameraSnapshot(
                camera_id=camera_id,
                source=f"hikvision:{self._host}",
                error="Autentifikatsiya xato (401) — login/parolni tekshiring",
            )
        if response.status_code != 200:
            return CameraSnapshot(
                camera_id=camera_id,
                source=f"hikvision:{self._host}",
                error=f"HTTP xato ({response.status_code})",
            )
        if not response.content:
            return CameraSnapshot(
                camera_id=camera_id,
                source=f"hikvision:{self._host}",
                error="Bo'sh javob — rasm olinmadi",
            )

        log.info("camera.hikvision.snapshot", host=self._host, camera_id=camera_id)
        return CameraSnapshot(
            camera_id=camera_id,
            image_b64=base64.b64encode(response.content).decode(),
            format="jpeg",
            source=f"hikvision:{self._host}",
        )

    async def is_available(self, camera_id: str) -> bool:
        """Snapshot olib ko'rish orqali mavjudligini tekshiradi."""
        snapshot = await self.snapshot(camera_id)
        return snapshot.has_image

    async def info(self, camera_id: str) -> dict[str, str]:
        """Kamera ma'lumotlari (statik — ISAPI device-info so'ramaydi)."""
        return {
            "name": f"Hikvision ({self._host}, kanal {self._channel})",
            "model": "Hikvision ISAPI",
            "source": "hikvision",
            "host": self._host,
            "camera_id": camera_id,
        }


__all__ = ["HikvisionCamera"]
