"""Tool chaqiruvlari — har bir chaqiruv izsiz qolmaydi (V-34)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from zet.domain.enums import PermissionLevel, TrustLevel


class ToolCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta tool chaqiruvining to'liq yozuvi.

    `output_trust_level` — A-05 ning yuragi: shu yerdan boshlab kontent
    ishonchsiz deb belgilanadi va planner promptiga to'g'ridan kira olmaydi.
    """

    __tablename__ = "tool_call"
    __table_args__ = (Index("ix_tool_call_run_created", "run_id", "created_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("step.id", ondelete="SET NULL"), default=None, index=True
    )

    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    permission_level: Mapped[PermissionLevel] = mapped_column()
    output_trust_level: Mapped[TrustLevel] = mapped_column(default=TrustLevel.SYSTEM)

    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(default=None)

    ok: Mapped[bool] = mapped_column(default=False)
    dry_run: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
