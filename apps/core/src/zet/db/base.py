"""SQLAlchemy deklarativ poydevor.

Ikkita maxsus tip ishlatiladi:

`UTCDateTime`
    Har qanday dialektda **timezone-aware UTC** kafolatlaydi. SQLite tz saqlamaydi,
    Postgres esa saqlaydi — bu tip farqni yo'qotadi. Naive datetime yozishga urinish
    xato beradi, chunki audit va budjet hisobida vaqt noaniqligi qabul qilinmaydi.

`enum_column`
    Enum'ni VARCHAR + CHECK sifatida saqlaydi va o'qishda enum a'zosiga qaytaradi.
    Native PG enum ishlatilmaydi: yangi qiymat qo'shish `ALTER TYPE` talab qilardi.

Tiplar Postgres va SQLite ikkalasida ham ishlaydi: unit testlar SQLite in-memory'da,
integration testlar va prod Postgres'da.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Dialect, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator, Uuid

from zet.domain.enums import (
    ApprovalStatus,
    MessageRole,
    ModelTier,
    PermissionLevel,
    RunStatus,
    RunTrigger,
    StepStatus,
    TaskClass,
    TrustLevel,
)

# Postgres'da JSONB, SQLite'da oddiy JSON
JSONType = JSON().with_variant(JSONB(), "postgresql")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Har doim timezone-aware UTC (ruff DTZ qoidasi shuni talab qiladi)."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Dialektdan qat'i nazar timezone-aware UTC qaytaradigan vaqt tipi."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime saqlab bo'lmaydi — zet.db.base.utcnow() ishlating")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:  # noqa: ARG002
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def enum_column(enum_cls: type[StrEnum]) -> SAEnum:
    """StrEnum uchun VARCHAR + CHECK ustuni.

    `values_callable` bo'lmasa SQLAlchemy a'zo **nomini** (`ADMIN`) saqlaydi;
    bizga qiymat (`admin`) kerak — u API va JSON'da ham ishlatiladi.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
        length=32,
        name=f"{enum_cls.__name__.lower()}_enum",
    )


class Base(DeclarativeBase):
    """Barcha ZET modellarining bazasi."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: JSONType,
        list[str]: JSONType,
        uuid.UUID: Uuid(as_uuid=True),
        datetime: UTCDateTime(),
        # Domen enum'lari — `Mapped[PermissionLevel]` avtomatik shu tipga tushadi
        ApprovalStatus: enum_column(ApprovalStatus),
        MessageRole: enum_column(MessageRole),
        ModelTier: enum_column(ModelTier),
        PermissionLevel: enum_column(PermissionLevel),
        RunStatus: enum_column(RunStatus),
        RunTrigger: enum_column(RunTrigger),
        StepStatus: enum_column(StepStatus),
        TaskClass: enum_column(TaskClass),
        TrustLevel: enum_column(TrustLevel),
    }

    def __repr__(self) -> str:
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class UUIDPrimaryKeyMixin:
    """UUIDv4 birlamchi kalit."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """`created_at` / `updated_at` — har doim timezone-aware UTC."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
    )
