"""camera.snapshot — kamera kadrini olish (Bo'lim 8, Vision).

`CameraProvider` orqali ishlaydi (`StubCamera`/`RTSPCamera`/`EZVIZCamera`,
`zet/devices/camera.py`). Natija `AgentRuntime` tomonidan avtomatik
`ImageBlock`ga aylantirilib, vision-capable modelga yuboriladi.

Ilgari vision agentning `tool_allowlist`ida kamera tool'i umuman yo'q edi
(gap-analysis #8/#11) — hatto `StubCamera` ham hech qayerdan chaqirilmasdi.

Xavfsizlik:
    - permission = READ
    - output UNTRUSTED — kamera kadridagi matn/OCR tashqi manba (A-05)

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar + kamera/vision
    A-05 — kamera matni UNTRUSTED
    A-06 — capability token (kelajakda real kameralar uchun)
"""

from __future__ import annotations

from typing import Any

from zet.devices.camera import CameraProvider, StubCamera
from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError


class CameraSnapshotTool(Tool):
    """Kameradan joriy kadrni oladi — natija vision modelga yuboriladi.

    `AgentRuntime` bu tool natijasidagi rasmni avtomatik aniqlaydi
    (`output["has_image"]` + `output["image_b64"]`) va keyingi LLM
    chaqiruviga `ImageBlock` sifatida qo'shadi.
    """

    def __init__(self, *, provider: CameraProvider | None = None) -> None:
        self._provider = provider or StubCamera()

    @property
    def name(self) -> str:
        return "camera.snapshot"

    @property
    def description(self) -> str:
        return "Kameradan joriy kadrni olish — natija vision tahlili uchun (UNTRUSTED)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "camera_id": {
                    "type": "string",
                    "description": "Kamera identifikatori",
                },
            },
            "required": ["camera_id"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return False

    @property
    def timeout_s(self) -> int:
        return 20

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        camera_id = params["camera_id"]
        snapshot = await self._provider.snapshot(camera_id)

        if not snapshot.has_image:
            raise ToolError(snapshot.error or f"Kamera '{camera_id}' snapshot bera olmadi")

        media_type = "image/png" if snapshot.format == "png" else "image/jpeg"
        return {
            "camera_id": snapshot.camera_id,
            "has_image": True,
            "image_b64": snapshot.image_b64,
            "media_type": media_type,
            "width": snapshot.width,
            "height": snapshot.height,
            "timestamp": snapshot.timestamp.isoformat(),
            "source": snapshot.source,
        }


__all__ = ["CameraSnapshotTool"]
