"""Injection himoyasi — UNTRUSTED kontentda xavfli patternlarni aniqlash (Bo'lim 7).

A-05 xavfsizlik chegarasi: tashqi kontentda (issue, PR, web sahifa, Telegram xabar)
tizim buyruqlari yoki injection urinishlarini aniqlash va bloklash.

Qoidalar:
    - UNTRUSTED kontentda tizim buyruqlari topilsa → BLOKLANADI
    - Himoya qatlamlari: pattern matching + heuristic scoring
    - False positive ga nisbatan false negative xavfliroq

Bog'liq qarorlar:
    A-05 — untrusted input chegarasi
    Bo'lim 7 — injection test to'plami
    V-31 — ruxsat darajalari
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

import structlog

log = structlog.get_logger(__name__)


class InjectionType(StrEnum):
    """Injection turi."""

    PROMPT_INJECTION = "prompt_injection"
    """System prompt ni o'zgartirishga urinish."""

    PRIVILEGE_ESCALATION = "privilege_escalation"
    """Ruxsat darajasini oshirishga urinish."""

    COMMAND_INJECTION = "command_injection"
    """Tizim buyruqlarini kiritish."""

    DATA_EXFILTRATION = "data_exfiltration"
    """Ma'lumotlarni chiqarib olishga urinish."""

    SOCIAL_ENGINEERING = "social_engineering"
    """Ijtimoiy muhandislik hujumi."""


@dataclass(frozen=True)
class InjectionMatch:
    """Aniqlangan injection."""

    injection_type: InjectionType
    pattern: str
    matched_text: str
    confidence: float  # 0.0 — 1.0


@dataclass(frozen=True)
class ScanResult:
    """Skanerlash natijasi."""

    is_safe: bool
    """True bo'lsa, xavfli pattern topilmadi."""

    matches: tuple[InjectionMatch, ...] = field(default_factory=tuple)
    """Topilgan injection patternlari."""

    score: float = 0.0
    """Umumiy xavf bali (0.0 — 1.0). 0.5 dan yuqori = bloklash."""

    @property
    def blocked(self) -> bool:
        """Bloklash kerakmi."""
        return not self.is_safe


# ── Pattern katalogi ─────────────────────────────────────────────

# Prompt injection patternlari
_PROMPT_INJECTION_PATTERNS: list[tuple[str, float]] = [
    (r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?|prompts?)", 0.95),
    (r"(?i)you\s+are\s+now\s+a?\s*(new|different)", 0.9),
    (r"(?i)forget\s+(everything|all|your)(\s+\w+)*\s+(rules?|instructions?|training)", 0.95),
    (r"(?i)system\s*:\s*you\s+are", 0.85),
    (r"(?i)new\s+system\s+prompt", 0.9),
    (r"(?i)act\s+as\s+(if\s+)?(you\s+are\s+)?(admin|root|system)", 0.85),
    (r"(?i)override\s+(your\s+)?(instructions?|rules?|settings?)", 0.9),
    (r"(?i)disregard\s+(all\s+)?(previous|safety|security)", 0.95),
    # O'zbek tilida
    (r"(?i)oldingi\s+(qoidalar|ko'rsatmalar|buyruqlar)ni\s+(unut|o'chir|ignor)", 0.95),
    (r"(?i)sen\s+endi\s+(admin|root|tizim)", 0.85),
    (r"(?i)tizim\s+sozlamalarini\s+o'zgartir", 0.9),
]

# Privilege escalation patternlari
_PRIVILEGE_PATTERNS: list[tuple[str, float]] = [
    (r"(?i)give\s+me\s+(admin|root|full)\s+(access|permission|control)", 0.9),
    (r"(?i)grant\s+(admin|write|execute)\s+(permission|access)", 0.9),
    (r"(?i)(make|set)\s+(me|user)\s+(admin|owner|root)", 0.9),
    (r"(?i)api\s*[-_]?\s*key|secret\s*[-_]?\s*key|token\s*[-_]?\s*ber", 0.85),
    (r"(?i)password|parol|maxfiy\s+kalitni?\s+(ber|ko'rsat|yubor)", 0.9),
    # O'zbek tilida
    (r"(?i)(admin|ega)\s+(qil|yasa|o'zgartir)", 0.85),
    (r"(?i)ruxsat\s+(ber|oshir|o'zgartir)", 0.8),
]

