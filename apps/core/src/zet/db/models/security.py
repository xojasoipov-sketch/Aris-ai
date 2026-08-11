"""Tasdiq, audit va emergency stop (V-32, V-33).

`AuditLog` — append-only: ORM darajasida va Postgres trigger'i bilan ikki qavat himoya.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from zet.domain.enums import ApprovalStatus, PermissionLevel


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Yuqori xavfli amal uchun egadan so'raladigan tasdiq.

    TTL tugasa `EXPIRED` bo'ladi va run bekor qilinadi — sukut bilan ruxsat
    berilmaydi (fail-closed).
    """

    __tablename__ = "approval"
    __table_args__ = (Index("ix_approval_status_expires", "status", "expires_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("step.id", ondelete="SET NULL"), default=None
    )

    reason: Mapped[str] = mapped_column(Text)
    requested_permission: Mapped[PermissionLevel] = mapped_column()
    tool_name: Mapped[str | None] = mapped_column(String(64), default=None)
    preview: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Nima bajarilishini egaga ko'rsatish uchun (buyruq, fayl yo'li, summa...)."""

    status: Mapped[ApprovalStatus] = mapped_column(default=ApprovalStatus.PENDING, index=True)
    expires_at: Mapped[datetime] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by: Mapped[str | None] = mapped_column(String(128), default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, default=None)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) >= self.expires_at


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """O'zgartirib va o'chirib bo'lmaydigan hodisalar jurnali.

    `TimestampMixin` qasddan ishlatilmagan: `updated_at` bo'lishi mumkin emas.
    """

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_ts_action", "ts", "action"),)

    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str | None] = mapped_column(String(256), default=None)
    permission_level: Mapped[PermissionLevel | None] = mapped_column(default=None)
    run_id: Mapped[uuid.UUID | None] = mapped_column(default=None, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class KillSwitch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Global emergency stop (V-33).

    Bazada saqlanadi — protsess qayta ishga tushsa ham kuchda qoladi.
    Jadvalda faqat bitta qator bo'ladi (`singleton` = True).
    """

    __tablename__ = "kill_switch"

    singleton: Mapped[bool] = mapped_column(Boolean, unique=True, default=True)
    engaged: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    engaged_at: Mapped[datetime | None] = mapped_column(default=None)
    engaged_by: Mapped[str | None] = mapped_column(String(128), default=None)
