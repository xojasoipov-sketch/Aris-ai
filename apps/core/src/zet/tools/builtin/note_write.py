"""note.write — lokal markdown eslatma yozish (Z1.10).

Ruxsat: WRITE — fayl yaratadi/o'zgartiradi.
Trust: SYSTEM — ichki tool.
Idempotent: ha — bir xil nom bilan qayta yoziladi.

Xavfsizlik:
    - Path traversal oldini oladi (faqat `notes_dir` ichida)
    - Fayl nomi sanitizatsiya qilinadi
    - Yozish hajmi chegaralangan (max 100 KB)

OBSIDIAN↔POSTGRES KO'PRIGI (A-03).

Obsidian vault va Postgres xotira ilgari MUSTAQIL ishlagan — birida
yozilgan boshqasidan ko'rinmasdi. `memory.search` "shu haqda notekim
bor" deya olmasdi. Endi `memory_shadow_fn` uzatilsa har eslatma
yozilganda memory'ga QISQA shadow yozuvi qo'shiladi:

    layer: KNOWLEDGE (ega o'zi yozgan bilim)
    content: "Eslatma: <title> — <path>. Birinchi 500 belgi: ..."
    tags: ['note', <asl teg'lar>]
    source: 'obsidian:<title>'

Shu tarzda:
  - LLM'ga xotiradan "bu haqda notekim bor" yetib boradi
  - Faylning o'zi obidiandan hech qayerga ko'chirilmaydi (bitta manba
    saqlanadi — vault)
  - Shadow yiqilsa (memory offline) — note baribir yoziladi (fail-open)

Bog'liq qarorlar:
    V-31 — WRITE ruxsat darajasi
    Bo'lim 2 — Obsidian integratsiyasi
    A-03 — bilim manbaalari o'zaro bog'liq
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError
from zet.tools.builtin._vault import note_title, render_frontmatter, resolve_note_path

log = structlog.get_logger(__name__)

_MAX_CONTENT_BYTES = 100 * 1024  # 100 KB

_SHADOW_PREVIEW_CHARS = 500
"""Shadow yozuvida saqlanadigan boshlang'ich belgi soni.

Butun matn yozilsa memory jadvali bir necha marta katta bo'ladi —
matn markdown formatida allaqachon vault'da. Shu boshlang'ich yetarli:
`memory.search` topsa, LLM `note.read` bilan to'liq faylni ochadi."""


NoteMemoryShadowFn = Callable[..., "Awaitable[object]"]
"""(title, path, preview, tags) → shadow yozuv (fail-open — istisno yutiladi)."""


class NoteWriteTool(Tool):
    """Lokal markdown eslatma yozadi."""

    def __init__(
        self,
        *,
        notes_dir: Path,
        memory_shadow_fn: NoteMemoryShadowFn | None = None,
    ) -> None:
        self._notes_dir = notes_dir.resolve()
        # A-03: Obsidian↔Postgres ko'prigi. Berilmasa (test/lean) shadow
        # yozilmaydi va eski xatti-harakat saqlanadi.
        self._shadow_fn = memory_shadow_fn

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
                    "description": (
                        "Eslatma nomi (.md qo'shiladi). Ichki papka bilan ham bo'lishi "
                        "mumkin: 'Loyihalar/ZET' — papka avtomatik yaratiladi."
                    ),
                    "minLength": 1,
                    "maxLength": 400,
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

        # Papka mavjudligini ta'minlash (ichki papkalar bilan birga)
        file_path.parent.mkdir(parents=True, exist_ok=True)

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

        title_norm = note_title(self._notes_dir, file_path)

        # A-03 shadow. Memory yiqilsa asosiy natija (fayl saqlangan)
        # o'zgarmasin — istisno yutiladi.
        if self._shadow_fn is not None:
            preview = content[:_SHADOW_PREVIEW_CHARS]
            tags = ["note"]
            if isinstance(frontmatter, dict):
                raw_tags = frontmatter.get("tags")
                if isinstance(raw_tags, list):
                    tags.extend(str(t) for t in raw_tags if isinstance(t, str))
            try:
                await self._shadow_fn(
                    title=title_norm,
                    path=str(file_path),
                    preview=preview,
                    tags=tags,
                )
            except Exception:
                log.warning("note.write.shadow_failed", title=title_norm)

        return {
            "action": action,
            "path": str(file_path),
            "title": title_norm,
            "size_bytes": file_path.stat().st_size,
        }


__all__ = ["NoteWriteTool"]
