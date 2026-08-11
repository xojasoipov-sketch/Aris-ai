"""Agent DB modeli (Bo'lim 3, A-02).

Agent = ma'lumot. Har bir agent shu jadvalda saqlanadi.
System prompt, tool allowlist, model policy — barchasi DB'da.

Bog'liq qarorlar:
    A-02 — Agent Factory kod generatsiya qilmaydi
    V-11 — lifecycle avtomati (AgentStatus)
    V-31 — permission darajasi
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, TrustLevel


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Agent yozuvi — nima qilishini belgilaydi."""

    __tablename__ = "agent"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    """Unikal agent nomi."""

    description: Mapped[str] = mapped_column(String(500))
    """Qisqa tavsif."""

    division: Mapped[str] = mapped_column(String(64), default="general")
    """Bo'lim."""

    role: Mapped[str] = mapped_column(String(64), default="assistant")
    """Rol."""

    goal: Mapped[str] = mapped_column(Text, default="")
    """Asosiy maqsad."""

    system_prompt: Mapped[str] = mapped_column(Text)
    """Tizim prompti."""

    tool_allowlist: Mapped[list[str]] = mapped_column(default=list)
    """Ruxsat etilgan toollar (JSON array)."""

    model_policy: Mapped[ModelTier] = mapped_column(default=ModelTier.T1_FREE)
    """Default model tier."""

    permission_level: Mapped[PermissionLevel] = mapped_column(
        default=PermissionLevel.READ,
    )
    """Agent ruxsat darajasi."""

    trust_level: Mapped[TrustLevel] = mapped_column(default=TrustLevel.SYSTEM)
    """Agent chiqishi ishonch darajasi."""

    status: Mapped[AgentStatus] = mapped_column(
        default=AgentStatus.DRAFT,
        index=True,
    )
    """Hozirgi holat (V-11)."""

    version: Mapped[int] = mapped_column(Integer, default=1)
    """Agent versiyasi."""

    max_steps: Mapped[int] = mapped_column(Integer, default=10)
    """Bitta run uchun maksimal qadamlar."""

    max_tool_calls: Mapped[int] = mapped_column(Integer, default=20)
    """Bitta run uchun maksimal tool chaqiruvlar."""

    timeout_s: Mapped[int] = mapped_column(Integer, default=120)
    """Bitta run uchun maksimal vaqt."""

    # Metrikalar
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    successful_runs: Mapped[int] = mapped_column(Integer, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_tool_calls_count: Mapped[int] = mapped_column(Integer, default=0)

    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Qo'shimcha sozlamalar (JSON)."""

    __table_args__ = (
        Index("ix_agent_division", "division"),
        Index("ix_agent_status_name", "status", "name"),
        CheckConstraint("version >= 1", name="agent_version_positive"),
        CheckConstraint("max_steps >= 1", name="agent_max_steps_positive"),
        CheckConstraint("max_tool_calls >= 1", name="agent_max_tool_calls_positive"),
        CheckConstraint("timeout_s >= 10", name="agent_timeout_min"),
    )
