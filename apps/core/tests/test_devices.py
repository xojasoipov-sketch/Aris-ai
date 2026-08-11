"""Bo'lim 8 testlari — Qurilmalar, Kamera, Vision Agent.

Test guruhlari:
    1. DeviceType enum
    2. CapabilityToken — yaratish, ekspiratsiya, imkoniyat tekshirish
    3. Device — yaratish, maydonlar
    4. DeviceRegistry — register, get, list, update_status, validate_token, revoke, stats
    5. CameraSnapshot — yaratish, has_image, image_bytes, size_kb
    6. StubCamera — snapshot, availability, info, unavailable
    7. CameraProvider — ABC enforced
    8. Vision Agent — spec, tools, brakes, prompt, eval, frozen
    9. Devices __init__ — exports
    10. Builtin agents — 9 specs (updated count)
    11. Xavfsizlik invariantlari
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

from zet.agents.builtin import (
    CEO_AGENT_SPEC,
    DEVELOPER_AGENT_SPEC,
    FINANCE_AGENT_SPEC,
    OPERATIONS_AGENT_SPEC,
    RESEARCH_AGENT_SPEC,
    SALES_AGENT_SPEC,
    SMM_AGENT_SPEC,
    SUPPORT_AGENT_SPEC,
    VISION_AGENT_SPEC,
)
from zet.agents.builtin.vision import VISION_AGENT_SPEC as DIRECT_VISION_SPEC
from zet.agents.eval import EvalRunner
from zet.devices import (
    CameraProvider,
    CameraSnapshot,
    CapabilityToken,
    Device,
    DeviceRegistry,
    DeviceType,
    StubCamera,
)
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel

# ── 1. DeviceType ────────────────────────────────────────────────


class TestDeviceType:
    def test_values(self) -> None:
        assert DeviceType.PHONE == "phone"
        assert DeviceType.DESKTOP == "desktop"
        assert DeviceType.CAMERA == "camera"
        assert DeviceType.IOT == "iot"

    def test_all_members(self) -> None:
        assert len(DeviceType) == 4


# ── 2. CapabilityToken ──────────────────────────────────────────


class TestCapabilityToken:
    def test_create_default(self) -> None:
        token = CapabilityToken(device_id="dev1")
        assert token.device_id == "dev1"
        assert len(token.token) > 10
        assert token.capabilities == frozenset()
        assert token.expires_at is None
        assert not token.is_expired

    def test_create_with_capabilities(self) -> None:
        caps = frozenset({"camera.snapshot", "notify"})
        token = CapabilityToken(device_id="dev2", capabilities=caps)
        assert token.capabilities == caps
        assert token.has_capability("camera.snapshot")
        assert token.has_capability("notify")
        assert not token.has_capability("admin")

    def test_expired_token(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        token = CapabilityToken(
            device_id="dev3",
            capabilities=frozenset({"camera.snapshot"}),
            expires_at=past,
        )
        assert token.is_expired
        assert not token.has_capability("camera.snapshot")

    def test_not_expired_yet(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1)
        token = CapabilityToken(
            device_id="dev4",
            capabilities=frozenset({"camera.snapshot"}),
            expires_at=future,
        )
        assert not token.is_expired
        assert token.has_capability("camera.snapshot")

    def test_no_expiry_means_valid(self) -> None:
        token = CapabilityToken(
            device_id="dev5",
            capabilities=frozenset({"notify"}),
            expires_at=None,
        )
        assert not token.is_expired
        assert token.has_capability("notify")

    def test_frozen(self) -> None:
        token = CapabilityToken(device_id="dev6")
        with pytest.raises(Exception):  # noqa: B017
            token.device_id = "other"  # type: ignore[misc]

    def test_unique_tokens(self) -> None:
        t1 = CapabilityToken(device_id="a")
        t2 = CapabilityToken(device_id="b")
        assert t1.token != t2.token


# ── 3. Device ────────────────────────────────────────────────────


class TestDevice:
    def test_create_minimal(self) -> None:
        dev = Device(name="My Phone", device_type=DeviceType.PHONE)
        assert dev.name == "My Phone"
        assert dev.device_type == DeviceType.PHONE
        assert len(dev.id) == 12
        assert dev.online is False
        assert dev.platform == ""
        assert dev.last_seen is None

    def test_create_full(self) -> None:
        dev = Device(
            name="MacBook Pro",
            device_type=DeviceType.DESKTOP,
            platform="macos",
            model="MacBook Pro 16",
            ip_address="192.168.1.100",
            online=True,
            metadata={"os_version": "14.0"},
        )
        assert dev.platform == "macos"
        assert dev.model == "MacBook Pro 16"
        assert dev.ip_address == "192.168.1.100"
        assert dev.online is True
        assert dev.metadata == {"os_version": "14.0"}

    def test_unique_ids(self) -> None:
        d1 = Device(name="A", device_type=DeviceType.IOT)
        d2 = Device(name="B", device_type=DeviceType.IOT)
        assert d1.id != d2.id

    def test_frozen(self) -> None:
        dev = Device(name="X", device_type=DeviceType.CAMERA)
        with pytest.raises(Exception):  # noqa: B017
            dev.name = "Y"  # type: ignore[misc]


# ── 4. DeviceRegistry ───────────────────────────────────────────


class TestDeviceRegistryRegister:
    def test_register_basic(self) -> None:
        reg = DeviceRegistry()
        device, token = reg.register(name="Phone", device_type=DeviceType.PHONE)
        assert device.name == "Phone"
        assert device.device_type == DeviceType.PHONE
        assert token.device_id == device.id
        assert token.capabilities == frozenset()

    def test_register_with_capabilities(self) -> None:
        reg = DeviceRegistry()
        caps = frozenset({"camera.snapshot", "notify"})
        device, token = reg.register(
            name="Camera 1",
            device_type=DeviceType.CAMERA,
            platform="hikvision",
            capabilities=caps,
        )
        assert device.platform == "hikvision"
        assert token.capabilities == caps

    def test_register_multiple(self) -> None:
        reg = DeviceRegistry()
        d1, _ = reg.register(name="A", device_type=DeviceType.PHONE)
        d2, _ = reg.register(name="B", device_type=DeviceType.DESKTOP)
        assert d1.id != d2.id
        assert reg.stats["total_devices"] == 2


class TestDeviceRegistryGet:
    def test_get_existing(self) -> None:
        reg = DeviceRegistry()
        device, _ = reg.register(name="Phone", device_type=DeviceType.PHONE)
        found = reg.get(device.id)
        assert found is not None
        assert found.name == "Phone"

    def test_get_missing(self) -> None:
        reg = DeviceRegistry()
        assert reg.get("nonexistent") is None


class TestDeviceRegistryList:
    def test_list_all(self) -> None:
        reg = DeviceRegistry()
        reg.register(name="A", device_type=DeviceType.PHONE)
        reg.register(name="B", device_type=DeviceType.DESKTOP)
        reg.register(name="C", device_type=DeviceType.CAMERA)
        assert len(reg.list_devices()) == 3

    def test_list_by_type(self) -> None:
        reg = DeviceRegistry()
        reg.register(name="P1", device_type=DeviceType.PHONE)
        reg.register(name="P2", device_type=DeviceType.PHONE)
        reg.register(name="D1", device_type=DeviceType.DESKTOP)
        phones = reg.list_devices(device_type=DeviceType.PHONE)
        assert len(phones) == 2
        assert all(d.device_type == DeviceType.PHONE for d in phones)

    def test_list_empty(self) -> None:
        reg = DeviceRegistry()
        assert reg.list_devices() == []

    def test_list_type_no_match(self) -> None:
        reg = DeviceRegistry()
        reg.register(name="P1", device_type=DeviceType.PHONE)
        assert reg.list_devices(device_type=DeviceType.IOT) == []


class TestDeviceRegistryUpdateStatus:
    def test_update_online(self) -> None:
        reg = DeviceRegistry()
        device, _ = reg.register(name="Phone", device_type=DeviceType.PHONE)
        assert not device.online
        updated = reg.update_status(device.id, online=True)
        assert updated is not None
        assert updated.online is True
        assert updated.last_seen is not None

    def test_update_offline(self) -> None:
        reg = DeviceRegistry()
        device, _ = reg.register(name="Phone", device_type=DeviceType.PHONE)
        reg.update_status(device.id, online=True)
        updated = reg.update_status(device.id, online=False)
        assert updated is not None
        assert updated.online is False

    def test_update_preserves_fields(self) -> None:
        reg = DeviceRegistry()
        device, _ = reg.register(name="Camera", device_type=DeviceType.CAMERA, platform="hikvision")
        updated = reg.update_status(device.id, online=True)
        assert updated is not None
        assert updated.name == "Camera"
        assert updated.platform == "hikvision"
        assert updated.device_type == DeviceType.CAMERA

    def test_update_missing(self) -> None:
        reg = DeviceRegistry()
        assert reg.update_status("nonexistent", online=True) is None


class TestDeviceRegistryToken:
    def test_validate_token_valid(self) -> None:
        reg = DeviceRegistry()
        caps = frozenset({"camera.snapshot", "notify"})
        _, token = reg.register(name="Cam", device_type=DeviceType.CAMERA, capabilities=caps)
        assert reg.validate_token(token.token, "camera.snapshot")
        assert reg.validate_token(token.token, "notify")

    def test_validate_token_no_capability(self) -> None:
        reg = DeviceRegistry()
        _, token = reg.register(
            name="Cam",
            device_type=DeviceType.CAMERA,
            capabilities=frozenset({"camera.snapshot"}),
        )
        assert not reg.validate_token(token.token, "admin")

    def test_validate_token_missing(self) -> None:
        reg = DeviceRegistry()
        assert not reg.validate_token("nonexistent-token", "anything")

    def test_revoke_token(self) -> None:
        reg = DeviceRegistry()
        _, token = reg.register(
            name="Cam",
            device_type=DeviceType.CAMERA,
            capabilities=frozenset({"camera.snapshot"}),
        )
        assert reg.validate_token(token.token, "camera.snapshot")
        assert reg.revoke_token(token.token)
        assert not reg.validate_token(token.token, "camera.snapshot")

    def test_revoke_missing(self) -> None:
        reg = DeviceRegistry()
        assert not reg.revoke_token("nonexistent")


class TestDeviceRegistryStats:
    def test_empty_stats(self) -> None:
        reg = DeviceRegistry()
        stats = reg.stats
        assert stats["total_devices"] == 0
        assert stats["online_devices"] == 0
        assert stats["active_tokens"] == 0

    def test_full_stats(self) -> None:
        reg = DeviceRegistry()
        d1, _ = reg.register(name="P1", device_type=DeviceType.PHONE)
        reg.register(name="P2", device_type=DeviceType.PHONE)
        reg.register(name="D1", device_type=DeviceType.DESKTOP)
        reg.register(name="C1", device_type=DeviceType.CAMERA)
        reg.update_status(d1.id, online=True)

        stats = reg.stats
        assert stats["total_devices"] == 4
        assert stats["online_devices"] == 1
        assert stats["phones"] == 2
        assert stats["desktops"] == 1
        assert stats["cameras"] == 1
        assert stats["active_tokens"] == 4

    def test_revoked_token_stats(self) -> None:
        reg = DeviceRegistry()
        _, token = reg.register(name="X", device_type=DeviceType.IOT)
        assert reg.stats["active_tokens"] == 1
        reg.revoke_token(token.token)
        assert reg.stats["active_tokens"] == 0


# ── 5. CameraSnapshot ───────────────────────────────────────────


class TestCameraSnapshot:
    def test_create_empty(self) -> None:
        snap = CameraSnapshot(camera_id="cam1")
        assert snap.camera_id == "cam1"
        assert snap.image_b64 == ""
        assert not snap.has_image
        assert snap.image_bytes == b""
        assert snap.size_kb == 0.0
        assert snap.error is None

    def test_create_with_image(self) -> None:
        img_data = base64.b64encode(b"fake-jpeg-data").decode()
        snap = CameraSnapshot(
            camera_id="cam2",
            image_b64=img_data,
            width=640,
            height=480,
            format="jpeg",
            source="rtsp://192.168.1.10",
        )
        assert snap.has_image
        assert snap.image_bytes == b"fake-jpeg-data"
        assert snap.width == 640
        assert snap.height == 480
        assert snap.size_kb > 0

    def test_error_snapshot(self) -> None:
        snap = CameraSnapshot(
            camera_id="cam3",
            error="Connection refused",
        )
        assert not snap.has_image
        assert snap.error == "Connection refused"

    def test_error_with_image_not_valid(self) -> None:
        """Agar error bor bo'lsa, image bo'lsa ham has_image = False."""
        snap = CameraSnapshot(
            camera_id="cam4",
            image_b64=base64.b64encode(b"data").decode(),
            error="Partial frame",
        )
        assert not snap.has_image

    def test_frozen(self) -> None:
        snap = CameraSnapshot(camera_id="cam5")
        with pytest.raises(Exception):  # noqa: B017
            snap.camera_id = "other"  # type: ignore[misc]

    def test_format_default(self) -> None:
        snap = CameraSnapshot(camera_id="cam6")
        assert snap.format == "jpeg"


# ── 6. StubCamera ───────────────────────────────────────────────


class TestStubCamera:
    async def test_snapshot(self) -> None:
        camera = StubCamera()
        snap = await camera.snapshot("cam1")
        assert snap.has_image
        assert snap.camera_id == "cam1"
        assert snap.source == "stub"
        assert snap.width == 1
        assert snap.height == 1
        assert snap.error is None

    async def test_snapshot_count(self) -> None:
        camera = StubCamera()
        await camera.snapshot("a")
        await camera.snapshot("b")
        assert camera.snapshot_count == 2

    async def test_available(self) -> None:
        camera = StubCamera()
        result = await camera.is_available("cam1")
        assert result is True

    async def test_unavailable(self) -> None:
        camera = StubCamera(available=False)
        result = await camera.is_available("cam1")
        assert result is False

    async def test_unavailable_snapshot(self) -> None:
        camera = StubCamera(available=False)
        snap = await camera.snapshot("cam1")
        assert not snap.has_image
        assert snap.error is not None
        assert "mavjud emas" in snap.error

    async def test_info(self) -> None:
        camera = StubCamera()
        info = await camera.info("cam1")
        assert "name" in info
        assert "model" in info
        assert info["source"] == "stub"
        assert info["status"] == "available"

    async def test_info_unavailable(self) -> None:
        camera = StubCamera(available=False)
        info = await camera.info("cam1")
        assert info["status"] == "unavailable"

    async def test_snapshot_image_decodable(self) -> None:
        """Stub rasm haqiqiy base64 decode qila oladimi."""
        camera = StubCamera()
        snap = await camera.snapshot("cam1")
        raw = snap.image_bytes
        assert len(raw) > 0
        # JPEG magic bytes
        assert raw[:2] == b"\xff\xd8"


# ── 7. CameraProvider ABC ───────────────────────────────────────


class TestCameraProviderABC:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            CameraProvider()  # type: ignore[abstract]

    def test_stub_is_provider(self) -> None:
        camera = StubCamera()
        assert isinstance(camera, CameraProvider)


# ── 8. Vision Agent ─────────────────────────────────────────────


class TestVisionAgent:
    def test_fields(self) -> None:
        spec = VISION_AGENT_SPEC
        assert spec.name == "vision"
        assert spec.division == "devices"
        assert spec.role == "analyst"
        assert spec.model_policy == ModelTier.T2_CHEAP
        assert spec.permission_level == PermissionLevel.READ
        assert spec.trust_level == TrustLevel.SYSTEM

    def test_tools_minimal(self) -> None:
        """Vision agent faqat time.now ishlatadi (kamera alohida provider)."""
        spec = VISION_AGENT_SPEC
        assert "time.now" in spec.tool_allowlist
        assert len(spec.tool_allowlist) == 1

    def test_brakes(self) -> None:
        spec = VISION_AGENT_SPEC
        assert 1 <= spec.max_steps <= 50
        assert 1 <= spec.max_tool_calls <= 100
        assert 10 <= spec.timeout_s <= 600

    def test_prompt_untrusted_warning(self) -> None:
        """Prompt UNTRUSTED haqida ogohlantirishni o'z ichiga oladi."""
        spec = VISION_AGENT_SPEC
        prompt = spec.system_prompt.lower()
        assert "untrusted" in prompt

    def test_prompt_injection_warning(self) -> None:
        """Prompt injection haqida ogohlantirishni o'z ichiga oladi."""
        spec = VISION_AGENT_SPEC
        prompt = spec.system_prompt.lower()
        assert "injection" in prompt

    def test_prompt_has_rules(self) -> None:
        spec = VISION_AGENT_SPEC
        assert "QOIDALAR" in spec.system_prompt

    def test_prompt_camera_tasks(self) -> None:
        """Prompt kamera vazifalari haqida yozilgan."""
        spec = VISION_AGENT_SPEC
        assert "snapshot" in spec.system_prompt.lower()
        assert "ocr" in spec.system_prompt.lower()

    def test_eval(self) -> None:
        runner = EvalRunner()
        result = runner.run_eval(VISION_AGENT_SPEC)
        assert result.success, f"Eval o'tmadi: {[c for c in result.cases if not c.passed]}"

    def test_frozen(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            VISION_AGENT_SPEC.name = "other"  # type: ignore[misc]

    def test_export_matches_direct(self) -> None:
        assert VISION_AGENT_SPEC is DIRECT_VISION_SPEC

    def test_t2_model(self) -> None:
        """Vision kerak — T2 minimum (Gemini/Haiku)."""
        spec = VISION_AGENT_SPEC
        assert spec.model_policy.rank >= ModelTier.T2_CHEAP.rank


# ── 9. Devices __init__ exports ──────────────────────────────────


class TestDevicesInit:
    def test_all_exports(self) -> None:
        from zet.devices import __all__

        expected = {
            "CameraProvider",
            "CameraSnapshot",
            "CapabilityToken",
            "Device",
            "DeviceRegistry",
            "DeviceType",
            "StubCamera",
        }
        assert set(__all__) == expected


# ── 10. Builtin agents — 9 specs ────────────────────────────────


class TestBuiltinExports:
    def test_twelve_specs_exported(self) -> None:
        from zet.agents.builtin import __all__

        assert len(__all__) == 12

    def test_vision_in_exports(self) -> None:
        from zet.agents.builtin import __all__

        assert "VISION_AGENT_SPEC" in __all__

    def test_all_importable(self) -> None:
        """Barcha eksportlar import qilinishi mumkin."""
        specs = [
            CEO_AGENT_SPEC,
            DEVELOPER_AGENT_SPEC,
            FINANCE_AGENT_SPEC,
            OPERATIONS_AGENT_SPEC,
            RESEARCH_AGENT_SPEC,
            SALES_AGENT_SPEC,
            SMM_AGENT_SPEC,
            SUPPORT_AGENT_SPEC,
            VISION_AGENT_SPEC,
        ]
        names = {s.name for s in specs}
        assert len(names) == 9


# ── 11. Xavfsizlik invariantlari ────────────────────────────────


class TestSecurityInvariants:
    ALL_SPECS: list = [  # noqa: RUF012
        CEO_AGENT_SPEC,
        DEVELOPER_AGENT_SPEC,
        FINANCE_AGENT_SPEC,
        OPERATIONS_AGENT_SPEC,
        RESEARCH_AGENT_SPEC,
        SALES_AGENT_SPEC,
        SMM_AGENT_SPEC,
        SUPPORT_AGENT_SPEC,
        VISION_AGENT_SPEC,
    ]

    def test_all_system_trust(self) -> None:
        """Barcha agentlar SYSTEM trust level."""
        for spec in self.ALL_SPECS:
            assert spec.trust_level == TrustLevel.SYSTEM, f"{spec.name} SYSTEM emas"

    def test_no_execute_or_admin(self) -> None:
        """Hech bir agent EXECUTE yoki ADMIN permission olmasin."""
        for spec in self.ALL_SPECS:
            assert spec.permission_level not in {
                PermissionLevel.EXECUTE,
                PermissionLevel.ADMIN,
            }, f"{spec.name} xavfli permission: {spec.permission_level}"

    def test_brakes_within_limits(self) -> None:
        """Barcha agentlar A-07 tormoz chegarasida."""
        for spec in self.ALL_SPECS:
            assert 1 <= spec.max_steps <= 50, f"{spec.name} max_steps={spec.max_steps}"
            assert 1 <= spec.max_tool_calls <= 100, (
                f"{spec.name} max_tool_calls={spec.max_tool_calls}"
            )
            assert 10 <= spec.timeout_s <= 600, f"{spec.name} timeout_s={spec.timeout_s}"

    def test_unique_names(self) -> None:
        names = [s.name for s in self.ALL_SPECS]
        assert len(names) == len(set(names))

    def test_prompts_have_qoidalar(self) -> None:
        """Barcha agentlar promptida QOIDALAR bo'limi bor."""
        for spec in self.ALL_SPECS:
            assert "QOIDALAR" in spec.system_prompt, f"{spec.name} promptida QOIDALAR yo'q"

    def test_vision_read_only(self) -> None:
        """Vision agent READ-only (kamera tokeni alohida)."""
        assert VISION_AGENT_SPEC.permission_level == PermissionLevel.READ

    def test_vision_t2_minimum(self) -> None:
        """Vision agent T2 yoki yuqori (vision model kerak)."""
        assert VISION_AGENT_SPEC.model_policy.rank >= ModelTier.T2_CHEAP.rank

    def test_capability_token_expiry_blocks(self) -> None:
        """Expired token hech qanday capability bermaydi."""
        past = datetime.now(UTC) - timedelta(seconds=1)
        token = CapabilityToken(
            device_id="test",
            capabilities=frozenset({"camera.snapshot", "admin", "notify"}),
            expires_at=past,
        )
        assert not token.has_capability("camera.snapshot")
        assert not token.has_capability("admin")
        assert not token.has_capability("notify")
