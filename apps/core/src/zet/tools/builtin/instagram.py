"""Instagram Graph API tool'lari — kanal statistikasi va nashr (Bo'lim 7, C-04).

Instagram Business/Creator akkaunti orqali Meta Graph API'ga chiqiladi.
**Shaxsiy akkaunt qo'llab-quvvatlanmaydi** — Instagram'da uni Facebook Page
bilan bog'lash + Business/Creator ga o'tkazish shart.

Kerakli sozlamalar (Meta App Dashboard):
    1. Facebook App (App type: Business)
    2. Instagram Business Account (Instagram Basic Display emas!)
    3. Access Token — long-lived, scope:
       instagram_basic, instagram_content_publish, pages_show_list
    4. Business Account ID (17-raqamli)

Toollar:
    - instagram.account_stats — followers, media_count, username (READ, UNTRUSTED)
    - instagram.recent_media — oxirgi postlar ro'yxati (READ, UNTRUSTED)
    - instagram.publish_photo — foto+caption nashr qilish (WRITE, approval)

Nashr oqimi (Graph API `IG_USER_ID/media` → `IG_USER_ID/media_publish`):
    1. Container yaratish (`POST /{ig-user}/media` + `image_url`, `caption`)
    2. Container'ni nashr qilish (`POST /{ig-user}/media_publish` + `creation_id`)
    Bu 2 qadam — Instagram rasmni asinxron olib keladi.

Chegara: `image_url` OMMAVIY (public HTTPS) bo'lishi shart — Instagram
uni o'z serverida keshlaydi. Mahalliy fayl → yuqoriga chiqarilishi kerak
(masalan CDN/S3 orqali). Bu tool faqat URL qabul qiladi.

Fail-open: token yo'q → stub. Boshqa tool'lar bilan bir xil.

Xavfsizlik:
    - publish_photo PermissionLevel.WRITE — V-32 approval
    - account_stats / recent_media READ + UNTRUSTED (foydalanuvchi kontenti)

Bog'liq qarorlar:
    C-04 — ijtimoiy tarmoq (Instagram doim, Telegram boshqaruv)
    V-32 — publish har doim approval
    V-42 — UNTRUSTED belgi
"""

from __future__ import annotations

from typing import Any

import httpx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

_API_BASE = "https://graph.facebook.com/v21.0"


