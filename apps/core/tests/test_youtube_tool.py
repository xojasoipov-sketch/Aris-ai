"""YouTube Data API v3 tool testlari (respx bilan real HTTP mock).

`WebSearchTool` va `GitHubReadTool` bilan bir xil naqsh:
    1. Kalit yo'q → stub rejim (barqaror, tarmoqqa chiqmaydi)
    2. Muvaffaqiyatli javob → to'g'ri parse
    3. HTTP xatolari (403 kvota, 404 topilmadi, timeout) → ToolError
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.tools.builtin.youtube import (
    YouTubeChannelStatsTool,
    YouTubeSearchTool,
    YouTubeVideoStatsTool,
)

_API_KEY = "AIza-fake-key"
_BASE = "https://www.googleapis.com/youtube/v3"


# ── Search ─────────────────────────────────────────────────────────


class TestYouTubeSearchTool:
    async def test_stub_when_no_key(self) -> None:
        tool = YouTubeSearchTool()
        assert tool.is_real is False

        result = await tool.execute({"query": "python tutorial"})
        assert result.success is True
        assert result.output["query"] == "python tutorial"
        assert len(result.output["results"]) == 3
        assert "stub" in result.output["source"]

    def test_is_real_with_key(self) -> None:
        assert YouTubeSearchTool(api_key=_API_KEY).is_real is True

    @respx.mock
    async def test_real_search_video(self) -> None:
        respx.get(f"{_BASE}/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": {"kind": "youtube#video", "videoId": "abc123"},
                            "snippet": {
                                "title": "Python o'rganamiz",
                                "channelTitle": "Test Channel",
                                "publishedAt": "2025-01-01T00:00:00Z",
                                "description": "Python asoslari",
                            },
                        }
                    ]
                },
            )
        )
        tool = YouTubeSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "python", "kind": "video"})

        assert result.success is True
        items = result.output["results"]
        assert len(items) == 1
        assert items[0]["id"] == "abc123"
        assert items[0]["kind"] == "video"
        assert items[0]["url"] == "https://www.youtube.com/watch?v=abc123"

    @respx.mock
    async def test_sends_correct_query_params(self) -> None:
        route = respx.get(f"{_BASE}/search").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        tool = YouTubeSearchTool(api_key=_API_KEY)
        await tool.execute({"query": "test", "max_results": 10, "kind": "channel"})

        request_url = str(route.calls[0].request.url)
        assert "q=test" in request_url
        assert "type=channel" in request_url
        assert "maxResults=10" in request_url
        assert f"key={_API_KEY}" in request_url

    @respx.mock
    async def test_quota_exceeded_returns_tool_error(self) -> None:
        respx.get(f"{_BASE}/search").mock(
            return_value=httpx.Response(403, json={"error": {"message": "quotaExceeded"}})
        )
        tool = YouTubeSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "x"})
        assert result.success is False
        assert "kvota" in (result.error or "").lower() or "403" in (result.error or "")

    @respx.mock
    async def test_max_results_clamped_to_25(self) -> None:
        route = respx.get(f"{_BASE}/search").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        tool = YouTubeSearchTool(api_key=_API_KEY)
        # JSON schema max=25, ammo dry test uchun tool ichida clamp
        await tool.execute({"query": "x", "max_results": 25})
        assert "maxResults=25" in str(route.calls[0].request.url)


# ── Channel stats ──────────────────────────────────────────────────


class TestYouTubeChannelStatsTool:
    async def test_stub_when_no_key(self) -> None:
        tool = YouTubeChannelStatsTool()
        result = await tool.execute({"channel_id": "UCabc"})
        assert result.success is True
        assert result.output["subscribers"] == 0

    @respx.mock
    async def test_real_channel_by_id(self) -> None:
        respx.get(f"{_BASE}/channels").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UCabc123",
                            "snippet": {
                                "title": "Test Kanal",
                                "description": "Tavsif",
                                "publishedAt": "2020-01-01T00:00:00Z",
                            },
                            "statistics": {
                                "subscriberCount": "12345",
                                "viewCount": "6789000",
                                "videoCount": "142",
                            },
                        }
                    ]
                },
            )
        )
        tool = YouTubeChannelStatsTool(api_key=_API_KEY)
        result = await tool.execute({"channel_id": "UCabc123"})

        assert result.success is True
        assert result.output["title"] == "Test Kanal"
        assert result.output["subscribers"] == 12345
        assert result.output["views"] == 6789000
        assert result.output["videos"] == 142

    @respx.mock
    async def test_handle_starts_with_at(self) -> None:
        """@handle → forHandle parametri uzatiladi."""
        route = respx.get(f"{_BASE}/channels").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "UCxxx",
                            "snippet": {"title": "x", "description": "", "publishedAt": ""},
                            "statistics": {
                                "subscriberCount": "1",
                                "viewCount": "1",
                                "videoCount": "1",
                            },
                        }
                    ]
                },
            )
        )
        tool = YouTubeChannelStatsTool(api_key=_API_KEY)
        await tool.execute({"channel_id": "@somehandle"})

        url = str(route.calls[0].request.url)
        assert "forHandle=%40somehandle" in url or "forHandle=@somehandle" in url

    @respx.mock
    async def test_channel_not_found_returns_error(self) -> None:
        respx.get(f"{_BASE}/channels").mock(return_value=httpx.Response(200, json={"items": []}))
        tool = YouTubeChannelStatsTool(api_key=_API_KEY)
        result = await tool.execute({"channel_id": "UCzzz"})
        assert result.success is False
        assert "topilmadi" in (result.error or "").lower()


# ── Video stats ────────────────────────────────────────────────────


class TestYouTubeVideoStatsTool:
    async def test_stub_when_no_key(self) -> None:
        tool = YouTubeVideoStatsTool()
        result = await tool.execute({"video_id": "abc"})
        assert result.success is True
        assert result.output["views"] == 0

    @respx.mock
    async def test_real_video_success(self) -> None:
        respx.get(f"{_BASE}/videos").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "vidXYZ",
                            "snippet": {
                                "title": "Test video",
                                "channelTitle": "Kanal",
                                "description": "Tavsif",
                                "publishedAt": "2024-06-01T12:00:00Z",
                            },
                            "contentDetails": {"duration": "PT10M15S"},
                            "statistics": {
                                "viewCount": "1000",
                                "likeCount": "50",
                                "commentCount": "5",
                            },
                        }
                    ]
                },
            )
        )
        tool = YouTubeVideoStatsTool(api_key=_API_KEY)
        result = await tool.execute({"video_id": "vidXYZ"})

        assert result.success is True
        assert result.output["title"] == "Test video"
        assert result.output["duration"] == "PT10M15S"
        assert result.output["views"] == 1000
        assert result.output["likes"] == 50
        assert result.output["comments"] == 5

    @respx.mock
    async def test_missing_video_returns_error(self) -> None:
        respx.get(f"{_BASE}/videos").mock(return_value=httpx.Response(200, json={"items": []}))
        tool = YouTubeVideoStatsTool(api_key=_API_KEY)
        result = await tool.execute({"video_id": "yoq"})
        assert result.success is False
        assert "topilmadi" in (result.error or "").lower()

    @respx.mock
    async def test_network_timeout(self) -> None:
        respx.get(f"{_BASE}/videos").mock(side_effect=httpx.TimeoutException("timeout"))
        tool = YouTubeVideoStatsTool(api_key=_API_KEY)
        result = await tool.execute({"video_id": "abc"})
        assert result.success is False
        assert "timeout" in (result.error or "").lower()


# ── build_default_registry integratsiyasi ──────────────────────────


class TestDefaultRegistryWiring:
    """Deps → build_default_registry → YouTube tool'lar mavjud."""

    def test_youtube_tools_registered(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        names = set(registry.tool_names())
        assert "youtube.search" in names
        assert "youtube.channel_stats" in names
        assert "youtube.video_stats" in names

    def test_youtube_tools_stub_without_key(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(notes_dir=tmp_path)  # type: ignore[arg-type]
        # is_real=False bo'lishi kerak
        search_tool = registry.get("youtube.search")
        assert search_tool.is_real is False  # type: ignore[attr-defined]

    def test_youtube_tools_real_with_key(self, tmp_path: pytest.TempPathFactory) -> None:
        from zet.tools.builtin import build_default_registry

        registry = build_default_registry(
            notes_dir=tmp_path,
            youtube_api_key=_API_KEY,  # type: ignore[arg-type]
        )
        assert registry.get("youtube.search").is_real is True  # type: ignore[attr-defined]
        assert registry.get("youtube.channel_stats").is_real is True  # type: ignore[attr-defined]
        assert registry.get("youtube.video_stats").is_real is True  # type: ignore[attr-defined]
