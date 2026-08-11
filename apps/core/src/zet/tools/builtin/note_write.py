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

import re
from pathlib import Path
from typing import Any

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError

_MAX_CONTENT_BYTES = 100 * 1024  # 100 KB
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-][a-zA-Z0-9_\- ]{0,98}$")


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

        # Content hajmi tekshiruvi
        if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise ToolError(
                f"Eslatma matni {_MAX_CONTENT_BYTES // 1024} KB dan katta bo'lishi mumkin emas"
            )

        # Fayl nomi sanitizatsiyasi
        safe_title = self._sanitize_title(title)
        file_path = (self._notes_dir / f"{safe_title}.md").resolve()

        # Path traversal tekshiruvi
        if not str(file_path).startswith(str(self._notes_dir)):
            raise ToolError(f"Xavfsizlik: fayl yo'li notes papkasidan tashqarida: {title}")

        # Papka mavjudligini ta'minlash
        self._notes_dir.mkdir(parents=True, exist_ok=True)

        # Yozish
        existed = file_path.exists()
        if append and existed:
            with file_path.open("a", encoding="utf-8") as f:
                f.write("\n" + content)
            action = "appended"
        else:
            file_path.write_text(content, encoding="utf-8")
            action = "updated" if existed else "created"

        return {
            "action": action,
            "path": str(file_path),
            "title": safe_title,
            "size_bytes": file_path.stat().st_size,
        }

    def _sanitize_title(self, title: str) -> str:
        """Fayl nomini xavfsiz qiladi.

        Raises:
            ToolError: nom yaroqsiz
        """
        # Yo'l ajratuvchilarini olib tashlash
        cleaned = title.replace("/", "_").replace("\\", "_").replace("..", "_")
        cleaned = cleaned.strip().strip(".")

        if not cleaned:
            raise ToolError("Eslatma nomi bo'sh bo'lishi mumkin emas")

        if not _SAFE_FILENAME_RE.match(cleaned):
            raise ToolError(
                f"Eslatma nomi xavfsiz emas: '{title}'. "
                "Faqat harflar, raqamlar, chiziq (-), pastki chiziq (_) va bo'shliq ishlatiladi."
            )

        return cleaned
