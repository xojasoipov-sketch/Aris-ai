"""YouTube Data API v3 tool'lari (Bo'lim 7, C-03 #2).

Ega o'quv markazi + YouTube kanal ustuvorliklari (C-03). Bu tool'lar
YouTube Data API v3 orqali ochiq ma'lumotlarni o'qiydi — kanal statistikasi,
video ro'yxati, video tafsilotlari. **OAuth kerak emas** — faqat API kalit.

Bepul kvota: **10 000 unit/kun** (~1000 oddiy so'rov). Sarflash normasi:
    - `search` = 100 unit (qimmatroq — imkon qadar oz)
    - `videos.list`, `channels.list` = 1 unit
    - `playlistItems.list` = 1 unit

**Publish/upload YO'Q** — u OAuth 2.0 va foydalanuvchi sozlanmasi talab
qiladi (Google Cloud Console + consent screen + refresh token). Uni
alohida Bo'lim (`youtube_publish.py`) sifatida keyingi bosqichda qo'shiladi.

Fail-open: `api_key` bo'lmasa — stub rejim (barqaror soxta natijalar,
tarmoqqa chiqmaydi). `WebSearchTool`/`GitHubReadTool` bilan bir xil
"real-vs-stub" naqshi.

Xavfsizlik:
    - output trust_level = UNTRUSTED (A-05) — YouTube foydalanuvchi
      kontenti, injection'ga qarshi belgilangan
    - permission = READ
    - idempotent = True (bir xil so'rov bir xil ma'lumot qaytaradi)

Bog'liq qarorlar:
    C-03 — biznes qamrovi (YouTube kanal ikkinchi ustuvorlik)
    V-42 — UNTRUSTED belgi
"""

from __future__ import annotations

from typing import Any

import httpx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

_API_BASE = "https://www.googleapis.com/youtube/v3"


class _YouTubeHttpMixin:
    """Umumiy HTTP klient + xato ushlash — barcha YouTube tool'lari uchun."""

    _api_key: str | None
    _client: httpx.AsyncClient | None
    _owns_client: bool

    def _init_http(self, api_key: str | None, client: httpx.AsyncClient | None) -> None:
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """`GET /youtube/v3/{endpoint}` — kalit qo'shiladi, xatolar `ToolError`ga."""
        try:
            response = await self._get_client().get(
                f"{_API_BASE}/{endpoint}",
                params={**params, "key": self._api_key or ""},
                timeout=30,
            )
        except httpx.TimeoutException as exc:
            raise ToolError(f"YouTube API timeout ({endpoint})") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"YouTube API tarmoq xatosi: {exc}") from exc

        if response.status_code == 403:
            # Kvota tugagan yoki kalit noto'g'ri — ikkalasi ham 403 qaytadi
            raise ToolError(
                f"YouTube API 403 — kalit noto'g'ri yoki kunlik kvota tugagan "
                f"({response.text[:200]})"
            )
        if response.status_code == 404:
            raise ToolError("YouTube: resurs topilmadi (404)")
        if response.status_code >= 400:
            raise ToolError(f"YouTube API xato ({response.status_code}): {response.text[:200]}")

        return response.json()  # type: ignore[no-any-return]


