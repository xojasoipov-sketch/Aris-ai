"""Kalit so'z qidiruvi — `CapabilityRegistry.search()` bilan bir xil
oddiy pastki-satr-sanash naqshi (`core/capability.py`), LLM chaqiruvisiz.

Bu funksiya XOM natija qaytaradi (mos kelgan yozuvlar + xom ball) —
`ranker.py` buni sog'liq/ishonch/https/auth bilan birlashtirib
YAKUNIY reytingni chiqaradi.
"""

from __future__ import annotations

from dataclasses import dataclass

from zet.integrations.public_apis.catalog.models import PublicAPIEntry


@dataclass(frozen=True, slots=True)
class SearchMatch:
    entry: PublicAPIEntry
    score: int
    """Kalit so'z mos kelish soni — ball emas, XOM hisob (ranker.py
    buni normallashtiradi)."""


def search_catalog(
    entries: list[PublicAPIEntry], keywords: list[str], *, limit: int = 20
) -> list[SearchMatch]:
    """Katalog yozuvlarini kalit so'zlar bo'yicha qidiradi.

    Har bir yozuv uchun ball — `name`/`description`/`category`/
    `capabilities`/`provider` maydonlaridagi kalit so'z uchrashlari
    soni (pastki registrga keltirib). Ball 0 bo'lgan yozuvlar
    qaytarilmaydi.
    """
    if not keywords:
        return []
    lowered_keywords = [k.strip().lower() for k in keywords if k.strip()]
    if not lowered_keywords:
        return []

    matches: list[SearchMatch] = []
    for entry in entries:
        haystacks = [
            entry.name.lower(),
            entry.description.lower(),
            entry.category.lower(),
            entry.provider.lower(),
            " ".join(entry.capabilities).lower(),
        ]
        blob = " ".join(haystacks)
        score = sum(blob.count(kw) for kw in lowered_keywords)
        if score > 0:
            matches.append(SearchMatch(entry=entry, score=score))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:limit]


def search_by_capability(entries: list[PublicAPIEntry], capability: str) -> list[PublicAPIEntry]:
    """Aniq capability tegiga ega yozuvlarni qaytaradi (masalan
    "geocoding") — `matcher.py`/fallback tanlovi shu orqali ishlaydi."""
    tag = capability.strip().lower()
    return [e for e in entries if tag in {c.lower() for c in e.capabilities}]


__all__ = ["SearchMatch", "search_by_capability", "search_catalog"]
