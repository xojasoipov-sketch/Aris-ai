"""Async engine, sessiya fabrikasi va ORM darajasidagi himoyalar."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from zet.db.models.security import AuditLog


class AuditLogImmutableError(RuntimeError):
    """`audit_log` yozuvini o'zgartirish yoki o'chirishga urinish.

    Audit jurnali append-only bo'lishi shart (V-33). Postgres'da bu trigger bilan
    ham qo'shimcha himoyalangan; bu yerda ORM darajasidagi birinchi to'siq.
    """


@event.listens_for(Session, "before_flush")
def _block_audit_log_mutation(
    session: Session,
    flush_context: Any,  # noqa: ARG001
    instances: Any,  # noqa: ARG001
) -> None:
    for obj in session.dirty:
        if isinstance(obj, AuditLog) and session.is_modified(obj):
            raise AuditLogImmutableError(
                f"audit_log o'zgartirilmaydi (id={obj.id}) — jurnal append-only"
            )
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            raise AuditLogImmutableError(
                f"audit_log o'chirilmaydi (id={obj.id}) — jurnal append-only"
            )


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Async engine yaratish.

    SQLite (unit testlar) va Postgres (prod) ikkalasini ham qo'llab-quvvatlaydi.
    """
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if not url.startswith("sqlite"):
        kwargs |= {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }
    return create_async_engine(url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Tranzaksiya konteksti: muvaffaqiyatda commit, xatoda rollback."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
