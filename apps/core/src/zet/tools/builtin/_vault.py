"""Vault (Obsidian-style markdown papka) uchun umumiy yordamchilar.

`note.write`/`note.read`/`note.list` toollarining barchasi shu modulni
ishlatadi — fayl nomi sanitizatsiyasi, YAML frontmatter va `[[wikilink]]`
mantig'i bir joyda, takrorlanmaydi.

Bog'liq qarorlar:
    Bo'lim 2 — Obsidian 2-tomonlama sinxron (markdown + frontmatter + backlink)
    V-31 — WRITE/READ ruxsat darajasi
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from zet.tools.base import ToolError

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-][a-zA-Z0-9_\- ]{0,98}$")
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")


def sanitize_title(title: str) -> str:
    """Eslatma nomini xavfsiz fayl nomiga o'giradi.

    Raises:
        ToolError: nom bo'sh yoki yaroqsiz.
    """
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


def resolve_note_path(notes_dir: Path, title: str) -> Path:
    """Eslatma nomini `notes_dir` ichidagi to'liq yo'lga o'giradi.

    Raises:
        ToolError: nom yaroqsiz yoki natija `notes_dir`dan tashqarida (path traversal).
    """
    safe_title = sanitize_title(title)
    file_path = (notes_dir / f"{safe_title}.md").resolve()
    if not str(file_path).startswith(str(notes_dir.resolve())):
        raise ToolError(f"Xavfsizlik: fayl yo'li notes papkasidan tashqarida: {title}")
    return file_path


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Matnni YAML frontmatter va tanaga ajratadi.

    Frontmatter yo'q yoki noto'g'ri formatda bo'lsa — bo'sh dict va butun
    matn tana sifatida qaytadi (fail-open — noto'g'ri frontmatter faylni
    o'qishga to'sqinlik qilmasligi kerak).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_yaml, body = match.groups()
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        return {}, text

    if not isinstance(parsed, dict):
        return {}, text
    return parsed, body


def render_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Frontmatter + tanani bitta fayl matniga birlashtiradi.

    `frontmatter` bo'sh bo'lsa — faqat tana qaytadi (frontmatter fenci qo'shilmaydi).
    """
    if not frontmatter:
        return body
    yaml_block = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip("\n")
    return f"---\n{yaml_block}\n---\n{body}"


def extract_wikilinks(text: str) -> list[str]:
    """Matndagi `[[Eslatma nomi]]` / `[[Nomi|Alias]]` / `[[Nomi#Bo'lim]]` havolalarini topadi.

    Natija — takrorlanmagan, birinchi uchrash tartibida.
    """
    seen: dict[str, None] = {}
    for raw in _WIKILINK_RE.findall(text):
        name = raw.strip()
        if name and name not in seen:
            seen[name] = None
    return list(seen)


__all__ = [
    "extract_wikilinks",
    "render_frontmatter",
    "resolve_note_path",
    "sanitize_title",
    "split_frontmatter",
]
