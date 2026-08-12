"""note.read — lokal markdown eslatmani o'qish (Bo'lim 2, gap-analysis #1).

Ilgari faqat `note.write` bor edi — yozilgan eslatmalarni birorta ham
tool qaytarib o'qiy olmasdi ("Core→disk only", ikki tomonlama emas).
Bu tool YAML frontmatter'ni ajratadi va `[[wikilink]]` havolalarini
(ham chiquvchi, ham kiruvchi — backlink) qaytaradi.

Ruxsat: READ.
Trust: SYSTEM.
Idempotent: ha.

Xavfsizlik:
    - Path traversal oldini oladi (faqat `notes_dir` ichida, `note.write`
      bilan bir xil `_vault.py` yordamchisi orqali)

Bog'liq qarorlar:
    V-31 — READ ruxsat darajasi
    Bo'lim 2 — Obsidian 2-tomonlama sinxron
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError
from zet.tools.builtin._vault import extract_wikilinks, resolve_note_path, split_frontmatter


class NoteReadTool(Tool):
    """Lokal markdown eslatmani o'qiydi — frontmatter va havolalar bilan."""

    def __init__(self, *, notes_dir: Path) -> None:
        self._notes_dir = notes_dir.resolve()

    @property
    def name(self) -> str:
        return "note.read"

    @property
    def description(self) -> str:
        return (
            "Markdown eslatmani o'qiydi — frontmatter, tana matni, chiquvchi va "
            "kiruvchi (backlink) [[havolalar]] bilan"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Eslatma nomi (fayl nomi, .md siz)",
                    "minLength": 1,
                    "maxLength": 100,
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 10

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        title: str = params["title"]
        file_path = resolve_note_path(self._notes_dir, title)

        if not file_path.exists():
            raise ToolError(f"Eslatma topilmadi: {title}")

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(raw)
        links = extract_wikilinks(body)
        backlinks = self._find_backlinks(file_path.stem)

        return {
            "title": file_path.stem,
            "path": str(file_path),
            "frontmatter": frontmatter,
            "content": body,
            "links": links,
            "backlinks": backlinks,
            "modified_at": file_path.stat().st_mtime,
        }

    def _find_backlinks(self, title: str) -> list[str]:
        """Vault ichidagi boshqa qaysi eslatmalar shu eslatmaga havola qilishini topadi."""
        if not self._notes_dir.exists():
            return []
        backlinks: list[str] = []
        for other in sorted(self._notes_dir.glob("*.md")):
            if other.stem == title:
                continue
            try:
                text = other.read_text(encoding="utf-8")
            except OSError:  # pragma: no cover — o'qib bo'lmaydigan fayl, o'tkazib yuborish
                continue
            if title in extract_wikilinks(text):
                backlinks.append(other.stem)
        return backlinks


__all__ = ["NoteReadTool"]