class _InstagramHttpMixin:
    """Umumiy HTTP klient + xato ushlash — barcha Instagram tool'lari uchun."""

    _access_token: str | None
    _ig_user_id: str | None
    _client: httpx.AsyncClient | None
    _owns_client: bool

    def _init_http(
        self,
        access_token: str | None,
        ig_user_id: str | None,
        client: httpx.AsyncClient | None,
    ) -> None:
        self._access_token = access_token
        self._ig_user_id = ig_user_id
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        return bool(self._access_token and self._ig_user_id)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """`GET /v21.0/{path}` — token qo'shiladi, xatolar `ToolError`ga."""
        try:
            response = await self._get_client().get(
                f"{_API_BASE}/{path}",
                params={**params, "access_token": self._access_token or ""},
            )
        except httpx.TimeoutException as exc:
            raise ToolError(f"Instagram API timeout ({path})") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Instagram API tarmoq xatosi: {exc}") from exc

        return self._parse(response, path)

    async def _post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """`POST /v21.0/{path}` — token qo'shiladi, xatolar `ToolError`ga."""
        try:
            response = await self._get_client().post(
                f"{_API_BASE}/{path}",
                data={**data, "access_token": self._access_token or ""},
            )
        except httpx.TimeoutException as exc:
            raise ToolError(f"Instagram API timeout ({path})") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Instagram API tarmoq xatosi: {exc}") from exc

        return self._parse(response, path)

    @staticmethod
    def _parse(response: httpx.Response, path: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError(f"Instagram API noJSON ({path}): {response.status_code}") from exc

        if response.status_code >= 400 or "error" in data:
            err = data.get("error", {})
            message = err.get("message", f"HTTP {response.status_code}")
            code = err.get("code", response.status_code)
            raise ToolError(f"Instagram API xato ({code}): {message}")

        return data  # type: ignore[no-any-return]


# ── Account stats ──────────────────────────────────────────────────


class InstagramAccountStatsTool(_InstagramHttpMixin, Tool):
    """Instagram Business akkaunt statistikasi — followers, media soni.

    `GET /{ig-user-id}?fields=username,name,media_count,followers_count,biography`
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        ig_user_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(access_token, ig_user_id, client)

    @property
    def name(self) -> str:
        return "instagram.account_stats"

    @property
    def description(self) -> str:
        return (
            "Instagram Business akkaunt statistikasi — followers, media_count, "
            "biography. Business/Creator akkaunt majburiy."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        # ig_user_id sozlamada — tool'ning inputi bo'sh (yoki alohida user_id
        # ko'rsatilsa uni ishlatadi, aks holda default'ga)
        return {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Ixtiyoriy: boshqa IG Business user ID (default: sozlangan)",
                }
            },
            "required": [],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        user_id = params.get("user_id") or self._ig_user_id

        if not self.is_real or not user_id:
            return _stub_account(user_id or "unknown")

        info = await self._get(
            str(user_id),
            {"fields": "id,username,name,biography,media_count,followers_count,follows_count"},
        )

        return {
            "user_id": info.get("id"),
            "username": info.get("username", ""),
            "name": info.get("name", ""),
            "biography": info.get("biography", "")[:500],
            "media_count": int(info.get("media_count", 0)),
            "followers_count": int(info.get("followers_count", 0)),
            "follows_count": int(info.get("follows_count", 0)),
            "source": "instagram.account_stats",
        }


# ── Recent media ───────────────────────────────────────────────────


class InstagramRecentMediaTool(_InstagramHttpMixin, Tool):
    """Instagram Business akkauntning oxirgi postlari.

    `GET /{ig-user-id}/media?fields=id,caption,media_type,permalink,timestamp,like_count,comments_count`
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        ig_user_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(access_token, ig_user_id, client)

    @property
    def name(self) -> str:
        return "instagram.recent_media"

    @property
    def description(self) -> str:
        return "Instagram akkauntning oxirgi N ta posti — caption, like, comment."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Nechta oxirgi post (1-25)",
                    "minimum": 1,
                    "maximum": 25,
                    "default": 10,
                },
                "user_id": {
                    "type": "string",
                    "description": "Ixtiyoriy: boshqa IG Business user ID (default: sozlangan)",
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        limit = min(max(int(params.get("limit", 10)), 1), 25)
        user_id = params.get("user_id") or self._ig_user_id

        if not self.is_real or not user_id:
            return {
                "user_id": user_id or "unknown",
                "media": [],
                "source": "instagram.recent_media (stub)",
            }

        data = await self._get(
            f"{user_id}/media",
            {
                "fields": (
                    "id,caption,media_type,permalink,timestamp,"
                    "like_count,comments_count,media_url,thumbnail_url"
                ),
                "limit": limit,
            },
        )

        items = data.get("data", [])
        media = [
            {
                "id": item.get("id"),
                "caption": (item.get("caption") or "")[:500],
                "media_type": item.get("media_type"),  # IMAGE / VIDEO / CAROUSEL_ALBUM
                "permalink": item.get("permalink", ""),
                "timestamp": item.get("timestamp", ""),
                "likes": int(item.get("like_count", 0)),
                "comments": int(item.get("comments_count", 0)),
                "media_url": item.get("media_url", ""),
                "thumbnail_url": item.get("thumbnail_url", ""),
            }
            for item in items
        ]

        return {
            "user_id": user_id,
            "media": media,
            "count": len(media),
            "source": "instagram.recent_media",
        }


# ── Publish photo (WRITE) ──────────────────────────────────────────


class InstagramPublishPhotoTool(_InstagramHttpMixin, Tool):
    """Foto nashr qilish — WRITE, approval so'raladi (V-32).

    2-qadamlik oqim:
        1. `POST /{ig-user}/media` + image_url + caption → creation_id
        2. `POST /{ig-user}/media_publish` + creation_id → media_id

    **`image_url` OMMAVIY HTTPS bo'lishi shart** — Instagram uni o'z
    serveriga keshlaydi. Mahalliy fayl → oldindan CDN/S3'ga yuklang.
    """

    def __init__(
        self,
        *,
        access_token: str | None = None,
        ig_user_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(access_token, ig_user_id, client)

    @property
    def name(self) -> str:
        return "instagram.publish_photo"

    @property
    def description(self) -> str:
        return (
            "Instagram Business akkauntga foto post nashr qilish. "
            "image_url ommaviy HTTPS bo'lishi shart. Approval kerak."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "Foto uchun ommaviy HTTPS URL (JPEG, <8 MB)",
                    "pattern": "^https?://.+",
                    "minLength": 10,
                },
                "caption": {
                    "type": "string",
                    "description": "Post matni + hashtaglar (max 2200 belgi)",
                    "maxLength": 2200,
                },
            },
            "required": ["image_url"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.SYSTEM

    @property
    def idempotent(self) -> bool:
        return False  # Bir xil post qayta yuborilsa dublikat bo'ladi

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        image_url = params["image_url"]
        caption = params.get("caption", "")

        if not self.is_real or not self._ig_user_id:
            return {
                "media_id": "",
                "creation_id": "",
                "posted": False,
                "source": "instagram.publish_photo (stub)",
            }

        # 1-qadam: container yaratish
        container = await self._post(
            f"{self._ig_user_id}/media",
            {"image_url": image_url, "caption": caption},
        )
        creation_id = container.get("id")
        if not creation_id:
            raise ToolError("Instagram: container ID qaytmadi")

        # 2-qadam: nashr qilish
        result = await self._post(
            f"{self._ig_user_id}/media_publish",
            {"creation_id": creation_id},
        )
        media_id = result.get("id")

        return {
            "media_id": str(media_id) if media_id else "",
            "creation_id": str(creation_id),
            "posted": bool(media_id),
            "source": "instagram.publish_photo",
        }


def _stub_account(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "username": f"stub_{user_id}",
        "name": "[stub] Instagram akkaunt",
        "biography": "Stub — Instagram access token sozlanmagan",
        "media_count": 0,
        "followers_count": 0,
        "follows_count": 0,
        "source": "instagram.account_stats (stub)",
    }


__all__ = [
    "InstagramAccountStatsTool",
    "InstagramPublishPhotoTool",
    "InstagramRecentMediaTool",
]
