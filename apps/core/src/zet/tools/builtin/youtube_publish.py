"""YouTube Publish tool — video yuklash (Bo'lim 7, C-03 #2).

`youtube.py` — READ (search, stats, no OAuth).
`youtube_publish.py` — WRITE (video upload, OAuth 2.0 kerak).

OAuth 2.0 oqimi (birinchi marta sozlash):
    1. Google Cloud Console → APIs & Services → Credentials
    2. OAuth 2.0 Client ID yaratish (Desktop app type)
    3. YouTube Data API v3 → Enable
    4. Scope: https://www.googleapis.com/auth/youtube.upload
    5. Consent screen'da o'zingizni Test User sifatida qo'shish
    6. `scripts/youtube_oauth.py` skriptni ishga tushirish (bir marta) —
       u brauzerni ochib refresh_token beradi. Uni `.env`ga saqlang.

Access token refresh: refresh_token → yangi access_token (~1 soat), Google
`/oauth2/v3/token` endpoint'ida. Har `_execute()` chaqiruvida token yangilanadi
(kesh yo'q — soddaligi uchun; ishlab chiqarish tomonida keshlashni qo'shish
mumkin).

Multipart upload: metadata JSON + video baytlari bir httpx request'da.
Videofayl kattaligi <128 GB (Google chegarasi), lekin timeout uchun katta
fayllarni resumable upload'ga o'tkazish tavsiya etiladi (hozir amalga
oshirilmagan — MVP uchun multipart yetarli).

Xavfsizlik:
    - permission_level = WRITE (V-32: approval kerak)
    - idempotent = False (har yuklash yangi video yaratadi)
    - Kvota: `videos.insert` = 1600 unit → kuniga ~6 video (10 000 kvota
      chegarasi bilan).

Bog'liq qarorlar:
    C-03 — biznes qamrovi (YouTube kanal)
    V-32 — publish har doim approval
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — bu URL, parol emas

# Ruxsat berilgan privacy qiymatlari (YouTube API)
_ALLOWED_PRIVACY = {"public", "unlisted", "private"}
# Ruxsat berilgan video toifalari (mostly used — full list: 22 kategoriya)
# Bu tool'da default 22 (People & Blogs) — SMM/vlog uchun eng keng tarqalgan
_DEFAULT_CATEGORY_ID = "22"


class YouTubePublishTool(Tool):
    """YouTube kanaliga video yuklash (OAuth 2.0 refresh_token bilan).

    Fail-open: OAuth ma'lumotlari yo'q → stub rejim (real API'ga chiqmaydi).
    """

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        return bool(self._client_id and self._client_secret and self._refresh_token)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Video yuklash sekin — 5 daqiqa timeout
            self._client = httpx.AsyncClient(timeout=300)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def name(self) -> str:
        return "youtube.publish"

    @property
    def description(self) -> str:
        return (
            "YouTube kanaliga video yuklash (mp4/mov). OAuth 2.0 refresh_token "
            "orqali ishlaydi. Kvota: 1600 unit/video. Approval kerak."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Mahalliy video fayl yo'li (absolute)",
                    "minLength": 1,
                },
                "title": {
                    "type": "string",
                    "description": "Video sarlavhasi (max 100 belgi)",
                    "minLength": 1,
                    "maxLength": 100,
                },
                "description": {
                    "type": "string",
                    "description": "Video tavsifi (max 5000 belgi)",
                    "maxLength": 5000,
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Video teglari (max 500 belgi jami)",
                    "maxItems": 30,
                },
                "privacy": {
                    "type": "string",
                    "enum": sorted(_ALLOWED_PRIVACY),
                    "description": "public/unlisted/private (default: private)",
                    "default": "private",
                },
                "category_id": {
                    "type": "string",
                    "description": "YouTube kategoriya ID (default 22 = People & Blogs)",
                    "default": _DEFAULT_CATEGORY_ID,
                },
            },
            "required": ["file_path", "title"],
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
        return False  # Har yuklash yangi video yaratadi

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        file_path = Path(params["file_path"])
        title = params["title"]
        description = params.get("description", "")
        tags = params.get("tags", [])
        privacy = params.get("privacy", "private")
        category_id = params.get("category_id", _DEFAULT_CATEGORY_ID)

        if privacy not in _ALLOWED_PRIVACY:
            raise ToolError(f"privacy noto'g'ri qiymati: {privacy}")

        if not self.is_real:
            return {
                "video_id": "",
                "url": "",
                "uploaded": False,
                "source": "youtube.publish (stub)",
            }

        # Fayl mavjudligi (sync IO — kichik chek, async'da xavfsiz)
        if not file_path.is_file():  # noqa: ASYNC240 — statik chek, tez
            raise ToolError(f"Video fayl topilmadi: {file_path}")

        # Access token olish (refresh)
        access_token = await self._refresh_access_token()

        # Multipart upload
        metadata = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        video_id = await self._upload_video(access_token, metadata, file_path)
        return {
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "uploaded": True,
            "privacy": privacy,
            "source": "youtube.publish",
        }

    async def _refresh_access_token(self) -> str:
        """Refresh token orqali yangi access_token olish."""
        try:
            response = await self._get_client().post(
                _TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.TimeoutException as exc:
            raise ToolError("YouTube OAuth token refresh timeout") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"YouTube OAuth tarmoq xatosi: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError(f"YouTube OAuth noJSON javob: {response.status_code}") from exc

        if response.status_code != 200 or "access_token" not in data:
            err = data.get("error_description") or data.get("error") or str(data)
            raise ToolError(f"YouTube OAuth token yangilash xatosi: {err}")

        token: str = data["access_token"]
        return token

    async def _upload_video(
        self,
        access_token: str,
        metadata: dict[str, Any],
        file_path: Path,
    ) -> str:
        """Multipart upload — metadata + video baytlari."""
        # Google multipart naqshi: `related` content-type, ikki qism —
        # birinchi JSON metadata, ikkinchi video baytlari.
        import json as _json
        import secrets

        boundary = f"----zet_boundary_{secrets.token_hex(16)}"
        # Sync read — kichik-o'rta video (<128 MB) uchun yetarli.
        # Kattaroq fayl uchun resumable upload'ga o'tish kerak (TODO).
        video_bytes = file_path.read_bytes()  # noqa: ASYNC240
        content_type = _guess_video_content_type(file_path.suffix.lower())

        body = (
            (
                f"--{boundary}\r\n"
                "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{_json.dumps(metadata)}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + video_bytes
            + f"\r\n--{boundary}--\r\n".encode()
        )

        try:
            response = await self._get_client().post(
                _UPLOAD_URL,
                params={"uploadType": "multipart", "part": "snippet,status"},
                content=body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f'multipart/related; boundary="{boundary}"',
                },
            )
        except httpx.TimeoutException as exc:
            raise ToolError("YouTube video yuklash timeout") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"YouTube video yuklash tarmoq xatosi: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError(f"YouTube upload noJSON: {response.status_code}") from exc

        if response.status_code >= 400 or "id" not in data:
            err = data.get("error", {})
            message = err.get("message", f"HTTP {response.status_code}")
            raise ToolError(f"YouTube video yuklash xatosi: {message}")

        video_id: str = data["id"]
        return video_id


def _guess_video_content_type(suffix: str) -> str:
    """Fayl kengaytmasi bo'yicha content-type. Noma'lum bo'lsa — video/mp4."""
    mapping = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }
    return mapping.get(suffix, "video/mp4")


__all__ = ["YouTubePublishTool"]
