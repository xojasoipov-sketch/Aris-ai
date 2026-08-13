"""RtspCamera testlari — cv2 modulini mock qilib, haqiqiy kameraga
ulanmasdan.

NEGA. `opencv-python` — MAJBURIY bog'liqlik EMAS (test/CI muhitiga
o'rnatilmagan). Shuning uchun test ikki oyoqda turadi: (1) cv2 yo'q
bo'lgan holatda tushunarli xato, (2) cv2 mock qilinganda kutilgan
JPEG baytlar.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from zet.api import deps as api_deps
from zet.config import get_settings
from zet.devices.camera import StubCamera
from zet.devices.rtsp import RtspCamera, _redact_url

_URL = "rtsp://admin:Secret123@192.168.1.10:554/live/stream1"
_FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"


class _FakeFrame:
    """`numpy.ndarray` o'rniga oddiy `.shape` beruvchi obyekt.

    `numpy` sinov muhitiga o'rnatilmagan (opsional bog'liqlik) —
    kadr obyekti bo'lishi kifoya, cv2 mock uni o'zgartirmasdan
    imencode'ga uzatadi.
    """

    def __init__(self, height: int, width: int) -> None:
        self.shape = (height, width, 3)


class _StubCapture:
    """`cv2.VideoCapture` o'rnini bosuvchi soxta obyekt.

    Barcha xatti-harakat konstruktorga berilgan sozlamalar bilan
    boshqariladi — testlar shu orqali muvaffaqiyat, bo'sh kadr yoki
    istisno holatlarini tekshiradi.
    """

    def __init__(
        self,
        *,
        opened: bool = True,
        read_ok: bool = True,
        frame: Any = None,
        raise_on_open: Exception | None = None,
    ) -> None:
        if raise_on_open is not None:
            raise raise_on_open
        self._opened = opened
        self._read_ok = read_ok
        self._frame = frame
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 — cv2 API
        return self._opened

    def read(self) -> tuple[bool, Any]:
        return self._read_ok, self._frame

    def release(self) -> None:
        self.released = True


def _make_cv2_mock(
    *,
    capture: _StubCapture | None = None,
    imencode_ok: bool = True,
    imencode_bytes: bytes = _FAKE_JPEG,
    capture_factory: Any = None,
) -> Any:
    """Kichik `cv2` o'rnini bosuvchi modul obyekti quramiz.

    `RtspCamera` cv2'dan atigi to'rt narsani ishlatadi:
    `VideoCapture`, `CAP_FFMPEG`, `imencode`. Testda shu minimum ni
    beramiz.
    """
    captured_url: dict[str, Any] = {}

    def default_factory(url: str, backend: int) -> _StubCapture:
        captured_url["url"] = url
        captured_url["backend"] = backend
        assert capture is not None
        return capture

    factory = capture_factory or default_factory

    def imencode(_ext: str, _frame: Any) -> tuple[bool, Any]:
        buf = SimpleNamespace(tobytes=lambda: imencode_bytes)
        return imencode_ok, buf

    return SimpleNamespace(
        VideoCapture=factory,
        CAP_FFMPEG=1900,
        imencode=imencode,
        _captured=captured_url,
    )


class TestImportFallback:
    async def test_missing_cv2_returns_clear_error(self) -> None:
        """cv2 argumentiga None berilsa, snapshot tushunarli xato qaytaradi.

        Modul yuklanayotgan payt cv2 topilmasa `_cv2_default` None
        bo'ladi — shu holatni to'g'ridan-to'g'ri simulyatsiya qilamiz.
        """
        camera = RtspCamera(rtsp_url=_URL, cv2_module=None)
        # `_cv2` majburiy None bo'lishi kerak, hatto modul darajasidagi
        # `_cv2_default` boshqacha bo'lsa ham.
        camera._cv2 = None  # type: ignore[assignment]
        snapshot = await camera.snapshot("cam-1")

        assert not snapshot.has_image
        assert snapshot.error is not None
        assert "opencv-python not installed" in snapshot.error
        assert "opencv-python-headless" in snapshot.error

    async def test_is_available_backend_reflects_cv2(self) -> None:
        cv2_mock = _make_cv2_mock(capture=_StubCapture(frame=_FakeFrame(2, 3)))
        assert RtspCamera(rtsp_url=_URL, cv2_module=cv2_mock).is_available_backend is True

        # Modul darajasidagi `_cv2_default` yuklangan bo'lsa ham,
        # instansiya o'z `cv2_module`ini ustun qo'yadi.
        empty = RtspCamera(rtsp_url=_URL)
        empty._cv2 = None  # type: ignore[assignment]
        assert empty.is_available_backend is False


class TestSuccessfulSnapshot:
    async def test_snapshot_returns_jpeg_bytes(self) -> None:
        frame = _FakeFrame(240, 320)
        capture = _StubCapture(frame=frame)
        cv2_mock = _make_cv2_mock(capture=capture)

        camera = RtspCamera(rtsp_url=_URL, cv2_module=cv2_mock)
        snapshot = await camera.snapshot("front-door")

        assert snapshot.has_image
        assert snapshot.error is None
        assert snapshot.format == "jpeg"
        assert snapshot.width == 320
        assert snapshot.height == 240
        assert snapshot.image_bytes == _FAKE_JPEG
        assert base64.b64decode(snapshot.image_b64) == _FAKE_JPEG
        # URL parolini log/manba matnida ochmaymiz.
        assert "Secret123" not in snapshot.source
        assert "192.168.1.10" in snapshot.source
        # Resurs yopilgan.
        assert capture.released is True
        # cv2.CAP_FFMPEG backend ishlatilgan.
        assert cv2_mock._captured["backend"] == cv2_mock.CAP_FFMPEG
        assert cv2_mock._captured["url"] == _URL


class TestTimeout:
    async def test_timeout_raises_error(self) -> None:
        """Kadr olish uzoq davom etsa — snapshot xato bilan qaytadi."""
        import time

        def slow_capture(_url: str, _backend: int) -> _StubCapture:
            time.sleep(0.5)  # timeout=0.05 dan uzun
            return _StubCapture(frame=_FakeFrame(1, 1))

        cv2_mock = _make_cv2_mock(capture_factory=slow_capture)
        camera = RtspCamera(rtsp_url=_URL, timeout_s=1, cv2_module=cv2_mock)
        # `timeout_s` int; qisqartirish uchun `_timeout_s` ni to'g'ridan
        # to'g'ri majburiy qilamiz — 50ms bo'lsa 500ms sleep uzunroq.
        camera._timeout_s = 0.05  # type: ignore[assignment]

        snapshot = await camera.snapshot("cam-x")
        assert not snapshot.has_image
        assert snapshot.error is not None
        assert "javob bermadi" in snapshot.error or "s ichida" in snapshot.error


class TestBadUrl:
    async def test_capture_not_opened_returns_error(self) -> None:
        """URL yaroqsiz bo'lsa `isOpened() == False` — tushunarli xato."""
        capture = _StubCapture(opened=False, frame=None)
        cv2_mock = _make_cv2_mock(capture=capture)

        camera = RtspCamera(rtsp_url="rtsp://bad-host:554/nope", cv2_module=cv2_mock)
        snapshot = await camera.snapshot("cam-x")

        assert not snapshot.has_image
        assert snapshot.error is not None
        assert "ochilmadi" in snapshot.error

    async def test_read_failure_returns_error(self) -> None:
        capture = _StubCapture(read_ok=False, frame=None)
        cv2_mock = _make_cv2_mock(capture=capture)
        camera = RtspCamera(rtsp_url=_URL, cv2_module=cv2_mock)
        snapshot = await camera.snapshot("cam-x")

        assert not snapshot.has_image
        assert snapshot.error is not None
        assert "Kadr olinmadi" in snapshot.error

    async def test_exception_in_cv2_returns_error(self) -> None:
        """cv2 ichida istisno bo'lsa — jarayon yiqilmaydi."""
        cv2_mock = _make_cv2_mock(
            capture_factory=lambda *_a, **_k: _StubCapture(raise_on_open=RuntimeError("boom")),
        )
        camera = RtspCamera(rtsp_url=_URL, cv2_module=cv2_mock)
        snapshot = await camera.snapshot("cam-x")

        assert not snapshot.has_image
        assert snapshot.error is not None
        assert "boom" in snapshot.error


