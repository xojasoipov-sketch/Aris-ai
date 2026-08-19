"""`public-apis/public-apis` README.md'ni xom qatorlarga ajratuvchi parser.

HAQIQIY FORMAT (2026-08, `README.md`dan to'g'ridan-to'g'ri tekshirilgan):

    ### Kategoriya Nomi

    API | Description | Auth | HTTPS | CORS |
    |:---|:---|:---|:---|:---|
    | [Nomi](https://homepage) | Tavsif | `apiKey` | Yes | Yes |
    | [Boshqa](https://x) | Tavsif | No | Yes | Unknown |

`Auth` ustuni ikki ko'rinishda keladi: oddiy matn `No` (kalitsiz) yoki
backtick bilan o'ralgan `` `apiKey` ``/`` `OAuth` ``/`` `bearer` `` va h.k.

Bu modul FAQAT satrlarni ajratadi — normalizatsiya (`AuthType`/
`PricingStatus`ga o'girish) `normalizer.py`da.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CATEGORY_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_ROW_RE = re.compile(
    r"^\|\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)\s*\|"
    r"\s*(?P<description>[^|]*?)\s*\|"
    r"\s*(?P<auth>[^|]*?)\s*\|"
    r"\s*(?P<https>[^|]*?)\s*\|"
    r"\s*(?P<cors>[^|]*?)\s*\|?\s*$",
    re.MULTILINE,
)
_SEPARATOR_ROW_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*\|")
_TABLE_HEADER_RE = re.compile(r"^API\s*\|\s*Description\s*\|\s*Auth\s*\|", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RawEntry:
    """Parse bosqichining xom (normalizatsiyalanmagan) chiqishi."""

    category: str
    name: str
    homepage_url: str
    description: str
    auth_raw: str
    https_raw: str
    cors_raw: str


def parse_readme(text: str) -> list[RawEntry]:
    """README matnini `RawEntry` ro'yxatiga ajratadi.

    Diqqatga: markdown formati o'zgarishi mumkin bo'lgan tashqi
    manba — bu funksiya XATO OTMAYDI, faqat tushunadigan qatorlarni
    qaytaradi (bo'sh/moslashmagan kategoriyalar jimgina o'tkazib
    yuboriladi — Bo'lim 3: "ingestion, execution emas", noto'g'ri
    formatlangan bitta qator butun sync'ni yiqitmasligi kerak).
    """
    entries: list[RawEntry] = []
    current_category: str | None = None

    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        cat_match = _CATEGORY_RE.match(line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            i += 1
            continue

        if current_category is not None and _TABLE_HEADER_RE.match(line.strip()):
            # Keyingi qator — ajratuvchi (|:---|:---|...) bo'lishi kerak,
            # keyin haqiqiy qatorlar boshlanadi.
            i += 1
            if i < n and _SEPARATOR_ROW_RE.match(lines[i].strip()):
                i += 1
            while i < n:
                row_line = lines[i].strip()
                if not row_line.startswith("|"):
                    break  # jadval tugadi
                row_match = _ROW_RE.match(row_line)
                if row_match:
                    entries.append(
                        RawEntry(
                            category=current_category,
                            name=row_match.group("name").strip(),
                            homepage_url=row_match.group("url").strip(),
                            description=row_match.group("description").strip(),
                            auth_raw=row_match.group("auth").strip(),
                            https_raw=row_match.group("https").strip(),
                            cors_raw=row_match.group("cors").strip(),
                        )
                    )
                i += 1
            continue

        i += 1

    return entries


__all__ = ["RawEntry", "parse_readme"]
