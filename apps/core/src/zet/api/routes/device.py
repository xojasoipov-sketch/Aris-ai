"""Qurilma API endpoint'lari (Bo'lim 8, A-06).

    POST   /api/v1/devices           — yangi qurilma ro'yxatga olish
    GET    /api/v1/devices           — qurilmalar ro'yxati (ixtiyoriy tur filtri)
    GET    /api/v1/devices/{id}      — bitta qurilma
    POST   /api/v1/devices/{id}/status — onlaynlikni yangilash
    DELETE /api/v1/devices/{id}      — qurilma va uning tokenlarini o'chirish

Ilgari `DeviceRegistry` (`devices/registry.py`) hech qanday route yoki
tool bilan bog'lanmagan edi (GAP_ANALYSIS #12: "qurilgan-u ulanmagan").
iPhone/Mac boshqaruvi shu API'ga tayanadi — qurilma ro'yxatga oladi,
token oladi, so'ng har HTTP chaqiruvida `capability_token` xesh bo'yicha
tekshiriladi.

Xavfsizlik izohi — TOKEN JAVOBI:
    `POST /devices` javobida `token` maydoni **xom qiymat** — u faqat
    shu javobda bir marta ko'rinadi. Foydalanuvchi uni o'zi qurilmaga
    ko'chirishi kerak; keyin uni qayta olib bo'lmaydi (DB'da faqat
    xesh saqlanadi, `devices/repository.py` docstringiga qarang).

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar
    A-06 — capability token
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from zet.api.deps import get_device_repository
from zet.devices.registry import DeviceType
from zet.devices.repository import DeviceDBRepository, DeviceRecord

router = APIRouter(prefix="/devices", tags=["devices"])


# ── Pydantic modellari ────────────────────────────────────────────


class DeviceCreateRequest(BaseModel):
    """Yangi qurilma ro'yxatga olish so'rovi."""

    name: str = Field(..., min_length=1, max_length=128)
    device_type: DeviceType
    platform: str = Field(default="", max_length=32)
    model: str = Field(default="", max_length=128)
    capabilities: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    label: str = ""


class DeviceStatusUpdateRequest(BaseModel):
    """Onlayn holatni yangilash so'rovi."""

    online: bool


class DeviceResponse(BaseModel):
    """Qurilma javob modeli."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    device_type: DeviceType
    platform: str
    model: str
    ip_address: str
    online: bool
    last_seen: datetime | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DeviceRegisteredResponse(BaseModel):
    """`POST /devices` javobi — qurilma + XOM token (bir marta)."""

    device: DeviceResponse
    token: str
    """Xom capability tokeni — FAQAT SHU JAVOBDA ko'rinadi (modul izohiga qarang)."""


def _record_to_response(record: DeviceRecord) -> DeviceResponse:
    return DeviceResponse(
        id=record.id,
        name=record.name,
        device_type=record.device_type,
        platform=record.platform,
        model=record.model,
        ip_address=record.ip_address,
        online=record.online,
        last_seen=record.last_seen,
        meta=record.meta,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ── Endpoint'lar ──────────────────────────────────────────────────


@router.post("", response_model=DeviceRegisteredResponse, status_code=201)
async def create_device(
    request: DeviceCreateRequest,
    repo: DeviceDBRepository = Depends(get_device_repository),
) -> DeviceRegisteredResponse:
    """Yangi qurilma ro'yxatga oladi va unga capability token beradi.

    Xom token javobda **bir marta** ko'rinadi (`token` maydoni).
    Uni yozib olishni unutmang — DB'da faqat xesh saqlanadi.
    """
    record, raw_token = await repo.register(
        name=request.name,
        device_type=request.device_type,
        platform=request.platform,
        model=request.model,
        capabilities=request.capabilities,
        expires_at=request.expires_at,
        label=request.label,
    )
    return DeviceRegisteredResponse(
        device=_record_to_response(record),
        token=raw_token,
    )


@router.get("", response_model=list[DeviceResponse])
async def list_devices(
    device_type: DeviceType | None = None,
    repo: DeviceDBRepository = Depends(get_device_repository),
) -> list[DeviceResponse]:
    """Qurilmalar ro'yxati (ixtiyoriy tur bo'yicha filtr)."""
    records = await repo.list(device_type=device_type)
    return [_record_to_response(r) for r in records]


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str,
    repo: DeviceDBRepository = Depends(get_device_repository),
) -> DeviceResponse:
    """Bitta qurilma ma'lumotlari."""
    record = await repo.get(device_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Qurilma topilmadi")
    return _record_to_response(record)


@router.post("/{device_id}/status", response_model=DeviceResponse)
async def update_device_status(
    device_id: str,
    request: DeviceStatusUpdateRequest,
    repo: DeviceDBRepository = Depends(get_device_repository),
) -> DeviceResponse:
    """Qurilma onlaynligini yangilash. `online=True` bo'lsa `last_seen` ham yangilanadi."""
    record = await repo.update_status(device_id, online=request.online)
    if record is None:
        raise HTTPException(status_code=404, detail="Qurilma topilmadi")
    return _record_to_response(record)


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: str,
    repo: DeviceDBRepository = Depends(get_device_repository),
) -> None:
    """Qurilmani (va uning barcha tokenlarini) o'chiradi.

    Tokenlar avval bekor qilinadi (audit uchun `revoked_at` qo'yiladi),
    keyin qurilma o'chirilib, CASCADE orqali tokenlar ham yo'qoladi.
    """
    deleted = await repo.delete(device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Qurilma topilmadi")
