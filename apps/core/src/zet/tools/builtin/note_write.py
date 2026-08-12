"""note.write — lokal markdown eslatma yozish (Z1.10).

Ruxsat: WRITE — fayl yaratadi/o'zgartiradi.
Trust: SYSTEM — ichki tool.
Idempotent: ha — bir xil nom bilan qayta yoziladi.

Xavfsizlik:
    - Path traversal oldini oladi (faqat `notes_dir` ichida)
    - Fayl nomi sanitizatsiya qilinadi
    - Yozish hajmi chegaralangan (max 100 KB)

Bog'liq qarorlar:
    V-31 — WRITE ruxsat darajasi
    Bo'lim 2 — Obsidian integratsiyasi
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError
from zet.tools.builtin._vault import render_frontmatter, resolve_note_path

_MAX_CONTENT_BYTES = 100 * 1024  # 100 KB


class NoteWriteTool(Tool):
    """Lokal markdown eslatma yozadi."""

    def __init__(self, *, notes_dir: Path) -> None:
        self._notes_dir = notes_dir.resolve()

    @property
    def name(self) -> str:
        return "note.write"

    @property
    def description(self) -> str:
        return "Markdown formatida eslatma yozadi (yaratadi yoki ustiga yozadi)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Eslatma nomi (fayl nomi sifatida ishlatiladi, .md qo'shiladi)",
                    "minLength": 1,
                    "maxLength": 100,
                },
                "content": {
                    "type": "string",
                    "description": "Eslatma matni (Markdown)",
                    "minLength": 1,
                },
                "append": {
                    "type": "boolean",
                    "description": "True bo'lsa mavjud faylga qo'shadi, False bo'lsa ustiga yozadi",
                    "default": False,
                },
                "frontmatter": {
                    "type": "object",
                    "description": (
                        "YAML frontmatter sifatida saqlanadigan metama'lumot "
                        '(masalan: {"tags": ["loyiha"]}). `append=true` bilan birga ishlatilmaydi.'
                    ),
                },
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 10

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        title: str = params["title"]
        content: str = params["content"]
        append: bool = params.get("append", False)
        frontmatter: dict[str, Any] | None = params.get("frontmatter")

        if frontmatter and append:
            raise ToolError(
                "frontmatter va append birga ishlatilmaydi — frontmatter faqat "
                "yaratish/ustiga yozishda qo'llaniladi"
            )

        # Content hajmi tekshiruvi
        if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise ToolError(
                f"Eslatma matni {_MAX_CONTENT_BYTES // 1024} KB dan katta bo'lishi mumkin emas"
            )

        file_path = resolve_note_path(self._notes_dir, title)

        # Papka mavjudligini ta'minlash
        self._notes_dir.mkdir(parents=True, exist_ok=True)

        # Yozish
        existed = file_path.exists()
        if append and existed:
            with file_path.open("a", encoding="utf-8") as f:
                f.write("\n" + content)
            action = "appended"
        else:
            full_content = render_frontmatter(frontmatter or {}, content)
            file_path.write_text(full_content, encoding="utf-8")
            action = "updated" if existed else "created"

        return {
            "action": action,
            "path": str(file_path),
            "title": file_path.stem,
            "size_bytes": file_path.stat().st_size,
        }


__all__ = ["NoteWriteTool"]
