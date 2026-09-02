"""Trace context — har bir run uchun noyob trace_id (Z1.13).

`structlog.contextvars` orqali har bir log avtomatik trace_id ni oladi.
FastAPI middleware va CLI da `bind_trace()` chaqiriladi.

Bog'liq qarorlar:
    V-34 — audit trail
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import structlog


def new_trace_id() -> str:
    """Yangi trace_id generatsiya qiladi (UUID4 hex, 32 belgi)."""
    return uuid.uuid4().hex


def bind_trace(trace_id: str | None = None) -> str:
    """Joriy kontekstga trace_id bog'laydi.

    Args:
        trace_id: mavjud trace_id (None bo'lsa yangi yaratiladi)

    Returns:
        bog'langan trace_id
    """
    tid = trace_id or new_trace_id()
    structlog.contextvars.bind_contextvars(trace_id=tid)
    return tid


def unbind_trace() -> None:
    """trace_id ni kontekstdan olib tashlaydi."""
    structlog.contextvars.unbind_contextvars("trace_id")


def get_current_trace_id() -> str | None:
    """Joriy kontekstdagi trace_id ni qaytaradi."""
    ctx = structlog.contextvars.get_contextvars()
    result = ctx.get("trace_id")
    if isinstance(result, str):
        return result
    return None


@contextmanager
def trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Context manager — trace_id avtomatik bog'lanadi va chiqishda tozalanadi.

    Usage::

        with trace_context() as tid:
            log.info("ishlayapti", trace_id=tid)
        # trace_id avtomatik tozalandi
    """
    tid = bind_trace(trace_id)
    try:
        yield tid
    finally:
        unbind_trace()
