"""Qurilmalar moduli — telefon, desktop, kamera (Bo'lim 8).

Komponentlar:
    - DeviceRegistry: qurilmalar ro'yxati va holatini boshqarish
    - ICameraProvider: kamera interfeysi (Mock, RTSP, EZVIZ)
    - CapabilityToken: qurilma ruxsat tokeni (A-06)

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar + kamera/vision
    A-06 — capability token asosida ruxsat
"""

from zet.devices.camera import CameraProvider, CameraSnapshot, StubCamera
from zet.devices.registry import CapabilityToken, Device, DeviceRegistry, DeviceType

__all__ = [
    "CameraProvider",
    "CameraSnapshot",
    "CapabilityToken",
    "Device",
    "DeviceRegistry",
    "DeviceType",
    "StubCamera",
]
