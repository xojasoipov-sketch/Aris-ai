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
from zet.devices.desktop import DesktopProvider
from zet.tools.builtin.camera import CameraSnapshotTool
from zet.tools.builtin.desktop_tools import (
    DesktopKeyPressTool,
    DesktopMouseClickTool,
    DesktopScreenshotTool,
    DesktopTypeTextTool,
)
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.instagram import (
    InstagramAccountStatsTool,
    InstagramPublishPhotoTool,
    InstagramRecentMediaTool,
)
from zet.tools.builtin.memory_search import MemorySearchTool, SearchFn
from zet.tools.builtin.note_list import NoteListTool
from zet.tools.builtin.note_read import NoteReadTool
from zet.tools.builtin.note_write import NoteWriteTool
from zet.tools.builtin.shell_exec import ShellExecTool
from zet.tools.builtin.telegram_tools import (
    TelegramChannelPostTool,
    TelegramChannelStatsTool,
)
from zet.tools.builtin.time_now import TimeNowTool
from zet.tools.builtin.video_learn import DEFAULT_MODEL as DEFAULT_VIDEO_MODEL
from zet.tools.builtin.video_learn import VideoLearnTool
from zet.tools.builtin.web_reader import WebReaderTool
from zet.tools.builtin.web_search import WebSearchTool
from zet.tools.builtin.workspace_tools import WORKSPACE_TOOL_CLASSES, WorkspaceScope
from zet.tools.builtin.youtube import (
    YouTubeChannelStatsTool,
    YouTubeSearchTool,
    YouTubeVideoStatsTool,
)
from zet.tools.builtin.youtube_publish import YouTubePublishTool
from zet.tools.registry import ToolRegistry


def build_default_registry(
    *,
    notes_dir: Path,
    enable_shell: bool = False,
    web_reader_stub: bool = True,
    github_token: str | None = None,
    web_search_api_key: str | None = None,
    youtube_api_key: str | None = None,
    gemini_api_key: str | None = None,
    gemini_video_model: str | None = None,
    youtube_oauth_client_id: str | None = None,
    youtube_oauth_client_secret: str | None = None,
    youtube_oauth_refresh_token: str | None = None,
    telegram_bot_token: str | None = None,
    instagram_access_token: str | None = None,
    instagram_business_account_id: str | None = None,
    camera_provider: CameraProvider | None = None,
    desktop_provider: DesktopProvider | None = None,
    memory_search_fn: SearchFn | None = None,
    workspace_scope: WorkspaceScope | None = None,
    timezone: str = "Asia/Tashkent",
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
        gemini_api_key: berilsa — `video.learn` YouTube videosini to'liq ko'rib
            bilim ajratadi; bo'lmasa tool chaqirilganda tushunarli xato
            (soxta "bilim" qaytarish yolg'on bo'lardi, shuning uchun stub yo'q).
        telegram_bot_token: berilsa — `telegram.channel_stats`/`.channel_post`
            Telegram Bot API'siga chiqadi (bot kanaldan administrator bo'lishi
            shart); bo'lmasa — stub.
        instagram_access_token: berilsa (business_account_id bilan birga) —
            `instagram.*` tool'lar Meta Graph API'ga chiqadi; aks holda stub.
        instagram_business_account_id: Instagram Business Account ID
            (17-raqamli). Token bilan birga bo'lishi kerak.
        camera_provider: `camera.snapshot` uchun ulanish (default: `StubCamera`
            — real RTSP/EZVIZ hali ulanmagan).
        memory_search_fn: berilsa — `memory.search` uzoq muddatli xotiradan
            qidiradi. Berilmasa tool baribir ro'yxatda turadi, lekin
            chaqirilganda ochiq xato beradi: Planner uni ko'rib turgani
            ma'qul, aks holda ega haqidagi savolga yo'q eslatma fayllarini
            qidirib reja tuzadi (jonli tekshiruvda aynan shunday bo'ldi).
        workspace_scope: berilsa — `task.*`/`project.*`/`calendar.*` tool'lar
            haqiqiy doskaga yozadi va o'qiydi. Berilmasa tool'lar baribir
            ro'yxatda turadi, lekin chaqirilganda ochiq xato beradi (soxta
            bo'sh doska "hech qanday vazifa yo'q" degan YOLG'ON javobga
            olib kelardi). AYNAN shu argument `Capability.TASK_BOARD` va
            `Capability.CALENDAR`ni haqiqiy qiladi — `recipes.py`ga qarang.
        timezone: ega vaqt mintaqasi — kalendar va muddatlar shu mintaqada
            o'qiladi/yoziladi (baza doim UTC saqlaydi).
        desktop_provider: `desktop.*` tool'lar uchun ulanish (default:
            `StubDesktop(available=False)` — headless server muhitida). ZET
            foydalanuvchining mahalliy Mac/Win kompyuterida ishga tushirilsa,
            `PyAutoGUIDesktop` bilan almashtiriladi.

    Returns:
        Ro'yxatga olingan `ToolRegistry`.
    """
    registry = ToolRegistry()
    registry.register(TimeNowTool())
    registry.register(MemorySearchTool(search_fn=memory_search_fn))
    registry.register(NoteWriteTool(notes_dir=notes_dir))
    registry.register(NoteReadTool(notes_dir=notes_dir))
    registry.register(NoteListTool(notes_dir=notes_dir))
    registry.register(WebSearchTool(api_key=web_search_api_key))
    registry.register(WebReaderTool(stub=web_reader_stub))
    registry.register(GitHubReadTool(token=github_token))
    registry.register(GitHubWriteTool(token=github_token))
    registry.register(
        VideoLearnTool(api_key=gemini_api_key, model=gemini_video_model or DEFAULT_VIDEO_MODEL)
    )
    registry.register(YouTubeSearchTool(api_key=youtube_api_key))
    registry.register(YouTubeChannelStatsTool(api_key=youtube_api_key))
    registry.register(YouTubeVideoStatsTool(api_key=youtube_api_key))
    registry.register(
        YouTubePublishTool(
            client_id=youtube_oauth_client_id,
            client_secret=youtube_oauth_client_secret,
            refresh_token=youtube_oauth_refresh_token,
        )
    )
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
    for workspace_tool in WORKSPACE_TOOL_CLASSES:
        registry.register(workspace_tool(scope=workspace_scope, tz=timezone))
    registry.register(CameraSnapshotTool(provider=camera_provider))
    registry.register(DesktopScreenshotTool(provider=desktop_provider))
    registry.register(DesktopTypeTextTool(provider=desktop_provider))
    registry.register(DesktopKeyPressTool(provider=desktop_provider))
    registry.register(DesktopMouseClickTool(provider=desktop_provider))
    if enable_shell:
        registry.register(ShellExecTool(enabled=True))
    return registry


__all__ = ["build_default_registry"]
