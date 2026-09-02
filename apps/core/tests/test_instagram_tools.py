"""Instagram Graph API tool testlari (respx bilan real HTTP mock).

Naqsh: telegram_tools/youtube_tool bilan bir xil — stub/real/xato/integratsiya.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.builtin.instagram import (
    InstagramAccountStatsTool,
    InstagramPublishPhotoTool,
    InstagramRecentMediaTool,
)

_TOKEN = "EAABtest_fake_long_lived_token"
_IG_ID = "17841400000000000"
_BASE = "https://graph.facebook.com/v21.0"


# ── Account stats ──────────────────────────────────────────────────


class TestInstagramAccountStatsTool:
    async def test_stub_when_no_token(self) -> None:
        tool = InstagramAccountStatsTool()
        assert tool.is_real is False

        result = await tool.execute({})
        assert result.success is True
        assert result.output["followers_count"] == 0
        assert "stub" in result.output["source"]

    async def test_stub_when_token_but_no_id(self) -> None:
        """Token bor lekin business_account_id yo'q → stub."""
        tool = InstagramAccountStatsTool(access_token=_TOKEN)
        assert tool.is_real is False
        result = await tool.execute({})
        assert "stub" in result.output["source"]

    def test_is_real_with_both(self) -> None:
        tool = InstagramAccountStatsTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        assert tool.is_real is True

    def test_permission_and_trust(self) -> None:
        tool = InstagramAccountStatsTool()
        assert tool.permission_level == PermissionLevel.READ
        assert tool.output_trust_level == TrustLevel.UNTRUSTED

    @respx.mock
    async def test_real_account_stats(self) -> None:
        respx.get(f"{_BASE}/{_IG_ID}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": _IG_ID,
                    "username": "zet_official",
                    "name": "ZET AI",
                    "biography": "Shaxsiy AI operatsion tizim",
                    "media_count": 42,
                    "followers_count": 1234,
                    "follows_count": 100,
                },
            )
        )
        tool = InstagramAccountStatsTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({})

        assert result.success is True
        out = result.output
        assert out["user_id"] == _IG_ID
        assert out["username"] == "zet_official"
        assert out["followers_count"] == 1234
        assert out["media_count"] == 42

    @respx.mock
    async def test_invalid_token_returns_error(self) -> None:
        respx.get(f"{_BASE}/{_IG_ID}").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Invalid OAuth access token",
                        "type": "OAuthException",
                        "code": 190,
                    }
                },
            )
        )
        tool = InstagramAccountStatsTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({})
        assert result.success is False
        assert "oauth" in (result.error or "").lower() or "190" in (result.error or "")

    @respx.mock
    async def test_timeout(self) -> None:
        respx.get(f"{_BASE}/{_IG_ID}").mock(side_effect=httpx.TimeoutException("t"))
        tool = InstagramAccountStatsTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({})
        assert result.success is False
        assert "timeout" in (result.error or "").lower()

    @respx.mock
    async def test_override_user_id_in_params(self) -> None:
        other_id = "17841499999999999"
        respx.get(f"{_BASE}/{other_id}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": other_id,
                    "username": "boshqa",
                    "media_count": 5,
                    "followers_count": 10,
                    "follows_count": 3,
                },
            )
        )
        tool = InstagramAccountStatsTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({"user_id": other_id})
        assert result.output["user_id"] == other_id
        assert result.output["username"] == "boshqa"


# ── Recent media ───────────────────────────────────────────────────


class TestInstagramRecentMediaTool:
    async def test_stub_when_no_config(self) -> None:
        tool = InstagramRecentMediaTool()
        result = await tool.execute({"limit": 5})
        assert result.success is True
        assert result.output["media"] == []
        assert "stub" in result.output["source"]

    @respx.mock
    async def test_real_recent_media(self) -> None:
        respx.get(f"{_BASE}/{_IG_ID}/media").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1780000001",
                            "caption": "Salom Instagram!",
                            "media_type": "IMAGE",
                            "permalink": "https://instagram.com/p/abc",
                            "timestamp": "2026-01-15T10:00:00+0000",
                            "like_count": 42,
                            "comments_count": 5,
                            "media_url": "https://cdn.instagram.com/1.jpg",
                        },
                        {
                            "id": "1780000002",
                            "caption": "Video post",
                            "media_type": "VIDEO",
                            "permalink": "https://instagram.com/p/xyz",
                            "timestamp": "2026-01-16T11:00:00+0000",
                            "like_count": 100,
                            "comments_count": 10,
                            "media_url": "https://cdn.instagram.com/2.mp4",
                            "thumbnail_url": "https://cdn.instagram.com/2.jpg",
                        },
                    ]
                },
            )
        )
        tool = InstagramRecentMediaTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({"limit": 10})

        assert result.success is True
        assert result.output["count"] == 2
        media = result.output["media"]
        assert media[0]["id"] == "1780000001"
        assert media[0]["media_type"] == "IMAGE"
        assert media[0]["likes"] == 42
        assert media[1]["media_type"] == "VIDEO"
        assert media[1]["comments"] == 10

    @respx.mock
    async def test_limit_clamped(self) -> None:
        route = respx.get(f"{_BASE}/{_IG_ID}/media").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        tool = InstagramRecentMediaTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        await tool.execute({"limit": 25})

        url = str(route.calls[0].request.url)
        assert "limit=25" in url


