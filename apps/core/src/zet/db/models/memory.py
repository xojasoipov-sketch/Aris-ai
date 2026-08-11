"""Xotira DB modeli (Bo'lim 2).

`memory_entries` jadvali — 7 qatlamli xotira, vektor embedding'lar bilan.

pgvector `Vector` tipi Postgres'da, SQLite'da oddiy JSON sifatida saqlanadi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, JSONType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class MemoryEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Xotira yozuvi — asosiy jadval."""

    __tablename__ = "memory_entries"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"),
        index=True,
    )

    layer: Mapped[str] = mapped_column(String(32), index=True)
    """Qatlam nomi: short_term, conversation, task, ..."""

    content: Mapped[str] = mapped_column(Text)
    """Asosiy matn."""

    summary: Mapped[str | None] = mapped_column(Text, default=None)
    """Qisqartma."""

    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    """Teglar."""

    source: Mapped[str | None] = mapped_column(String(500), default=None)
    """Manba (run_id, conversation_id, fayl nomi va h.k.)."""

    embedding: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    """Vektor tasviri (JSON formatda; pgvector uchun migratsiyada Vector tipiga o'tkaziladi)."""

    version: Mapped[int] = mapped_column(default=1)
    """Versiya raqami."""

    trust_level: Mapped[str] = mapped_column(String(32), default="owner")
    """Manba ishonchliligi."""

    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None, index=True)
    """Muddati tugash vaqti (None = cheksiz)."""

    is_deleted: Mapped[bool] = mapped_column(default=False)
    """Soft delete."""

    __table_args__ = (
        Index("ix_memory_layer_owner", "layer", "owner_id"),
        # Partial index (postgresql_where) alohida migratsiyada qo'shiladi
    )
