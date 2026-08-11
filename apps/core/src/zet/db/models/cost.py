"""Xarajat va kvota hisobi (A-04, ADR-0006).

Ikkita alohida daftar kerak, chunki tier'lar ikki xil o'lchovda cheklanadi:
    - T2/T3 — **pulda** (USD)
    - T0/T1 — **so'rovlar sonida** (free tier RPM/RPD kvotasi)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from zet.domain.enums import ModelTier, TaskClass


class CostLedger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Har bir LLM chaqiruvining token/xarajat/natija yozuvi.

    `verified_ok` — A-04 ning metrika qaytish halqasi: Model Router shu ustun
    asosida qaysi tier qaysi vazifada haqiqatan ishlayotganini o'lchaydi.
    """

    __tablename__ = "cost_ledger"
    __table_args__ = (
        CheckConstraint("usd >= 0", name="usd_non_negative"),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"),
        Index("ix_cost_ledger_created_tier", "created_at", "tier"),
        Index("ix_cost_ledger_taskclass_tier", "task_class", "tier"),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(default=None, index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64))
    tier: Mapped[ModelTier] = mapped_column(index=True)
    task_class: Mapped[TaskClass] = mapped_column()

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    usd: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    ok: Mapped[bool] = mapped_column(default=True)
    verified_ok: Mapped[bool | None] = mapped_column(default=None)
    is_autonomous: Mapped[bool] = mapped_column(default=False)
    """Avtonom run'lar alohida ulushga ega (ADR-0006 §4)."""

    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class QuotaLedger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Free tier kvota hisobchisi.

    Free tier'lar pulda emas, so'rovlar sonida cheklanadi (RPM/RPD).
    Har bir (provayder, oyna turi, oyna boshlanishi) uchun bitta qator.
    """

    __tablename__ = "quota_ledger"
    __table_args__ = (
        UniqueConstraint("provider", "window", "window_start", name="unique_quota_window"),
        CheckConstraint("used >= 0 AND limit_value > 0", name="quota_sane"),
        Index("ix_quota_provider_window", "provider", "window", "window_start"),
    )

    provider: Mapped[str] = mapped_column(String(32))
    window: Mapped[str] = mapped_column(String(16))
    """`minute` yoki `day`."""

    window_start: Mapped[datetime] = mapped_column()
    used: Mapped[int] = mapped_column(Integer, default=0)
    limit_value: Mapped[int] = mapped_column(Integer)
    resets_at: Mapped[datetime] = mapped_column()

    @property
    def remaining(self) -> int:
        return max(0, self.limit_value - self.used)

    @property
    def is_exhausted(self) -> bool:
        return self.used >= self.limit_value
