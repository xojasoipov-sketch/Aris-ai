"""Xotira qidiruvi uchun o'xshashlik hisoblash — kalit-so'z va vektor (Bo'lim 2).

`MemoryStore` (in-memory) va `PgMemoryStore` (DB-backed) bir xil
strategiyani ishlatadi — takrorlanmasin deb bir joyda.

Ilgari faqat kalit-so'z (substring/so'z-overlap) balli bor edi — `embedding`
ustuni hech qachon to'ldirilmasdi va hisobga olinmasdi (gap-analysis:
"memory search is pure keyword matching despite embedding column existing").
`hybrid_score()` shu ikkalasini birlashtiradi.

Bog'liq qarorlar:
    Bo'lim 2 — pgvector + hybrid search (BM25 + vektor), reranking
"""

from __future__ import annotations

import math

_VECTOR_WEIGHT = 0.6
_KEYWORD_WEIGHT = 0.4
"""Semantik moslikka ko'proq vazn — lekin kalit-so'z hech qachon nolga
tushmaydi, chunki embedding hisoblanmagan/mavjud bo'lmagan yozuvlar ham
qidiruvda topilishi kerak (fail-open)."""


def keyword_score(query_text: str, content: str, summary: str | None = None) -> float:
    """Oddiy substring/so'z-overlap o'xshashligi (0.0-1.0)."""
    score = 0.0
    query_lower = query_text.lower()
    content_lower = content.lower()
    summary_lower = (summary or "").lower()

    if query_lower in content_lower:
        score = max(score, 0.8)
    elif query_lower in summary_lower:
        score = max(score, 0.75)

    query_words = set(query_lower.split())
    content_words = set(content_lower.split())
    if query_words and content_words:
        overlap = len(query_words & content_words)
        word_score = overlap / max(len(query_words), 1) * 0.7
        score = max(score, word_score)

    return score


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity ikki vektor orasida.

    Bo'sh yoki uzunligi farqli vektorlar uchun 0.0 qaytaradi.
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def hybrid_score(*, keyword: float, vector: float | None) -> float:
    """Kalit-so'z va vektor balllarini birlashtiradi.

    `vector` `None` bo'lsa (embedding hisoblanmagan, provider ulanmagan
    yoki yozuvda saqlanmagan) — faqat kalit-so'z balli ishlatiladi:
    semantik qidiruv yo'qligi natija bermay qolishiga sabab bo'lmasligi
    kerak (fail-open).
    """
    if vector is None:
        return keyword
    blended = _KEYWORD_WEIGHT * keyword + _VECTOR_WEIGHT * max(vector, 0.0)
    return min(blended, 1.0)


__all__ = ["cosine_similarity", "hybrid_score", "keyword_score"]
