"""Qurilmalar registri — ro'yxat, holat, token (Bo'lim 8).

DeviceRegistry — qurilmalarni ro'yxatga olish va boshqarish.
CapabilityToken — qurilma ruxsat tokeni (A-06).

Qurilma turlari:
    - PHONE — Android telefon (companion app)
    - DESKTOP — macOS/Windows daemon
    - CAMERA — IP kamera (Hikvision RTSP/EZVIZ)
    - IOT — boshqa qurilmalar

Bog'liq qarorlar:
    A-06 — capability token
    Bo'lim 8 — qurilmalar
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class DeviceType(StrEnum):
    """Qurilma turi."""

    PHONE = "phone"
    DESKTOP = "desktop"
    CAMERA = "camera"
    IOT = "iot"


class CapabilityToken(BaseModel, frozen=True):
    """Qurilma ruxsat tokeni (A-06).

    Har bir qurilma o'ziga xos token oladi.
    Token orqali faqat ruxsat etilgan amallar bajariladi.
    """

    token: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    """Token qiymati (unikal, kriptografik xavfsiz)."""

    device_id: str
    """Bog'liq qurilma ID."""

    capabilities: frozenset[str] = frozenset()
    """Ruxsat etilgan imkoniyatlar (masalan: 'camera.snapshot', 'notify')."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    expires_at: datetime | None = None
    """Muddati tugash vaqti (None = cheksiz)."""

    @property
    def is_expired(self) -> bool:
        """Token muddati tugaganmi."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    def has_capability(self, capability: str) -> bool:
        """Token berilgan imkoniyatga ega ekanligini tekshirish."""
        if self.is_expired:
            return False
        return capability in self.capabilities


class Device(BaseModel, frozen=True):
    """Qurilma yozuvi."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal qurilma ID."""

    name: str
    """Qurilma nomi (masalan: 'iPhone 15', 'MacBook Pro')."""

    device_type: DeviceType
    """Qurilma turi."""

    platform: str = ""
    """Platforma (masalan: 'android', 'macos', 'windows', 'hikvision')."""

    model: str = ""
    """Model nomi."""

    ip_address: str = ""
    """IP manzil (agar mavjud bo'lsa)."""

    online: bool = False
    """Qurilma onlinedaligi."""

    last_seen: datetime | None = None
    """Oxirgi aloqa vaqti."""

    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Ro'yxatga olingan vaqt."""

    metadata: dict[str, str] = Field(default_factory=dict)
    """Qo'shimcha ma'lumotlar."""


class DeviceRegistry:
    """Qurilmalar registri — in-memory (Bo'lim 8 lean).

    Produksiyada DB bilan almashtiriladi.
    """

    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}
        self._tokens: dict[str, CapabilityToken] = {}

    def register(
        self,
        *,
        name: str,
        device_type: DeviceType,
        platform: str = "",
        model: str = "",
        capabilities: frozenset[str] | None = None,
    ) -> tuple[Device, CapabilityToken]:
        """Yangi qurilma ro'yxatga olish.

        Returns:
            (Device, CapabilityToken) — qurilma va uning tokeni
        """
        device = Device(
            name=name,
            device_type=device_type,
            platform=platform,
            model=model,
        )
        self._devices[device.id] = device

        caps = capabilities or frozenset()
        token = CapabilityToken(device_id=device.id, capabilities=caps)
        self._tokens[token.token] = token

        log.info(
            "device.registered",
            id=device.id,
            name=name,
            type=device_type.value,
            capabilities=list(caps),
        )
        return device, token

    def get(self, device_id: str) -> Device | None:
        """Qurilma olish."""
        return self._devices.get(device_id)

    def list_devices(self, device_type: DeviceType | None = None) -> list[Device]:
        """Qurilmalar ro'yxati."""
        if device_type is None:
            return list(self._devices.values())
        return [d for d in self._devices.values() if d.device_type == device_type]

    def update_status(self, device_id: str, *, online: bool) -> Device | None:
        """Qurilma holatini yangilash."""
        old = self._devices.get(device_id)
        if old is None:
            return None

        updated = Device(
            id=old.id,
            name=old.name,
            device_type=old.device_type,
            platform=old.platform,
            model=old.model,
            ip_address=old.ip_address,
            online=online,
            last_seen=datetime.now(UTC) if online else old.last_seen,
            registered_at=old.registered_at,
            metadata=old.metadata,
        )
        self._devices[device_id] = updated
        log.info("device.status_updated", id=device_id, online=online)
        return updated

    def validate_token(self, token_value: str, capability: str) -> bool:
        """Tokenni validatsiya qilish — ruxsat bormi.

        Args:
            token_value: Token qiymati
            capability: Tekshiriladigan imkoniyat

        Returns:
            True agar token yaroqli va imkoniyat ruxsat etilgan
        """
        token = self._tokens.get(token_value)
        if token is None:
            return False
        return token.has_capability(capability)

    def revoke_token(self, token_value: str) -> bool:
        """Tokenni bekor qilish.

        Returns:
            True agar token topildi va bekor qilindi
        """
        if token_value in self._tokens:
            del self._tokens[token_value]
            log.info("device.token_revoked", token=token_value[:8] + "...")
            return True
        return False

    @property
    def stats(self) -> dict[str, int]:
        """Registr statistikasi."""
        devices = list(self._devices.values())
        return {
            "total_devices": len(devices),
            "online_devices": sum(1 for d in devices if d.online),
            "phones": sum(1 for d in devices if d.device_type == DeviceType.PHONE),
            "desktops": sum(1 for d in devices if d.device_type == DeviceType.DESKTOP),
            "cameras": sum(1 for d in devices if d.device_type == DeviceType.CAMERA),
            "active_tokens": len(self._tokens),
        }
