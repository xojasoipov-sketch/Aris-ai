"""Ega, suhbat va xabarlar."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from zet.domain.enums import MessageRole, PermissionLevel, TrustLevel


class Owner(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tizim egasi. ZET bir egali (V-02), lekin jadval ko'p qatorni qo'llab-quvvatlaydi.

    Bu — kelajakda ko'p foydalanuvchiga o'tish uchun emas, balki kanal
    identifikatorlarini (Telegram ID, CLI) bitta shaxsga bog'lash uchun.
    """

    __tablename__ = "owner"

    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="owner")
    permission_level: Mapped[PermissionLevel] = mapped_column(default=PermissionLevel.ADMIN)
    is_active: Mapped[bool] = mapped_column(default=True)

    conversations: Mapped[list[Conversation]] = relationship(back_populates="owner")


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta suhbat sessiyasi (CLI, Telegram, API)."""

    __tablename__ = "conversation"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32), default="cli")
    title: Mapped[str | None] = mapped_column(String(256), default=None)

    owner: Mapped[Owner] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Suhbatdagi bitta xabar.

    `trust_level` A-05 uchun kritik: foydalanuvchi forward qilgan tashqi matn
    `UNTRUSTED` bo'lishi kerak, o'zi yozgani `OWNER`.
    """

    __tablename__ = "message"
    __table_args__ = (Index("ix_message_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[MessageRole] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    trust_level: Mapped[TrustLevel] = mapped_column(default=TrustLevel.OWNER)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
