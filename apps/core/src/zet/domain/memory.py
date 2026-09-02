"""Xotira domen modellari (Bo'lim 2).

7 qatlamli xotira tizimi:
    1. short_term  — joriy run konteksti (TTL: 1 soat)
    2. conversation — suhbat tarixi (TTL: 7 kun)
    3. task        — vazifa konteksti (TTL: 30 kun)
    4. project     — loyiha bilimlari (TTL: yo'q)
    5. business    — biznes bilimlari (TTL: yo'q)
    6. personal    — shaxsiy ma'lumotlar (TTL: yo'q)
    7. knowledge   — umumiy bilim bazasi (TTL: yo'q)

Bog'liq qarorlar:
    V-14 — ruxsatga bog'liq ko'rinish
    V-15 — xotira versiyalash
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemoryLayer(StrEnum):
    """Xotira qatlami."""

    SHORT_TERM = "short_term"
    CONVERSATION = "conversation"
    TASK = "task"
    PROJECT = "project"
    BUSINESS = "business"
    PERSONAL = "personal"
    KNOWLEDGE = "knowledge"


# TTL sekundlarda (None = cheksiz)
LAYER_TTL: dict[MemoryLayer, int | None] = {
    MemoryLayer.SHORT_TERM: 3600,  # 1 soat
    MemoryLayer.CONVERSATION: 604_800,  # 7 kun
    MemoryLayer.TASK: 2_592_000,  # 30 kun
    MemoryLayer.PROJECT: None,
    MemoryLayer.BUSINESS: None,
    MemoryLayer.PERSONAL: None,
    MemoryLayer.KNOWLEDGE: None,
}


class MemoryEntry(BaseModel):
    """Bitta xotira yozuvi.

    Immutable (frozen) — versiyalash alohida bo'ladi.
    """

    model_config = {"frozen": True}

    id: str | None = None
    """DB ID (yaratilgandan keyin)."""

    layer: MemoryLayer
    """Qaysi qatlamda saqlanadi."""

    content: str
    """Asosiy matn."""

    summary: str | None = None
    """Qisqartma (summarization uchun)."""

    tags: list[str] = Field(default_factory=list)
    """Teglar — qidiruv va filtrlash uchun."""

    source: str | None = None
    """Manba (run_id, conversation_id, fayl nomi va h.k.)."""

    embedding: list[float] | None = None
    """Vektor tasviri (pgvector uchun)."""

    version: int = 1
    """Versiya raqami (V-15)."""

    created_at: datetime | None = None
    expires_at: datetime | None = None

    trust_level: str = "owner"
    """Manba ishonchliligi (V-14)."""


class MemoryQuery(BaseModel):
    """Xotira qidiruv so'rovi."""

    model_config = {"frozen": True}

    text: str
    """Qidiruv matni."""

    layers: list[MemoryLayer] | None = None
    """Faqat shu qatlamlardan qidirish (None = barchasi)."""

    tags: list[str] | None = None
    """Teglar bo'yicha filtrlash."""

    limit: int = Field(default=10, ge=1, le=100)
    """Maksimal natijalar soni."""

    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    """Minimal o'xshashlik ball."""

    include_expired: bool = False
    """Muddati o'tgan yozuvlarni ham qo'shish."""


class MemorySearchResult(BaseModel):
    """Qidiruv natijasi."""

    model_config = {"frozen": True}

    entry: MemoryEntry
    similarity: float = Field(ge=0.0, le=1.0)
    """O'xshashlik balli (0-1)."""

    rank: int = Field(ge=1)
    """Natija tartibi."""
