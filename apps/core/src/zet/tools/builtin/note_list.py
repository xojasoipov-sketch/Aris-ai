"""note.list — vault'dagi eslatmalarni ro'yxatlash/qidirish (Bo'lim 2, gap-analysis #1).

Ilgari vault ichida nima borligini bilishning birorta yo'li yo'q edi —
agent faqat aniq nomi ma'lum eslatmani yozishi mumkin edi. Bu tool
sarlavha/tarkib bo'yicha oddiy substring qidiruvi bilan ro'yxat qaytaradi.

Ruxsat: READ.
Trust: SYSTEM.
Idempotent: ha.

Bog'liq qarorlar:
    V-31 — READ ruxsat darajasi
    Bo'lim 2 — Obsidian 2-tomonlama sinxron
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool
from zet.tools.builtin._vault import iter_notes, note_title

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


class NoteListTool(Tool):
    """Vault'dagi eslatmalarni ro'yxatlaydi — ixtiyoriy substring qidiruvi bilan."""

    def __init__(self, *, notes_dir: Path) -> None:
        self._notes_dir = notes_dir.resolve()

    @property
    def name(self) -> str:
        return "note.list"

    @property
    def description(self) -> str:
        return "Vault'dagi eslatmalar ro'yxati (ixtiyoriy: sarlavha/tarkib bo'yicha qidiruv)"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Sarlavha yoki tarkibda qidiriladigan matn (bo'sh — barchasi)",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Maksimal natija soni (default {_DEFAULT_LIMIT})",
                    "minimum": 1,
                    "maximum": _MAX_LIMIT,
                    "default": _DEFAULT_LIMIT,
                },
            },
            "required": [],
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
        return 15

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query: str = params.get("query", "") or ""
        limit: int = params.get("limit", _DEFAULT_LIMIT)
        query_lower = query.lower()

        matches: list[dict[str, Any]] = []
        for path in iter_notes(self._notes_dir):
            title = note_title(self._notes_dir, path)
            if query_lower:
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:  # pragma: no cover
                    continue
                if query_lower not in title.lower() and query_lower not in text.lower():
                    continue
            stat = path.stat()
            matches.append(
                {
                    "title": title,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )

        return {"notes": matches[:limit], "total": len(matches)}


__all__ = ["NoteListTool"]