# Command injection patternlari
_COMMAND_PATTERNS: list[tuple[str, float]] = [
    (r"(?i)run\s+(command|shell|bash|cmd)", 0.85),
    (r"(?i)exec(ute)?\s*\(", 0.8),
    (r"(?i)os\.system|subprocess|eval\s*\(", 0.9),
    (r"(?i)rm\s+-rf|del\s+/[sf]|format\s+[cd]:", 0.95),
    (r"(?i)curl\s+.*\|\s*(sh|bash)", 0.95),
    # O'zbek tilida
    (r"(?i)barcha\s+(fayllar|ma'lumotlar)ni\s+o'chir", 0.9),
    (r"(?i)tizimni\s+(o'chir|qayta\s+yukla|to'xtat)", 0.85),
]

# Data exfiltration patternlari
_EXFIL_PATTERNS: list[tuple[str, float]] = [
    (r"(?i)send\s+(all|my)?\s*(data|files?|secrets?|env)\s+to", 0.9),
    (r"(?i)upload\s+(to|at)\s+https?://", 0.75),
    (r"(?i)(show|print|display)\s+(all\s+)?(env|environment|variables?|secrets?)", 0.85),
    (r"(?i)\.env\s+(\w+\s+)*(ko'rsat|o'qi|yubor|show|read|send)", 0.9),
]

# Social engineering patternlari
_SOCIAL_PATTERNS: list[tuple[str, float]] = [
    (r"(?i)i\s+am\s+(the\s+)?(owner|admin|developer|boss)", 0.7),
    (r"(?i)trust\s+me|ishon\s+menga", 0.6),
    (r"(?i)this\s+is\s+(urgent|emergency|critical)", 0.5),
    (r"(?i)men\s+(ega|admin|boss)man", 0.7),
]

_ALL_PATTERNS: list[tuple[InjectionType, str, float]] = [
    *((InjectionType.PROMPT_INJECTION, p, c) for p, c in _PROMPT_INJECTION_PATTERNS),
    *((InjectionType.PRIVILEGE_ESCALATION, p, c) for p, c in _PRIVILEGE_PATTERNS),
    *((InjectionType.COMMAND_INJECTION, p, c) for p, c in _COMMAND_PATTERNS),
    *((InjectionType.DATA_EXFILTRATION, p, c) for p, c in _EXFIL_PATTERNS),
    *((InjectionType.SOCIAL_ENGINEERING, p, c) for p, c in _SOCIAL_PATTERNS),
]

# Kompilyatsiya qilingan patternlar (bir marta)
_COMPILED_PATTERNS: list[tuple[InjectionType, re.Pattern[str], float]] = [
    (itype, re.compile(pattern), confidence) for itype, pattern, confidence in _ALL_PATTERNS
]


def scan_text(text: str, *, threshold: float = 0.5) -> ScanResult:
    """Matnni injection patternlari uchun skanerlash.

    Args:
        text: Tekshiriladigan matn (UNTRUSTED)
        threshold: Bloklash chegarasi (0.0-1.0). Default: 0.5

    Returns:
        ScanResult — xavfsizmi va topilgan patternlar
    """
    if not text or not text.strip():
        return ScanResult(is_safe=True)

    matches: list[InjectionMatch] = []
    max_confidence = 0.0

    for itype, compiled, confidence in _COMPILED_PATTERNS:
        for m in compiled.finditer(text):
            match = InjectionMatch(
                injection_type=itype,
                pattern=compiled.pattern,
                matched_text=m.group()[:100],  # Truncate
                confidence=confidence,
            )
            matches.append(match)
            max_confidence = max(max_confidence, confidence)

    is_safe = max_confidence < threshold

    if not is_safe:
        log.warning(
            "injection.detected",
            match_count=len(matches),
            max_confidence=max_confidence,
            types=[m.injection_type.value for m in matches[:5]],
        )

    return ScanResult(
        is_safe=is_safe,
        matches=tuple(matches),
        score=max_confidence,
    )


def is_safe(text: str) -> bool:
    """Oddiy tekshirish — matn xavfsizmi.

    Args:
        text: Tekshiriladigan matn

    Returns:
        True agar xavfsiz bo'lsa
    """
    return scan_text(text).is_safe
