"""Z1.13 — Observability testlari.

NEGA `CostTracker` testlari yo'q. Ilgari `zet.observability.cost` da
in-memory `CostTracker` bor edi, lekin hech qanday produksiya kodi
uni ishlatmasdi — haqiqiy sarf/budjet yo'li
`zet.llm.budget.BudgetGuard` (`zet.llm.router` va
`zet.llm.routed_provider` orqali) — REPLACEMENT: **tests/test_router_verified.py**,
**tests/test_routed_provider.py** BudgetGuard'ni qamrab oladi.

Tekshiriladi:
    - structlog konfiguratsiyasi (JSON va console)
    - trace_id generatsiya va bind/unbind
    - trace_context context manager
"""

from __future__ import annotations

import logging

import structlog

from zet.observability.logging import configure_logging
from zet.observability.trace import (
    bind_trace,
    get_current_trace_id,
    new_trace_id,
    trace_context,
    unbind_trace,
)

# ── Logging ────────────────────────────────────────────────────────


class TestConfigureLogging:
    def test_console_mode(self) -> None:
        """Console renderer sozlanadi."""
        configure_logging(json_output=False, log_level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 1

    def test_json_mode(self) -> None:
        """JSON renderer sozlanadi."""
        configure_logging(json_output=True, log_level="WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_noisy_loggers_suppressed(self) -> None:
        """Shovqinli loggerlar WARNING darajasiga tushirilgan."""
        configure_logging()
        assert logging.getLogger("httpx").level >= logging.WARNING
        assert logging.getLogger("httpcore").level >= logging.WARNING

    def test_reconfigure_clears_handlers(self) -> None:
        """Qayta sozlashda eski handlerlar tozalanadi."""
        configure_logging()
        configure_logging()
        root = logging.getLogger()
        assert len(root.handlers) == 1


# ── Trace ──────────────────────────────────────────────────────────


class TestTrace:
    def setup_method(self) -> None:
        """Har bir testdan oldin trace tozalash."""
        structlog.contextvars.clear_contextvars()

    def test_new_trace_id_format(self) -> None:
        """trace_id UUID4 hex formatida (32 belgi)."""
        tid = new_trace_id()
        assert len(tid) == 32
        assert tid.isalnum()

    def test_new_trace_ids_unique(self) -> None:
        """Har bir trace_id noyob."""
        ids = {new_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_bind_and_get(self) -> None:
        """bind_trace → get_current_trace_id."""
        tid = bind_trace("test-123")
        assert tid == "test-123"
        assert get_current_trace_id() == "test-123"
        unbind_trace()

    def test_bind_generates_id(self) -> None:
        """trace_id berilmasa avtomatik generatsiya."""
        tid = bind_trace()
        assert len(tid) == 32
        assert get_current_trace_id() == tid
        unbind_trace()

    def test_unbind_clears(self) -> None:
        """unbind_trace trace_id ni tozalaydi."""
        bind_trace("abc")
        unbind_trace()
        assert get_current_trace_id() is None

    def test_context_manager(self) -> None:
        """trace_context: avtomatik bind va tozalash."""
        with trace_context("ctx-test") as tid:
            assert tid == "ctx-test"
            assert get_current_trace_id() == "ctx-test"
        assert get_current_trace_id() is None

    def test_context_manager_auto_id(self) -> None:
        """trace_context: avtomatik ID generatsiya."""
        with trace_context() as tid:
            assert len(tid) == 32
            assert get_current_trace_id() == tid
        assert get_current_trace_id() is None

    def test_context_manager_cleanup_on_error(self) -> None:
        """trace_context: xatolikda ham tozalanadi."""
        try:
            with trace_context("err-test"):
                msg = "test xato"
                raise ValueError(msg)
        except ValueError:
            pass
        assert get_current_trace_id() is None


# ── Cost ───────────────────────────────────────────────────────────
# `CostTracker` olib tashlandi (audit qarori) — haqiqiy budjet
# `zet.llm.budget.BudgetGuard`; `tests/test_router_verified.py` va
# `tests/test_routed_provider.py` uni qamrab oladi.
