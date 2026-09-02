"""Profil hujjatini xotira yozuvlariga bo'lish — umumiy mantiq (Bo'lim 2).

NEGA BU MODUL ALOHIDA. Ega profilini ZET xotirasiga yuklashning ikkita
yo'li bor: CLI skripti (`scripts/ingest_profile.py`, lokal DB yoki
mavjud API orqali) va HTTP endpoint (`POST /api/v1/memory/ingest-profile`,
fayl-yuklash orqali). Ikkalasi ham bitta savolga javob beradi — "markdown
hujjatni qanday bo'laklarga ajratamiz?" — va javob bir xil bo'lishi
SHART, aks holda bitta yo'l bilan yuklangan profil boshqa yo'l bilan
qayta yuklanganda boshqacha bo'linib, dublikat/nomuvofiq yozuvlar hosil
bo'ladi. Shu sabab bo'lish (splitting) mantig'i shu yerda — HTTP'ga ham,
fayl tizimiga ham bog'liq bo'lmagan sof matn funksiyalari — bir marta
yoziladi, ikkalasi shundan foydalanadi.
"""

from __future__ import annotations

import re

MAX_SECTION_CHARS = 3000
"""Bitta yozuvning maksimal uzunligi — undan uzun bo'lim bo'linadi."""

SOURCE_TAG = "boss-profile"
"""Barcha yozuvlarga qo'yiladigan teg — qayta yuklashda topish uchun."""


def _slug(title: str) -> str:
    """Sarlavhadan teg yasaydi: 'Active Projects' → 'active-projects'."""
    cleaned = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_]+", "-", cleaned)[:40]


def split_sections(markdown: str) -> list[tuple[str, str]]:
    """Markdown'ni `##` sarlavhalari bo'yicha bo'ladi.

    Returns:
        [(sarlavha, mazmun), ...] — mazmun sarlavhani ham o'z ichiga oladi,
        chunki yozuv o'z-o'zidan tushunarli bo'lishi kerak (qidiruvda u
        kontekstsiz qaytadi).
    """
    # `#` (h1) sarlavhasi hujjat nomi — bo'lim emas.
    body = re.sub(r"^#\s+.*$", "", markdown, count=1, flags=re.MULTILINE)

    parts = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    sections: list[tuple[str, str]] = []

    # `re.split` natijasi: [oldi, sarlavha1, matn1, sarlavha2, matn2, ...]
    for i in range(1, len(parts) - 1, 2):
        title = parts[i].strip()
        content = parts[i + 1].strip()
        if not content:
            continue
        full = f"{title}\n\n{content}"
        if len(full) <= MAX_SECTION_CHARS:
            sections.append((title, full))
            continue
        # Uzun bo'lim — `###` bo'yicha maydalaymiz
        for j, chunk in enumerate(_split_long(title, content), start=1):
            sections.append((f"{title} ({j})", chunk))

    return sections


def _split_long(title: str, content: str) -> list[str]:
    """Uzun bo'limni `###` yoki paragraf bo'yicha bo'lakchalarga ajratadi."""
    subs = re.split(r"^###\s+(.+)$", content, flags=re.MULTILINE)
    chunks: list[str] = []

    if len(subs) > 1:
        for i in range(1, len(subs) - 1, 2):
            text = subs[i + 1].strip()
            if text:
                chunks.append(f"{title} — {subs[i].strip()}\n\n{text}")
        if chunks:
            return chunks

    buffer = f"{title}\n\n"
    for paragraph in content.split("\n\n"):
        if len(buffer) + len(paragraph) > MAX_SECTION_CHARS:
            chunks.append(buffer.rstrip())
            buffer = f"{title} (davomi)\n\n"
        buffer += paragraph + "\n\n"
    if buffer.strip():
        chunks.append(buffer.rstrip())
    return chunks
