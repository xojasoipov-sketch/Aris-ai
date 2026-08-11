"""Xotira summarizer (Bo'lim 2).

Uzun matnlarni qisqartirish va xotira siqish uchun.

Strategiya:
    1. Oddiy — matn boshidan N belgi olish
    2. LLM — AI yordamida qisqartirish (Bo'lim 3 da)
    3. Hierarchical — qatlam bo'yicha siqish

Hozirgi versiya faqat (1) ni qo'llaydi.
LLM-based summarization Bo'lim 3 (LLM Router) dan keyin qo'shiladi.
"""

from __future__ import annotations

import re


def truncate_summary(text: str, max_length: int = 200) -> str:
    """Matnni kesib qisqartirish.

    So'z chegarasida kesadi (so'zning o'rtasida emas).

    Args:
        text: Asl matn.
        max_length: Maksimal uzunlik.

    Returns:
        Qisqartirilgan matn (agar kerak bo'lsa, "..." bilan).
    """
    text = text.strip()
    if len(text) <= max_length:
        return text

    # So'z chegarasida kesish
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.5:
        truncated = truncated[:last_space]

    return truncated.rstrip() + "..."


def extract_keywords(text: str, max_keywords: int = 10) -> list[str]:
    """Matndan kalit so'zlarni ajratish (oddiy).

    Stop-so'zlarni chiqaradi, faqat 3+ harfli so'zlarni oladi.
    """
    # Oddiy tokenizatsiya
    words = re.findall(r"\b[a-zA-ZЀ-ӿ]{3,}\b", text.lower())

    # Takrorlanmaslik va tartib saqlash
    seen: set[str] = set()
    unique: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique[:max_keywords]


def should_summarize(text: str, threshold: int = 500) -> bool:
    """Matn qisqartirish kerakmi."""
    return len(text) > threshold


def compress_conversation(
    messages: list[str],
    *,
    max_total: int = 2000,
    per_message: int = 200,
) -> str:
    """Suhbat xabarlarini siqish.

    Har bir xabarni qisqartiradi va umumiy limitga moslashtiradi.

    Args:
        messages: Xabarlar ro'yxati.
        max_total: Jami maksimal uzunlik.
        per_message: Har bir xabar uchun limit.

    Returns:
        Siqilgan matn.
    """
    parts: list[str] = []
    total_len = 0

    for msg in messages:
        summary = truncate_summary(msg, per_message)
        if total_len + len(summary) > max_total:
            remaining = max_total - total_len
            if remaining > 20:
                parts.append(truncate_summary(summary, remaining))
            break
        parts.append(summary)
        total_len += len(summary) + 1  # +1 for separator

    return "\n".join(parts)
