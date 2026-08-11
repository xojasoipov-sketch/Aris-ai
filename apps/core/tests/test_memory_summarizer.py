"""Bo'lim 2 — Memory summarizer testlari.

Tekshiriladi:
    - truncate_summary — kesib qisqartirish
    - extract_keywords — kalit so'zlar
    - should_summarize — qisqartirish kerakmi
    - compress_conversation — suhbat siqish
"""

from __future__ import annotations

from zet.memory.summarizer import (
    compress_conversation,
    extract_keywords,
    should_summarize,
    truncate_summary,
)


class TestTruncateSummary:
    def test_short_text_unchanged(self) -> None:
        """Qisqa matn o'zgarmaydi."""
        assert truncate_summary("qisqa matn", 200) == "qisqa matn"

    def test_long_text_truncated(self) -> None:
        """Uzun matn kesiladi."""
        long = "bir " * 100
        result = truncate_summary(long, 50)
        assert len(result) <= 53  # "..." bilan
        assert result.endswith("...")

    def test_word_boundary(self) -> None:
        """So'z chegarasida kesiladi."""
        text = "Python dasturlash tili juda kuchli"
        result = truncate_summary(text, 20)
        assert result.endswith("...")
        # "..." dan oldingi qism to'liq so'z bilan tugashi kerak
        without_dots = result[:-3].rstrip()
        # Oxirgi belgi harf bo'lishi mumkin (so'z tugashi)
        assert len(without_dots) > 0

    def test_exact_length(self) -> None:
        """Huddi limitga teng matn kesilmaydi."""
        text = "hello"
        assert truncate_summary(text, 5) == "hello"

    def test_strips_whitespace(self) -> None:
        """Bosh va oxirdagi bo'shliqlar olib tashlanadi."""
        assert truncate_summary("  hello  ", 200) == "hello"


class TestExtractKeywords:
    def test_basic_extraction(self) -> None:
        """Oddiy kalit so'z ajratish."""
        text = "Python dasturlash tilini o'rganish"
        keywords = extract_keywords(text)
        assert "python" in keywords
        assert "dasturlash" in keywords

    def test_unique_only(self) -> None:
        """Takrorlanmas so'zlar."""
        text = "python python python java java"
        keywords = extract_keywords(text)
        assert keywords.count("python") == 1

    def test_min_length(self) -> None:
        """3 harfdan qisqa so'zlar chiqariladi."""
        text = "bu va o Python uchun"
        keywords = extract_keywords(text)
        assert "bu" not in keywords
        assert "va" not in keywords

    def test_max_keywords(self) -> None:
        """Maksimal soni cheklangan."""
        text = " ".join(f"word{i}xx" for i in range(20))
        keywords = extract_keywords(text, max_keywords=5)
        assert len(keywords) <= 5

    def test_empty_text(self) -> None:
        """Bo'sh matn — bo'sh ro'yxat."""
        assert extract_keywords("") == []


class TestShouldSummarize:
    def test_short_no(self) -> None:
        """Qisqa matn qisqartirish kerak emas."""
        assert should_summarize("qisqa", 500) is False

    def test_long_yes(self) -> None:
        """Uzun matn qisqartirish kerak."""
        assert should_summarize("x" * 501, 500) is True

    def test_exact_threshold(self) -> None:
        """Huddi chegarada — kerak emas."""
        assert should_summarize("x" * 500, 500) is False


class TestCompressConversation:
    def test_basic_compression(self) -> None:
        """Oddiy siqish."""
        messages = ["Salom, qanday yordam kerak?", "Python haqida savol bor"]
        result = compress_conversation(messages)
        assert "Salom" in result
        assert "Python" in result

    def test_limit_respected(self) -> None:
        """Jami limit saqlanadi."""
        messages = ["uzun matn " * 50 for _ in range(10)]
        result = compress_conversation(messages, max_total=200, per_message=100)
        assert len(result) <= 250  # biroz elastik

    def test_empty_messages(self) -> None:
        """Bo'sh xabarlar — bo'sh natija."""
        assert compress_conversation([]) == ""

    def test_single_message(self) -> None:
        """Bitta xabar."""
        result = compress_conversation(["Salom dunyo"])
        assert "Salom" in result
