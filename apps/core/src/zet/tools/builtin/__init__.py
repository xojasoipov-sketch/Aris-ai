"""Built-in toollar — Bo'lim 1, 3, 7 uchun ro'yxatga olinadigan toollar.

`build_default_registry()` — barcha builtin toollarni bitta `ToolRegistry`ga
yig'adi. API va CLI shu funksiyadan foydalanadi — har birida alohida-alohida
bo'sh registry yaratilmaydi (avvalgi xato: har so'rovda bo'sh `ToolRegistry()`
yaratilar edi, hech qanday tool ishlamas edi).

Bog'liq qarorlar:
    Bo'lim 1 — time.now, note.write
    Bo'lim 3 — web.search (stub)
    Bo'lim 7 — github.read/write, web.read
"""

from __future__ import annotations

from pathlib import Path

from zet.devices.camera import CameraProvider
from zet.tools.builtin.camera import CameraSnapshotTool
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.instagram import (
    InstagramAccountStatsTool,
    InstagramPublishPhotoTool,
    InstagramRecentMediaTool,
)
from zet.tools.builtin.note_list import NoteListTool
from zet.tools.builtin.note_read import NoteReadTool
from zet.tools.builtin.note_write import NoteWriteTool
from zet.tools.builtin.shell_exec import ShellExecTool
from zet.tools.builtin.telegram_tools import (
    TelegramChannelPostTool,
    TelegramChannelStatsTool,
)
from zet.tools.builtin.time_now import TimeNowTool
from zet.tools.builtin.web_reader import WebReaderTool
from zet.tools.builtin.web_search import WebSearchTool
from zet.tools.builtin.youtube import (
    YouTubeChannelStatsTool,
    YouTubeSearchTool,
    YouTubeVideoStatsTool,
)
from zet.tools.registry import ToolRegistry


def build_default_registry(
    *,
    notes_dir: Path,
    enable_shell: bool = False,
    web_reader_stub: bool = True,
    github_token: str | None = None,
    web_search_api_key: str | None = None,
    youtube_api_key: str | None = None,
    telegram_bot_token: str | None = None,
    instagram_access_token: str | None = None,
    instagram_business_account_id: str | None = None,
    camera_provider: CameraProvider | None = None,
) -> ToolRegistry:
    """Barcha builtin toollarni ro'yxatga olib, tayyor `ToolRegistry` qaytaradi.

    Args:
        notes_dir: `note.write` tooli uchun eslatmalar papkasi (odatda
            `Settings.vault_dir`).
        enable_shell: `shell.exec` toolini ro'yxatga qo'shish (default:
            o'chirilgan — eng xavfli komponent, faqat aniq yoqilganda).
        web_reader_stub: `web.read` stub rejimida ishlasinmi (default: ha).
            Haqiqiy tarmoq chaqiruvi uchun `False` bering.
        github_token: berilsa — `github.read`/`github.write` haqiqiy API'ga
            chiqadi; bo'lmasa (default) — stub rejim.
        web_search_api_key: berilsa — `web.search` haqiqiy qidiradi (Brave
            Search API); bo'lmasa (default) — stub rejim.
        youtube_api_key: berilsa — `youtube.search`/`.channel_stats`/`.video_stats`
            YouTube Data API v3'ga chiqadi; bo'lmasa (default) — stub rejim.
        telegram_bot_token: berilsa — `telegram.channel_stats`/`.channel_post`
            Telegram Bot API'siga chiqadi (bot kanaldan administrator bo'lishi
            shart); bo'lmasa — stub.
        instagram_access_token: berilsa (business_account_id bilan birga) —
            `instagram.*` tool'lar Meta Graph API'ga chiqadi; aks holda stub.
        instagram_business_account_id: Instagram Business Account ID
            (17-raqamli). Token bilan birga bo'lishi kerak.
        camera_provider: `camera.snapshot` uchun ulanish (default: `StubCamera`
            — real RTSP/EZVIZ hali ulanmagan).

    Returns:
        Ro'yxatga olingan `ToolRegistry`.
    """
    registry = ToolRegistry()
    registry.register(TimeNowTool())
    registry.register(NoteWriteTool(notes_dir=notes_dir))
    registry.register(NoteReadTool(notes_dir=notes_dir))
    registry.register(NoteListTool(notes_dir=notes_dir))
    registry.register(WebSearchTool(api_key=web_search_api_key))
    registry.register(WebReaderTool(stub=web_reader_stub))
    registry.register(GitHubReadTool(token=github_token))
    registry.register(GitHubWriteTool(token=github_token))
    registry.register(YouTubeSearchTool(api_key=youtube_api_key))
    registry.register(YouTubeChannelStatsTool(api_key=youtube_api_key))
    registry.register(YouTubeVideoStatsTool(api_key=youtube_api_key))
    registry.register(TelegramChannelStatsTool(token=telegram_bot_token))
    registry.register(TelegramChannelPostTool(token=telegram_bot_token))
    registry.register(
        InstagramAccountStatsTool(
            access_token=instagram_access_token,
            ig_user_id=instagram_business_account_id,
        )
    )
    registry.register(
        InstagramRecentMediaTool(
            access_token=instagram_access_token,
            ig_user_id=instagram_business_account_id,
        )
    )
    registry.register(
        InstagramPublishPhotoTool(
            access_token=instagram_access_token,
            ig_user_id=instagram_business_account_id,
        )
    )
    registry.register(CameraSnapshotTool(provider=camera_provider))
    if enable_shell:
        registry.register(ShellExecTool(enabled=True))
    return registry


__all__ = ["build_default_registry"]
