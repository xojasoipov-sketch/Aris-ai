"""Kamera endpoint'lari (Z48.3).

    GET  /api/v1/camera            — kamera sozlanganmi va qaysi
    POST /api/v1/camera/snapshot   — haqiqiy kadr olish

NEGA KERAK BO'LDI.

`/camera` sahifasi butunlay o'ylab topilgan edi: OLTITA kamera nomi
("Old eshik", "Hovli", "Garaj", "Ofis", "Ombor", "Turargoh"), to'rtta
preset, PTZ tugmalari va uchta tab — hech biri hech qayerga
ulanmagan, hammasi faqat tovush chalardi. Sozlamada esa BITTA
Hikvision kanali bor xolos.

`camera.snapshot` tooli haqiqatan ishlaydi (agent uni chaqira oladi),
lekin ega interfeys orqali kadrni ko'ra olmasdi.

STUB QAYTARILMAYDI. Hikvision sozlanmagan bo'lsa `StubCamera` 1x1
piksel oq JPEG beradi. Uni sahifaga chiqarish "kamera ishlayapti"
degan yolg'on bo'lardi, shuning uchun sozlanmagan holatda endpoint
ochiq 503 qaytaradi.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from zet.api.deps import get_config, get_tool_registry
from zet.config import Settings
from zet.domain.enums import PermissionLevel
from zet.tools.registry import ToolRegistry

router = APIRouter(prefix="/camera", tags=["camera"])

DEFAULT_CAMERA_ID = "main"
"""Sozlamada bitta kanal bor — ko'p kamerali NVR alohida ish."""


class CameraInfoResponse(BaseModel):
    configured: bool
    """Hikvision host/login/parol to'liq berilganmi."""

    camera_id: str
    label: str
    detail: str
    """Ega o'qiydigan izoh — sozlanmagan bo'lsa NIMA qilish kerakligi."""


class SnapshotResponse(BaseModel):
    camera_id: str
    image_b64: str
    media_type: str
    width: int
    height: int
    timestamp: str
    source: str
    """`hikvision` yoki `stub` — ega manbani ko'rib tursin."""


def _is_configured(settings: Settings) -> bool:
    return bool(
        settings.hikvision_host and settings.hikvision_username and settings.hikvision_password
    )


@router.get("", response_model=CameraInfoResponse)
def camera_info(settings: Settings = Depends(get_config)) -> CameraInfoResponse:
    """Kamera sozlanganmi — sahifa shu javobga qarab chiziladi."""
    configured = _is_configured(settings)
    return CameraInfoResponse(
        configured=configured,
        camera_id=DEFAULT_CAMERA_ID,
        label=(
            f"Hikvision · {settings.hikvision_host} · kanal {settings.hikvision_channel}"
            if configured
            else "Kamera ulanmagan"
        ),
        detail=(
            "Kadr olish uchun 'Kadr olish' tugmasini bosing."
            if configured
            else (
                "ZET_HIKVISION_HOST, ZET_HIKVISION_USERNAME va ZET_HIKVISION_PASSWORD sozlanmagan."
            )
        ),
    )


@router.post("/snapshot", response_model=SnapshotResponse)
async def take_snapshot(
    settings: Settings = Depends(get_config),
    registry: ToolRegistry = Depends(get_tool_registry),
) -> SnapshotResponse:
    """Kameradan HAQIQIY kadr oladi.

    Sozlanmagan bo'lsa 503 — stub rasm qaytarish "kamera ishlayapti"
    degan yolg'on bo'lardi.
    """
    if not _is_configured(settings):
        raise HTTPException(status_code=503, detail="Kamera sozlanmagan")

    result = await registry.execute(
        "camera.snapshot",
        {"camera_id": DEFAULT_CAMERA_ID},
        caller_permission=PermissionLevel.READ,
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error or "Kadr olinmadi")

    output = result.output or {}
    return SnapshotResponse(
        camera_id=output.get("camera_id", DEFAULT_CAMERA_ID),
        image_b64=output.get("image_b64", ""),
        media_type=output.get("media_type", "image/jpeg"),
        width=output.get("width", 0),
        height=output.get("height", 0),
        timestamp=output.get("timestamp", ""),
        source=output.get("source", ""),
    )
