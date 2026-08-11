"""Tool domen modellari.

Tool Registry (Z1.10) va Executor (Z1.11) uchun kontraktlar.
DB `tool_call` jadvali bilan bog'lanadi, lekin undan mustaqil.

Bog'liq qarorlar:
    A-05 — tool natijasi trust level bilan keladi
    V-31 — tool chaqiruvi uchun ruxsat
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from zet.domain.enums import TrustLevel


class ToolResult(BaseModel, frozen=True):
    """Tool bajarilishi natijasi."""

    tool_name: str
    """Bajarilgan tool nomi."""

    success: bool
    """Muvaffaqiyatli bajarildi yoki yo'q."""

    output: Any = None
    """Chiqish qiymati (JSON-serializatsiya qilinadigan)."""

    error: str | None = None
    """Xato xabari (agar success=False)."""

    trust_level: TrustLevel = TrustLevel.SYSTEM
    """Natija ma'lumotining ishonch darajasi (A-05).

    Tashqi manbadan kelgan natija (web, file, OCR) → UNTRUSTED.
    ZET'ning o'z tool'lari (time.now, math) → SYSTEM.
    """

    latency_ms: int = 0
    """Bajarilish vaqti (millisekundlarda)."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Qo'shimcha ma'lumot (debug/audit)."""


class Verification(BaseModel, frozen=True):
    """Qadam/run natijasini tekshirish holati (V-35)."""

    ok: bool
    """Natija kutilgan natijaga mos keldi."""

    reason: str = ""
    """Tekshirish natijasi izohi."""

    auto: bool = True
    """Avtomatik tekshirildi (LLM) yoki ega tomonidan."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    """LLM tekshiruvchisining ishonch darajasi."""