class TestRedactUrl:
    def test_credentials_removed(self) -> None:
        assert _redact_url(_URL) == "rtsp://192.168.1.10:554/live/stream1"

    def test_url_without_credentials(self) -> None:
        assert _redact_url("rtsp://cam.example/stream") == "rtsp://cam.example/stream"


class TestDepsRegistration:
    @pytest.fixture(autouse=True)
    def _clear_caches(self) -> Any:
        get_settings.cache_clear()
        api_deps.get_tool_registry.cache_clear()
        yield
        get_settings.cache_clear()
        api_deps.get_tool_registry.cache_clear()

    def test_rtsp_camera_selected_when_url_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_RTSP_CAMERA_URL", _URL)
        monkeypatch.delenv("ZET_HIKVISION_HOST", raising=False)
        registry = api_deps.get_tool_registry()
        tool = registry.get("camera.snapshot")
        assert isinstance(tool._provider, RtspCamera)

    def test_rtsp_takes_precedence_over_hikvision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ikkalasi ham sozlangan bo'lsa — RTSP tanlanadi (umumiy yo'l)."""
        monkeypatch.setenv("ZET_RTSP_CAMERA_URL", _URL)
        monkeypatch.setenv("ZET_HIKVISION_HOST", "192.168.1.64")
        monkeypatch.setenv("ZET_HIKVISION_USERNAME", "admin")
        monkeypatch.setenv("ZET_HIKVISION_PASSWORD", "secret")
        registry = api_deps.get_tool_registry()
        tool = registry.get("camera.snapshot")
        assert isinstance(tool._provider, RtspCamera)

    def test_stub_when_neither_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ZET_RTSP_CAMERA_URL", raising=False)
        monkeypatch.delenv("ZET_HIKVISION_HOST", raising=False)
        registry = api_deps.get_tool_registry()
        tool = registry.get("camera.snapshot")
        assert isinstance(tool._provider, StubCamera)
