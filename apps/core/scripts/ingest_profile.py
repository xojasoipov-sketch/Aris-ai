#!/usr/bin/env python3
"""Ega profilini ZET xotirasiga yuklaydi (V-13 PERSONAL qatlami).

Ega markdown profil yubordi (`BOSS_PROFILE.md`) — unda kim ekani, qaysi
loyihalar ustida ishlayotgani, texnik stek va ish uslubi yozilgan. ZET
buni bilishi kerak, aks holda har suhbatda noldan boshlanadi.

NEGA BITTA KATTA BLOK EMAS. Butun faylni bitta yozuv qilib qo'ysak,
semantik qidiruv ishlamay qoladi: "qaysi to'lov tizimini ishlataman?"
degan savolga 300 qatorlik matn qaytadi va LLM kontekstini to'ldiradi.
Shuning uchun fayl `##` sarlavhalari bo'yicha bo'linadi — har bo'lim
alohida yozuv, alohida vektor, alohida teg. Bo'lish mantig'i
`zet.memory.profile_ingest` umumiy modulida — xuddi shu mantiqdan
`POST /api/v1/memory/ingest-profile` HTTP endpoint'i ham foydalanadi,
ikkalasi bir xil natija bersin uchun.

Ishlatish:

    # Lokal (to'g'ridan-to'g'ri DB'ga)
    uv run python scripts/ingest_profile.py ../../BOSS_PROFILE.md

    # Produksiya (API orqali)
    uv run python scripts/ingest_profile.py PROFILE.md \\
        --api https://backend-....up.railway.app --token "$ZET_API_TOKEN"

Qayta ishga tushirish xavfsiz: bir xil `source` tegli eski yozuvlar
avval o'chiriladi (aks holda har yuklashda dublikat to'planardi).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from zet.memory.profile_ingest import SOURCE_TAG, _slug, split_sections


async def _ingest_via_api(
    sections: list[tuple[str, str]], *, api: str, token: str
) -> tuple[int, int]:
    """Yozuvlarni HTTP API orqali qo'shadi."""
    base = api.rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    added = failed = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        for title, content in sections:
            response = await client.post(
                f"{base}/api/v1/memory",
                headers=headers,
                json={
                    "layer": "personal",
                    "content": content,
                    "summary": title[:200],
                    "tags": [SOURCE_TAG, _slug(title)],
                    "source": SOURCE_TAG,
                },
            )
            if response.status_code == 201:
                added += 1
                print(f"  + {title}")
            else:
                failed += 1
                print(f"  ! {title} — HTTP {response.status_code}: {response.text[:120]}")

    return added, failed


async def main() -> int:
    parser = argparse.ArgumentParser(description="Ega profilini ZET xotirasiga yuklaydi")
    parser.add_argument("profile", type=Path, help="Markdown profil fayli")
    parser.add_argument("--api", required=True, help="ZET backend manzili")
    parser.add_argument("--token", required=True, help="ZET_API_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="Faqat bo'limlarni ko'rsatish")
    args = parser.parse_args()

    if not args.profile.exists():
        print(f"Fayl topilmadi: {args.profile}", file=sys.stderr)
        return 1

    sections = split_sections(args.profile.read_text(encoding="utf-8"))
    print(f"{len(sections)} ta bo'lim topildi ({args.profile.name})\n")

    if args.dry_run:
        for title, content in sections:
            print(f"  · {title:42} {len(content):>5} belgi")
        return 0

    added, failed = await _ingest_via_api(sections, api=args.api, token=args.token)
    print(f"\nQo'shildi: {added} · Xato: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
