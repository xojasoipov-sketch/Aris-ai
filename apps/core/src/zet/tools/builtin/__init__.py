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

from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.note_write import NoteWriteTool
from zet.tools.builtin.shell_exec import ShellExecTool
from zet.tools.builtin.time_now import TimeNowTool
from zet.tools.builtin.web_reader import WebReaderTool
from zet.tools.builtin.web_search import WebSearchTool
from zet.tools.registry import ToolRegistry


def build_default_registry(
    *,
    notes_dir: Path,
    enable_shell: bool = False,
    web_reader_stub: bool = True,
    github_token: str | None = None,
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

    Returns:
        Ro'yxatga olingan `ToolRegistry`.
    """
    registry = ToolRegistry()
    registry.register(TimeNowTool())
    registry.register(NoteWriteTool(notes_dir=notes_dir))
    registry.register(WebSearchTool())
    registry.register(WebReaderTool(stub=web_reader_stub))
    registry.register(GitHubReadTool(token=github_token))
    registry.register(GitHubWriteTool(token=github_token))
    if enable_shell:
        registry.register(ShellExecTool(enabled=True))
    return registry


__all__ = ["build_default_registry"]
