"""Telegram Bot API tool'lari — kanal statistikasi va xabar yuborish (Bo'lim 7).

**Chegara:** Telegram Bot API MTProto emas, u sanitizatsiya qilingan API —
bot faqat u administrator bo'lgan kanaldagi ma'lumotni ko'radi. Shuning uchun:
    - `telegram.channel_stats` — kanal a'zolar soni, admin ma'lumot
    - `telegram.channel_post` — kanalga post joylash (ega tasdig'i bilan)

**Analytics chegaralari:** Bot API `getChatMemberCount` va `getChat` beradi.
Chuqur analitika (impressions/reach) faqat rasmiy Telegram Analytics'da
ko'rinadi (kanal egasi web.telegram.org orqali). Bu tool'lar — real-vaqt
statistikasi (a'zolar soni, kanal metama'lumoti).

Fail-open: token yo'q → stub. Boshqa "real-vs-stub" tool'lar bilan bir xil.

Xavfsizlik:
    - channel_post PermissionLevel.WRITE — Orchestrator ega tasdig'ini so'raydi (V-32)
    - channel_stats PermissionLevel.READ + UNTRUSTED (kanal ma'lumoti sirtdan)

Bog'liq qarorlar:
    C-04 — ijtimoiy tarmoq boshqaruvi Telegram orqali
    V-32 — publish har doim approval
"""

from __future__ import annotations

from typing import Any

import httpx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

_API_BASE = "https://api.telegram.org"


class _TelegramHttpMixin:
    """Umumiy HTTP klient + xato ushlash."""

    _token: str | None
    _client: httpx.AsyncClient | None
    _owns_client: bool

    def _init_http(self, token: str | None, client: httpx.AsyncClient | None) -> None:
        self._token = token
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        return bool(self._token)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _api(self, method: str, payload: dict[str, Any]) -> Any:
        """`POST /bot{token}/{method}` — ok=True bo'lmasa `ToolError`ga aylantiradi.

        Telegram Bot API `result` maydoni har xil turdagi bo'lishi mumkin:
        `getChat` → dict, `getChatMemberCount` → int, `sendMessage` → dict.
        Shuning uchun qaytish turi `Any`.
        """
        try:
            response = await self._get_client().post(
                f"{_API_BASE}/bot{self._token}/{method}", json=payload
            )
        except httpx.TimeoutException as exc:
            raise ToolError(f"Telegram API timeout ({method})") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Telegram API tarmoq xatosi: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError(f"Telegram API noJSON javob: {response.status_code}") from exc

        if not data.get("ok"):
            desc = data.get("description", f"HTTP {response.status_code}")
            raise ToolError(f"Telegram API: {desc}")

        return data.get("result")


class TelegramChannelStatsTool(_TelegramHttpMixin, Tool):
    """Kanal statistikasi — a'zolar soni, kanal ma'lumoti.

    Bot @kanaldan **administrator** bo'lishi shart, aks holda 403.
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token, client)

    @property
    def name(self) -> str:
        return "telegram.channel_stats"

    @property
    def description(self) -> str:
        return (
            "Telegram kanal statistikasi — a'zolar soni, kanal ma'lumoti. "
            "Bot kanaldan administrator bo'lishi shart."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Kanal @username yoki -100...ID (kanal uchun manfiy)",
                    "minLength": 1,
                },
            },
            "required": ["chat_id"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        chat_id = params["chat_id"].strip()

        if not self.is_real:
            return _stub_channel(chat_id)

        # getChat — kanal metama'lumot (dict qaytaradi)
        info: dict[str, Any] = await self._api("getChat", {"chat_id": chat_id}) or {}
        # getChatMemberCount — a'zolar soni (int qaytaradi to'g'ridan-to'g'ri)
        count_data = await self._api("getChatMemberCount", {"chat_id": chat_id})
        try:
            member_count = int(count_data) if isinstance(count_data, int | str) else 0
        except (TypeError, ValueError):
            member_count = 0

        return {
            "chat_id": info.get("id"),
            "type": info.get("type"),  # "channel", "supergroup", ...
            "title": info.get("title", ""),
            "username": info.get("username", ""),
            "description": info.get("description", "")[:500],
            "member_count": member_count,
            "invite_link": info.get("invite_link", ""),
            "source": "telegram.channel_stats",
        }


class TelegramChannelPostTool(_TelegramHttpMixin, Tool):
    """Kanalga xabar joylash — WRITE, approval so'raladi (V-32).

    Bot kanaldan administrator + "Post Messages" ruxsatiga ega bo'lishi
    shart. Matn HTML formatida uzatiladi (aiogram bilan bir xil).
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._init_http(token, client)

    @property
    def name(self) -> str:
        return "telegram.channel_post"

    @property
    def description(self) -> str:
        return "Telegram kanaliga xabar joylash (HTML formatida). Approval kerak."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Kanal @username yoki -100...ID",
                    "minLength": 1,
                },
                "text": {
                    "type": "string",
                    "description": "Xabar matni (HTML: <b>, <i>, <code>, <a>)",
                    "minLength": 1,
                    "maxLength": 4096,
                },
                "disable_notification": {
                    "type": "boolean",
                    "description": "Sekin xabar (a'zolarga bildirishnoma yubormaydi)",
                    "default": False,
                },
            },
            "required": ["chat_id", "text"],
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
        return False  # Bir xil xabar qayta yuborilsa dublikat bo'ladi

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        chat_id = params["chat_id"]
        text = params["text"]
        disable_notification = params.get("disable_notification", False)

        if not self.is_real:
            return {
                "chat_id": chat_id,
                "message_id": 0,
                "posted": False,
                "source": "telegram.channel_post (stub)",
            }

        result: dict[str, Any] = (
            await self._api(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_notification": disable_notification,
                },
            )
            or {}
        )
        chat_info = result.get("chat") or {}
        return {
            "chat_id": chat_info.get("id", chat_id),
            "message_id": result.get("message_id", 0),
            "posted": True,
            "source": "telegram.channel_post",
        }


def _stub_channel(chat_id: str) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "type": "channel",
        "title": f"[stub] {chat_id}",
        "username": chat_id.lstrip("@"),
        "description": "Stub kanal — Telegram bot tokeni sozlanmagan",
        "member_count": 0,
        "invite_link": "",
        "source": "telegram.channel_stats (stub)",
    }


__all__ = ["TelegramChannelPostTool", "TelegramChannelStatsTool"]
