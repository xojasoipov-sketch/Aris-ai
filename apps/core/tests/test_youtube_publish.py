"""YouTube Publish tool testlari (OAuth 2.0 refresh flow + multipart upload)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.builtin.youtube_publish import YouTubePublishTool

_CLIENT_ID = "fake-client-id.apps.googleusercontent.com"
_CLIENT_SECRET = "GOCSPX-fake-secret"
_REFRESH_TOKEN = "1//0fake_refresh_token"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    video = tmp_path / "sample.mp4"
    # Kichik "video" — real fayl emas, faqat baytlar
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
    return video


# ── Basic ──────────────────────────────────────────────────────────


class TestYouTubePublishBasic:
    async def test_stub_when_no_credentials(self, sample_video: Path) -> None:
        tool = YouTubePublishTool()
        assert tool.is_real is False

        result = await tool.execute({"file_path": str(sample_video), "title": "Test"})
        assert result.success is True
        assert result.output["uploaded"] is False
        assert "stub" in result.output["source"]

    async def test_stub_missing_one_of_three(self, sample_video: Path) -> None:
        """Uchtasidan bittasi yo'q → stub."""
        tool = YouTubePublishTool(client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET)
        assert tool.is_real is False

    def test_is_real_all_three(self) -> None:
        tool = YouTubePublishTool(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token=_REFRESH_TOKEN,
        )
        assert tool.is_real is True

    def test_permission_write(self) -> None:
        assert YouTubePublishTool().permission_level == PermissionLevel.WRITE

    def test_not_idempotent(self) -> None:
        assert YouTubePublishTool().idempotent is False

    def test_trust_system(self) -> None:
        assert YouTubePublishTool().output_trust_level == TrustLevel.SYSTEM


# ── Real upload flow ───────────────────────────────────────────────


class TestYouTubePublishReal:
    @respx.mock
    async def test_full_upload_success(self, sample_video: Path) -> None:
        # 1-qadam: refresh_token → access_token
        respx.post(_TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "ya29.fake_access_token",
                    "expires_in": 3599,
                    "token_type": "Bearer",
                    "scope": "https://www.googleapis.com/auth/youtube.upload",
                },
            )
        )
        # 2-qadam: multipart upload → video ID
        respx.post(_UPLOAD_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "abcXYZ12345",
                    "snippet": {"title": "Sinov video"},
                    "status": {"privacyStatus": "private"},
                },
            )
        )

        tool = YouTubePublishTool(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token=_REFRESH_TOKEN,
        )
        result = await tool.execute(
            {
                "file_path": str(sample_video),
                "title": "Sinov video",
                "description": "ZET testi",
                "tags": ["zet", "test"],
                "privacy": "unlisted",
            }
        )

        assert result.success is True
        assert result.output["video_id"] == "abcXYZ12345"
        assert result.output["url"] == "https://www.youtube.com/watch?v=abcXYZ12345"
        assert result.output["uploaded"] is True
        assert result.output["privacy"] == "unlisted"

    @respx.mock
    async def test_refresh_token_expired(self, sample_video: Path) -> None:
        respx.post(_TOKEN_URL).mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "Token has been expired or revoked.",
                },
            )
        )
        tool = YouTubePublishTool(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token=_REFRESH_TOKEN,
        )
        result = await tool.execute({"file_path": str(sample_video), "title": "x"})
        assert result.success is False
        assert "expired" in (result.error or "").lower() or "invalid_grant" in (result.error or "")

    @respx.mock
    async def test_upload_quota_exceeded(self, sample_video: Path) -> None:
        respx.post(_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "ya29.x"})
        )
        respx.post(_UPLOAD_URL).mock(
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "message": "The request cannot be completed because you have exceeded your quota.",
                        "errors": [{"reason": "quotaExceeded"}],
                    }
                },
            )
        )
        tool = YouTubePublishTool(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token=_REFRESH_TOKEN,
        )
        result = await tool.execute({"file_path": str(sample_video), "title": "x"})
        assert result.success is False
        assert "quota" in (result.error or "").lower()

    @respx.mock
    async def test_file_not_found(self) -> None:
        respx.post(_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "ya29.x"})
        )
        tool = YouTubePublishTool(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token=_REFRESH_TOKEN,
        )
        result = await tool.execute({"file_path": "/nonexistent/nowhere.mp4", "title": "x"})
        assert result.success is False
        assert "topilmadi" in (result.error or "").lower()

    @respx.mock
    async def test_upload_body_contains_metadata(self, sample_video: Path) -> None:
        """Multipart body — metadata JSON + fayl baytlari."""
        respx.post(_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "ya29.x"})
        )
        route = respx.post(_UPLOAD_URL).mock(
            return_value=httpx.Response(200, json={"id": "vid_777"})
        )
        tool = YouTubePublishTool(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            refresh_token=_REFRESH_TOKEN,
        )
        await tool.execute(
            {
                "file_path": str(sample_video),
                "title": "Meta test",
                "description": "Xushnud",
                "tags": ["zzz"],
                "privacy": "public",
            }
        )

        request = route.calls[0].request
        body = request.content
        # Metadata JSON body ichida
        assert b'"title": "Meta test"' in body
        assert b'"privacyStatus": "public"' in body
        assert b'"tags": ["zzz"]' in body
        # Bearer token
        assert request.headers["authorization"].startswith("Bearer ya29.")
        # Multipart content-type
        assert "multipart/related" in request.headers["content-type"]


# ── Registry & agent wiring ────────────────────────────────────────


class TestRegistryWiring:
    def test_youtube_publish_registered(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        assert "youtube.publish" in set(registry.tool_names())

    def test_stub_without_oauth(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        assert registry.get("youtube.publish").is_real is False  # type: ignore[attr-defined]

    def test_real_with_all_three(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(
            notes_dir=tmp_path,  # type: ignore[arg-type]
            youtube_oauth_client_id=_CLIENT_ID,
            youtube_oauth_client_secret=_CLIENT_SECRET,
            youtube_oauth_refresh_token=_REFRESH_TOKEN,
        )
        assert registry.get("youtube.publish").is_real is True  # type: ignore[attr-defined]

    def test_smm_agent_has_publish(self) -> None:
        from zet.agents.builtin.smm import SMM_AGENT_SPEC

        assert "youtube.publish" in SMM_AGENT_SPEC.tool_allowlist

    def test_eval_permissions(self) -> None:
        from zet.agents.eval import TOOL_PERMISSIONS

        assert TOOL_PERMISSIONS["youtube.publish"] == PermissionLevel.WRITE
