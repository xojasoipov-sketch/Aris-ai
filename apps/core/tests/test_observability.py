"""Z1.13 — Observability testlari.

Tekshiriladi:
    - structlog konfiguratsiyasi (JSON va console)
    - trace_id generatsiya va bind/unbind
    - trace_context context manager
    - CostTracker: record, summary, budget, reset
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import structlog

from zet.domain.enums import ModelTier
from zet.observability.cost import CostTracker
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


class TestCostTracker:
    def test_initial_state(self) -> None:
        """Boshlang'ich holat."""
        ct = CostTracker(budget_usd=1.0)
        assert ct.total_usd == 0.0
        assert ct.remaining_usd == 1.0
        assert ct.entry_count == 0
        assert not ct.is_over_budget()

    def test_record_entry(self) -> None:
        """Sarfni qayd qilish."""
        ct = CostTracker(budget_usd=1.0)
        entry = ct.record(
            tier=ModelTier.T1_FREE,
            model="gemini-flash",
            input_tokens=100,
            output_tokens=50,
            usd=0.0,
        )
        assert entry.model == "gemini-flash"
        assert ct.entry_count == 1

    def test_budget_tracking(self) -> None:
        """Budjet kuzatuvi to'g'ri ishlaydi."""
        ct = CostTracker(budget_usd=0.10)
        ct.record(
            tier=ModelTier.T2_CHEAP,
            model="haiku",
            input_tokens=1000,
            output_tokens=500,
            usd=0.03,
        )
        assert ct.total_usd == 0.03
        assert abs(ct.remaining_usd - 0.07) < 1e-9

    def test_over_budget(self) -> None:
        """Budjet tugashi."""
        ct = CostTracker(budget_usd=0.05)
        ct.record(
            tier=ModelTier.T3_STRONG,
            model="sonnet",
            input_tokens=5000,
            output_tokens=2000,
            usd=0.05,
        )
        assert ct.is_over_budget()
        assert ct.remaining_usd == 0.0

    def test_summary(self) -> None:
        """Hisobot to'g'ri."""
        ct = CostTracker(budget_usd=1.0)
        ct.record(
            tier=ModelTier.T1_FREE,
            model="gemini",
            input_tokens=100,
            output_tokens=50,
            usd=0.0,
        )
        ct.record(
            tier=ModelTier.T2_CHEAP,
            model="haiku",
            input_tokens=200,
            output_tokens=100,
            usd=0.01,
        )
        summary = ct.summary()
        assert summary["entries"] == 2
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 150
        assert summary["budget_usd"] == 1.0
        assert "by_tier" in summary
        assert "by_model" in summary

    def test_summary_by_tier(self) -> None:
        """Tier bo'yicha guruhlanadi."""
        ct = CostTracker(budget_usd=1.0)
        ct.record(
            tier=ModelTier.T2_CHEAP,
            model="haiku",
            input_tokens=100,
            output_tokens=50,
            usd=0.01,
        )
        ct.record(
            tier=ModelTier.T2_CHEAP,
            model="haiku",
            input_tokens=100,
            output_tokens=50,
            usd=0.02,
        )
        summary = ct.summary()
        by_tier = summary["by_tier"]
        assert isinstance(by_tier, dict)
        assert by_tier["t2_cheap"] == 0.03

    def test_reset(self) -> None:
        """Reset tozalaydi."""
        ct = CostTracker(budget_usd=1.0)
        ct.record(
            tier=ModelTier.T1_FREE,
            model="test",
            input_tokens=100,
            output_tokens=50,
            usd=0.01,
        )
        ct.reset()
        assert ct.total_usd == 0.0
        assert ct.entry_count == 0

    def test_entry_with_trace_id(self) -> None:
        """CostEntry trace_id saqlaydi."""
        ct = CostTracker()
        entry = ct.record(
            tier=ModelTier.T0_LOCAL,
            model="phi3",
            input_tokens=100,
            output_tokens=50,
            usd=0.0,
            trace_id="abc123",
            run_id="run-1",
            tool_name="test.tool",
        )
        assert entry.trace_id == "abc123"
        assert entry.run_id == "run-1"
        assert entry.tool_name == "test.tool"

    def test_custom_timestamp(self) -> None:
        """Berilgan vaqt ishlatiladi."""
        ct = CostTracker()
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        entry = ct.record(
            tier=ModelTier.T1_FREE,
            model="test",
            input_tokens=10,
            output_tokens=5,
            usd=0.0,
            now=ts,
        )
        assert entry.timestamp == ts

    def test_entries_immutable_copy(self) -> None:
        """entries() nusxa qaytaradi."""
        ct = CostTracker()
        ct.record(
            tier=ModelTier.T1_FREE,
            model="test",
            input_tokens=10,
            output_tokens=5,
            usd=0.0,
        )
        entries = ct.entries
        entries.clear()
        assert ct.entry_count == 1  # Ichki ro'yxat o'zgarmadi
