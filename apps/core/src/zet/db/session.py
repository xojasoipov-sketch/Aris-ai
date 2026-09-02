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


@event.listens_for(Session, "after_begin")
def _enable_sqlite_foreign_keys(
    session: Session,  # noqa: ARG001
    transaction: Any,  # noqa: ARG001
    connection: Any,
) -> None:
    """SQLite'da FK majburlashni yoqadi.

    SQLite tashqi kalitlarni SUKUT BO'YICHA e'tiborsiz qoldiradi —
    `ondelete="CASCADE"` va `ondelete="SET NULL"` shunchaki ishlamaydi.
    Postgres esa ularni majburlaydi. Ya'ni pragmasiz testlar prod'dan
    BOSHQACHA xatti-harakatni tekshirardi va FK bilan bog'liq xatoni
    umuman tuta olmasdi.

    Jonli misol: `task.project_id` uchun `SET NULL` e'lon qilingan,
    lekin testda loyiha o'chirilgach vazifa eski `project_id`ni saqlab
    qolaverdi — prod'da esa u `NULL` bo'lardi.

    NEGA `connect` HODISASI EMAS. Odatdagi yo'l — engine'ning `connect`
    hodisasida pragma yuborish. `aiosqlite` bilan u ISHLAMAYDI:
    ulanish obyekti async o'ram va sinxron `cursor.execute` greenlet
    konteksti yo'qligi sababli `MissingGreenlet` bilan yiqiladi.
    `after_begin` esa async oqim ichida chaqiriladi.
    """
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


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