# ── Publish photo (WRITE) ──────────────────────────────────────────


class TestInstagramPublishPhotoTool:
    async def test_stub_when_no_config(self) -> None:
        tool = InstagramPublishPhotoTool()
        result = await tool.execute(
            {"image_url": "https://example.com/photo.jpg", "caption": "Salom"}
        )
        assert result.success is True
        assert result.output["posted"] is False
        assert "stub" in result.output["source"]

    def test_permission_write(self) -> None:
        assert InstagramPublishPhotoTool().permission_level == PermissionLevel.WRITE

    def test_not_idempotent(self) -> None:
        assert InstagramPublishPhotoTool().idempotent is False

    @respx.mock
    async def test_real_publish_success(self) -> None:
        # 1-qadam: container yaratish
        respx.post(f"{_BASE}/{_IG_ID}/media").mock(
            return_value=httpx.Response(200, json={"id": "creation_123"})
        )
        # 2-qadam: nashr qilish
        respx.post(f"{_BASE}/{_IG_ID}/media_publish").mock(
            return_value=httpx.Response(200, json={"id": "media_999"})
        )

        tool = InstagramPublishPhotoTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute(
            {
                "image_url": "https://cdn.example.com/photo.jpg",
                "caption": "Test post #zet",
            }
        )

        assert result.success is True
        assert result.output["media_id"] == "media_999"
        assert result.output["creation_id"] == "creation_123"
        assert result.output["posted"] is True

    @respx.mock
    async def test_container_creation_fails(self) -> None:
        """Container yaratishda xato → ToolError."""
        respx.post(f"{_BASE}/{_IG_ID}/media").mock(
            return_value=httpx.Response(
                400,
                json={
                    "error": {
                        "message": "The image url is malformed",
                        "type": "OAuthException",
                        "code": 100,
                    }
                },
            )
        )
        tool = InstagramPublishPhotoTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({"image_url": "https://bad/photo.jpg"})
        assert result.success is False
        assert "malformed" in (result.error or "").lower() or "100" in (result.error or "")

    @respx.mock
    async def test_publish_step_fails(self) -> None:
        """1-qadam OK, 2-qadam xato."""
        respx.post(f"{_BASE}/{_IG_ID}/media").mock(
            return_value=httpx.Response(200, json={"id": "creation_456"})
        )
        respx.post(f"{_BASE}/{_IG_ID}/media_publish").mock(
            return_value=httpx.Response(
                500,
                json={"error": {"message": "Media not ready", "code": 9004}},
            )
        )
        tool = InstagramPublishPhotoTool(access_token=_TOKEN, ig_user_id=_IG_ID)
        result = await tool.execute({"image_url": "https://example.com/photo.jpg", "caption": "s"})
        assert result.success is False


# ── build_default_registry integratsiyasi ──────────────────────────


class TestDefaultRegistryWiring:
    def test_instagram_tools_registered(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        names = set(registry.tool_names())
        assert "instagram.account_stats" in names
        assert "instagram.recent_media" in names
        assert "instagram.publish_photo" in names

    def test_stub_without_config(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        assert registry.get("instagram.account_stats").is_real is False  # type: ignore[attr-defined]

    def test_real_with_both(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(
            notes_dir=tmp_path,  # type: ignore[arg-type]
            instagram_access_token=_TOKEN,
            instagram_business_account_id=_IG_ID,
        )
        assert registry.get("instagram.account_stats").is_real is True  # type: ignore[attr-defined]
        assert registry.get("instagram.recent_media").is_real is True  # type: ignore[attr-defined]
        assert registry.get("instagram.publish_photo").is_real is True  # type: ignore[attr-defined]


# ── SMM agent allowlist va eval permissions ────────────────────────


class TestSmmAndEvalWiring:
    def test_smm_agent_has_instagram_tools(self) -> None:
        from zet.agents.builtin.smm import SMM_AGENT_SPEC

        assert "instagram.account_stats" in SMM_AGENT_SPEC.tool_allowlist
        assert "instagram.recent_media" in SMM_AGENT_SPEC.tool_allowlist
        assert "instagram.publish_photo" in SMM_AGENT_SPEC.tool_allowlist

    def test_eval_permissions_registered(self) -> None:
        from zet.agents.eval import TOOL_PERMISSIONS

        assert TOOL_PERMISSIONS["instagram.account_stats"] == PermissionLevel.READ
        assert TOOL_PERMISSIONS["instagram.recent_media"] == PermissionLevel.READ
        assert TOOL_PERMISSIONS["instagram.publish_photo"] == PermissionLevel.WRITE