class YouTubeSearchTool(_YouTubeHttpMixin, Tool):
    """YouTube video/kanal qidiruvi (`search.list`, 100 quota unit/so'rov).

    Qimmat so'rov — ehtiyot bo'ling. Bir kunlik 10K kvotada ~100 ta
    qidirish bajarish mumkin.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(api_key, client)

    @property
    def name(self) -> str:
        return "youtube.search"

    @property
    def description(self) -> str:
        return (
            "YouTube'dan video yoki kanal qidiradi — natijalar UNTRUSTED "
            "sifatida qaytadi (foydalanuvchi kontenti)"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Qidiruv matni", "minLength": 1},
                "max_results": {
                    "type": "integer",
                    "description": "Maksimal natijalar (default 5, max 25)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 25,
                },
                "kind": {
                    "type": "string",
                    "description": "Turi: 'video', 'channel', 'playlist'",
                    "enum": ["video", "channel", "playlist"],
                    "default": "video",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def timeout_s(self) -> int:
        return 30

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params["query"]
        max_results = min(int(params.get("max_results", 5)), 25)
        kind = params.get("kind", "video")

        if not self.is_real:
            return _stub_search(query, kind, max_results)

        data = await self._get(
            "search",
            {"part": "snippet", "q": query, "type": kind, "maxResults": max_results},
        )
        items = data.get("items") or []
        results = [_format_search_item(it) for it in items]
        return {
            "query": query,
            "kind": kind,
            "results": results,
            "total": len(results),
            "source": "youtube.search",
        }


class YouTubeChannelStatsTool(_YouTubeHttpMixin, Tool):
    """Kanal statistikasi — obunachilar, ko'rishlar, videolar soni (`channels.list`, 1 unit)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(api_key, client)

    @property
    def name(self) -> str:
        return "youtube.channel_stats"

    @property
    def description(self) -> str:
        return "YouTube kanal statistikasi (obunachilar, jami ko'rishlar, videolar soni)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "channel_id": {
                    "type": "string",
                    "description": "Kanal ID (UC bilan boshlanadi) YOKI @handle",
                    "minLength": 1,
                },
            },
            "required": ["channel_id"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_id = params["channel_id"].strip()

        if not self.is_real:
            return _stub_channel(raw_id)

        # @handle → forHandle, aks holda id
        query: dict[str, Any] = {"part": "snippet,statistics"}
        if raw_id.startswith("@"):
            query["forHandle"] = raw_id
        elif raw_id.startswith("UC"):
            query["id"] = raw_id
        else:
            query["forUsername"] = raw_id  # legacy username

        data = await self._get("channels", query)
        items = data.get("items") or []
        if not items:
            raise ToolError(f"YouTube: kanal topilmadi: {raw_id}")

        item = items[0]
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        return {
            "channel_id": item.get("id"),
            "title": snippet.get("title", ""),
            "description": snippet.get("description", "")[:500],
            "subscribers": int(stats.get("subscriberCount", 0)),
            "views": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
            "published_at": snippet.get("publishedAt", ""),
            "source": "youtube.channel_stats",
        }


class YouTubeVideoStatsTool(_YouTubeHttpMixin, Tool):
    """Video statistikasi — ko'rishlar, layklar, izohlar (`videos.list`, 1 unit)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(api_key, client)

    @property
    def name(self) -> str:
        return "youtube.video_stats"

    @property
    def description(self) -> str:
        return "YouTube video statistikasi (ko'rishlar, layklar, izohlar, davomiyligi)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "video_id": {"type": "string", "description": "Video ID", "minLength": 1},
            },
            "required": ["video_id"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        video_id = params["video_id"].strip()

        if not self.is_real:
            return _stub_video(video_id)

        data = await self._get(
            "videos",
            {"part": "snippet,statistics,contentDetails", "id": video_id},
        )
        items = data.get("items") or []
        if not items:
            raise ToolError(f"YouTube: video topilmadi: {video_id}")

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        return {
            "video_id": item.get("id"),
            "title": snippet.get("title", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "description": snippet.get("description", "")[:500],
            "published_at": snippet.get("publishedAt", ""),
            "duration": content.get("duration", ""),  # ISO 8601 (PT3M15S)
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "source": "youtube.video_stats",
        }


# ── Yordamchi funksiyalar ────────────────────────────────────────────


def _format_search_item(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    id_obj = item.get("id", {})
    kind_key = id_obj.get("kind", "").removeprefix("youtube#")  # "video", "channel", "playlist"
    ref_id = id_obj.get("videoId") or id_obj.get("channelId") or id_obj.get("playlistId", "")
    return {
        "kind": kind_key,
        "id": ref_id,
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "published_at": snippet.get("publishedAt", ""),
        "description": snippet.get("description", "")[:300],
        "url": _url_for(kind_key, ref_id),
    }


def _url_for(kind: str, ref_id: str) -> str:
    if kind == "video":
        return f"https://www.youtube.com/watch?v={ref_id}"
    if kind == "channel":
        return f"https://www.youtube.com/channel/{ref_id}"
    if kind == "playlist":
        return f"https://www.youtube.com/playlist?list={ref_id}"
    return ""


def _stub_search(query: str, kind: str, count: int) -> dict[str, Any]:
    return {
        "query": query,
        "kind": kind,
        "results": [
            {
                "kind": kind,
                "id": f"stub-{i}",
                "title": f"[stub] {query} — natija {i + 1}",
                "channel": "Stub Channel",
                "published_at": "2026-01-01T00:00:00Z",
                "description": f"{query} haqida stub tavsif.",
                "url": _url_for(kind, f"stub-{i}"),
            }
            for i in range(min(count, 3))
        ],
        "total": min(count, 3),
        "source": "youtube.search (stub)",
    }


def _stub_channel(channel_id: str) -> dict[str, Any]:
    return {
        "channel_id": channel_id,
        "title": f"[stub] {channel_id}",
        "description": "Stub kanal — YouTube kaliti sozlanmagan",
        "subscribers": 0,
        "views": 0,
        "videos": 0,
        "published_at": "2026-01-01T00:00:00Z",
        "source": "youtube.channel_stats (stub)",
    }


def _stub_video(video_id: str) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "title": f"[stub] video {video_id}",
        "channel_title": "Stub Channel",
        "description": "Stub video — YouTube kaliti sozlanmagan",
        "published_at": "2026-01-01T00:00:00Z",
        "duration": "PT0S",
        "views": 0,
        "likes": 0,
        "comments": 0,
        "source": "youtube.video_stats (stub)",
    }


__all__ = [
    "YouTubeChannelStatsTool",
    "YouTubeSearchTool",
    "YouTubeVideoStatsTool",
]
