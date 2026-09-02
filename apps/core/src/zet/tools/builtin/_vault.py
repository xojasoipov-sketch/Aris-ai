"""Vault (Obsidian) papkasi uchun umumiy yordamchilar.

`note.write`/`note.read`/`note.list` toollarining barchasi shu modulni
ishlatadi — yo'l sanitizatsiyasi, YAML frontmatter va `[[wikilink]]`
mantig'i bir joyda, takrorlanmaydi.

Haqiqiy Obsidian vault'i **ichki papkalarga** ega (`Loyihalar/ZET.md`,
`Kundalik/2026-08-12.md`). Shuning uchun eslatma nomi `/` bilan
ajratilgan yo'l bo'lishi mumkin; har bir segment alohida sanitizatsiya
qilinadi va `..` qat'iy rad etiladi (path traversal).

Obsidian'ning o'z papkalari (`.obsidian`, `.trash`) va boshqa yashirin
papkalar indekslashda o'tkazib yuboriladi — ular eslatma emas.

Bog'liq qarorlar:
    Bo'lim 2 — Obsidian 2-tomonlama sinxron (markdown + frontmatter + backlink)
    V-31 — WRITE/READ ruxsat darajasi
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from zet.tools.base import ToolError

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")

_UNSAFE_CHARS_RE = re.compile(
    r"["
    r'<>:"/\\|?*'  # fayl tizimida taqiqlangan (Windows + POSIX)
    r"\x00-\x1f\x7f"  # boshqaruv belgilari
    r"​-‏‪-‮⁦-⁩"  # ko'rinmas / RTL spoofing
    r"]"
)
"""Ruxsat etilmagan belgilar. Qolgan hammasi — o'zbekcha lotin (okina bilan),
kirill, arab, xitoy, emoji — ruxsat etiladi: Obsidian ham shunday ishlaydi."""

_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

MAX_DEPTH = 8
"""Eslatma yo'lidagi maksimal papka chuqurligi (cheksiz ichma-ich oldini oladi)."""

MAX_SEGMENT_LEN = 100
"""Bitta papka/fayl nomi uzunligi chegarasi (fayl tizimi limitidan xavfsiz pastda)."""


def sanitize_segment(segment: str) -> str:
    """Bitta yo'l bo'lagini (papka yoki fayl nomi) tekshiradi.

    Unicode nomlar ruxsat etiladi (o'zbekcha, kirill, emoji) — Obsidian
    ham shunday ishlaydi. Faqat fayl tizimi uchun xavfli belgilar va
    yo'ldan chiqish (`..`) rad etiladi.

    Raises:
        ToolError: bo'lak bo'sh, `..`/`.`, juda uzun, xavfli belgili yoki
            Windows'da band nom (`CON`, `NUL`, ...).
    """
    cleaned = segment.strip()

    if cleaned in {"..", "."}:
        raise ToolError(f"Xavfsizlik: yo'lda '{cleaned}' ishlatib bo'lmaydi")

    # Oxiridagi nuqta/bo'shliq Windows'da fayl nomini buzadi
    cleaned = cleaned.rstrip(". ").lstrip(".")
    if not cleaned:
        raise ToolError("Eslatma nomi bo'sh bo'lishi mumkin emas")

    if len(cleaned) > MAX_SEGMENT_LEN:
        raise ToolError(f"Eslatma nomi juda uzun: {len(cleaned)} belgi (max {MAX_SEGMENT_LEN})")

    if _UNSAFE_CHARS_RE.search(cleaned):
        raise ToolError(
            f"Eslatma nomida ruxsat etilmagan belgi bor: '{segment}'. "
            r'Quyidagilar ishlatilmaydi: < > : " / \ | ? *'
        )

    if cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise ToolError(f"Eslatma nomi Windows'da band: '{cleaned}'")

    return cleaned


def sanitize_title(title: str) -> str:
    """Eslatma nomini (ichki papkalar bilan) xavfsiz nisbiy yo'lga o'giradi.

    `Loyihalar/ZET` → `Loyihalar/ZET`; bo'sh bo'laklar tashlab yuboriladi
    (`a//b` → `a/b`). `\\` ham papka ajratuvchi sifatida qabul qilinadi.

    Raises:
        ToolError: nom bo'sh, juda chuqur, `..` yoki yaroqsiz belgilar bilan.
    """
    raw_parts = [p for p in title.replace("\\", "/").split("/") if p.strip()]
    if not raw_parts:
        raise ToolError("Eslatma nomi bo'sh bo'lishi mumkin emas")

    if len(raw_parts) > MAX_DEPTH:
        raise ToolError(f"Eslatma yo'li juda chuqur: {len(raw_parts)} daraja (max {MAX_DEPTH})")

    return "/".join(sanitize_segment(p) for p in raw_parts)


def resolve_note_path(notes_dir: Path, title: str) -> Path:
    """Eslatma nomini `notes_dir` ichidagi to'liq yo'lga o'giradi.

    Raises:
        ToolError: nom yaroqsiz yoki natija `notes_dir`dan tashqarida (path traversal).
    """
    safe_title = sanitize_title(title)
    root = notes_dir.resolve()
    file_path = (root / f"{safe_title}.md").resolve()

    # Sanitizatsiyadan keyin ham yakuniy tekshiruv (symlink va h.k. uchun)
    if not file_path.is_relative_to(root):
        raise ToolError(f"Xavfsizlik: fayl yo'li vault papkasidan tashqarida: {title}")
    return file_path


def iter_notes(notes_dir: Path) -> Iterator[Path]:
    """Vault'dagi barcha `.md` fayllarni (ichki papkalar bilan) qaytaradi.

    Yashirin papkalar (`.obsidian`, `.trash`, `.git`) o'tkazib yuboriladi —
    ular eslatma emas, Obsidian/git ichki fayllari.
    """
    if not notes_dir.exists():
        return
    for path in sorted(notes_dir.rglob("*.md")):
        rel = path.relative_to(notes_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield path


def note_title(notes_dir: Path, path: Path) -> str:
    """Fayl yo'lini vault'ga nisbiy eslatma nomiga o'giradi (`Loyihalar/ZET`)."""
    rel = path.relative_to(notes_dir)
    return str(rel.with_suffix("")).replace("\\", "/")


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


def wikilink_targets(link: str, title: str) -> bool:
    """`[[link]]` havolasi `title` eslatmasiga ishora qiladimi (Obsidian semantikasi).

    Obsidian'da havola ham to'liq yo'l bilan (`[[Loyihalar/ZET]]`), ham
    faqat fayl nomi bilan (`[[ZET]]`) yozilishi mumkin — ikkalasi ham
    `Loyihalar/ZET.md` ga ishora qiladi.
    """
    normalized = link.replace("\\", "/").strip("/")
    if normalized == title:
        return True
    return "/" not in normalized and title.rsplit("/", 1)[-1] == normalized


__all__ = [
    "MAX_DEPTH",
    "extract_wikilinks",
    "iter_notes",
    "note_title",
    "render_frontmatter",
    "resolve_note_path",
    "sanitize_segment",
    "sanitize_title",
    "split_frontmatter",
    "wikilink_targets",
]
