"""Kamera endpoint'lari (Z48.3).

NEGA BU TESTLAR BOR.

`/camera` sahifasidagi hamma narsa o'ylab topilgan edi — oltita kamera
nomi, presetlar, PTZ tugmalari. Sozlamada esa bitta Hikvision kanali
bor xolos.

Eng muhim invariant shu yerda: **kamera sozlanmagan bo'lsa stub rasm
QAYTARILMAYDI**. `StubCamera` 1x1 piksel oq JPEG beradi va uni sahifaga
chiqarish "kamera ishlayapti" degan yolg'on bo'lardi — ega hovlini
kuzatyapman deb o'ylab qolardi.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_config
from zet.config import Settings


def _settings(**kwargs: object) -> Settings:
    """Hikvision kalitlari ANIQ bo'shatiladi (`.env` ta'siri yo'q)."""
    base: dict[str, object] = {
        "hikvision_host": "",
        "hikvision_username": "",
        "hikvision_password": None,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


@pytest.fixture
def unconfigured() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_config] = lambda: _settings()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def configured() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_config] = lambda: _settings(
        hikvision_host="192.168.1.64",
        hikvision_username="admin",
        hikvision_password="parol",
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestCameraInfo:
    def test_unconfigured_camera_says_so(self, unconfigured: TestClient) -> None:
        body = unconfigured.get("/api/v1/camera").json()

        assert body["configured"] is False
        assert "ulanmagan" in body["label"].lower()

    def test_detail_names_the_missing_settings(self, unconfigured: TestClient) -> None:
        """Ega NIMA qilish kerakligini ko'rsin — "xato" degan so'z yetarli emas."""
        body = unconfigured.get("/api/v1/camera").json()

        assert "ZET_HIKVISION_HOST" in body["detail"]

    def test_configured_camera_shows_host_and_channel(self, configured: TestClient) -> None:
        body = configured.get("/api/v1/camera").json()

        assert body["configured"] is True
        assert "192.168.1.64" in body["label"]


class TestSnapshot:
    def test_unconfigured_snapshot_is_503_not_a_stub_image(self, unconfigured: TestClient) -> None:
        """ENG MUHIM: stub rasm qaytarilmaydi.

        `StubCamera` 1x1 oq JPEG beradi. Uni ko'rsatish "kamera
        ishlayapti" degan yolg'on bo'lardi."""
        response = unconfigured.post("/api/v1/camera/snapshot")

        assert response.status_code == 503
        assert "image_b64" not in response.text
