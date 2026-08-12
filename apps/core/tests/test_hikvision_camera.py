"""HikvisionCamera testlari — respx bilan, haqiqiy kameraga ulanmasdan.

gap-analysis #8: foydalanuvchining aniq talabi (Hikvision kameralar).
HTTP Digest Auth ikki bosqichli oqim: 1) 401 + WWW-Authenticate,
2) to'g'ri Authorization header bilan qayta so'rov → 200 + JPEG baytlar.
"""

from __future__ import annotations

import base64

import httpx
import respx

from zet.devices.hikvision import HikvisionCamera

_HOST = "192.168.1.64"
_PATH = "/ISAPI/Streaming/channels/1/picture"
_URL = f"http://{_HOST}{_PATH}"
_DIGEST_CHALLENGE = 'Digest realm="Hikvision", nonce="abc123nonce", qop="auth"'
_FAKE_JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"


def _camera(**kwargs: object) -> HikvisionCamera:
    return HikvisionCamera(host=_HOST, username="admin", password="pass123", **kwargs)  # type: ignore[arg-type]


class TestSnapshot:
    @respx.mock
    async def test_successful_snapshot(self) -> None:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
                httpx.Response(200, content=_FAKE_JPEG, headers={"content-type": "image/jpeg"}),
            ]
        )
        camera = _camera()
        snapshot = await camera.snapshot("front-door")

        assert snapshot.has_image
        assert snapshot.error is None
        assert snapshot.format == "jpeg"
        assert snapshot.source == f"hikvision:{_HOST}"
        assert base64.b64decode(snapshot.image_b64) == _FAKE_JPEG

    @respx.mock
    async def test_auth_failure_returns_error(self) -> None:
        """Noto'g'ri parol — ikkinchi urinish ham 401 qaytaradi."""
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
            ]
        )
        camera = _camera()
        snapshot = await camera.snapshot("x")

        assert not snapshot.has_image
        assert "401" in snapshot.error or "Autentifikatsiya" in snapshot.error

    @respx.mock
    async def test_404_returns_error(self) -> None:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
                httpx.Response(404),
            ]
        )
        camera = _camera()
        snapshot = await camera.snapshot("x")

        assert not snapshot.has_image
        assert "404" in snapshot.error

    @respx.mock
    async def test_timeout_returns_error(self) -> None:
        respx.get(_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))
        camera = _camera()
        snapshot = await camera.snapshot("x")

        assert not snapshot.has_image
        assert snapshot.error is not None

    @respx.mock
    async def test_network_error_returns_error(self) -> None:
        respx.get(_URL).mock(side_effect=httpx.ConnectError("no route to host"))
        camera = _camera()
        snapshot = await camera.snapshot("x")

        assert not snapshot.has_image

    @respx.mock
    async def test_empty_body_returns_error(self) -> None:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
                httpx.Response(200, content=b""),
            ]
        )
        camera = _camera()
        snapshot = await camera.snapshot("x")

        assert not snapshot.has_image
        assert "Bo'sh" in snapshot.error

    @respx.mock
    async def test_custom_channel_used_in_path(self) -> None:
        channel_url = "http://192.168.1.64/ISAPI/Streaming/channels/101/picture"
        respx.get(channel_url).mock(
            side_effect=[
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
                httpx.Response(200, content=_FAKE_JPEG),
            ]
        )
        camera = _camera(channel=101)
        snapshot = await camera.snapshot("nvr-cam-1")
        assert snapshot.has_image


class TestIsAvailable:
    @respx.mock
    async def test_available_when_snapshot_succeeds(self) -> None:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(401, headers={"WWW-Authenticate": _DIGEST_CHALLENGE}),
                httpx.Response(200, content=_FAKE_JPEG),
            ]
        )
        camera = _camera()
        assert await camera.is_available("x") is True

    @respx.mock
    async def test_unavailable_when_snapshot_fails(self) -> None:
        respx.get(_URL).mock(side_effect=httpx.ConnectError("down"))
        camera = _camera()
        assert await camera.is_available("x") is False


class TestInfo:
    async def test_info_includes_host(self) -> None:
        camera = _camera()
        info = await camera.info("front-door")
        assert _HOST in info["name"]
        assert info["source"] == "hikvision"


class TestAclose:
    async def test_aclose_own_client(self) -> None:
        camera = _camera()
        camera._get_client()
        await camera.aclose()

    async def test_aclose_external_client_not_closed(self) -> None:
        client = httpx.AsyncClient()
        camera = _camera(client=client)
        await camera.aclose()
        assert client.is_closed is False
        await client.aclose()
