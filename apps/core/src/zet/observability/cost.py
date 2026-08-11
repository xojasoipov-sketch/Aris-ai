"""Cost reporting — sarfni hisoblash va hisobot (Z1.13).

In-memory hisoblagich — Executor va LLM chaqiruvlaridan
qo'llaniladi. DB bilan sinxronlash Orchestrator vazifasi.

Bog'liq qarorlar:
    A-07 — avtomatlashtirish tormozlari
    ADR-0006 §4 — budjet qo'riqchisi
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from zet.domain.enums import ModelTier

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CostEntry:
    """Bitta sarfning yozuvi."""

    tier: ModelTier
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    timestamp: datetime
    trace_id: str | None = None
    run_id: str | None = None
    tool_name: str | None = None


@dataclass
class CostTracker:
    """In-memory sarfni kuzatuvchi.

    Har bir run uchun alohida instance yaratiladi.
    DB'ga yozish Orchestrator'ning vazifasi.
    """

    budget_usd: float = 0.10
    """Run uchun maksimal budjet."""

    _entries: list[CostEntry] = field(default_factory=list)
    _total_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        """Jami sarflangan summa."""
        return self._total_usd

    @property
    def remaining_usd(self) -> float:
        """Qolgan budjet."""
        return max(0.0, self.budget_usd - self._total_usd)

    @property
    def entries(self) -> list[CostEntry]:
        """Barcha sarflar (faqat o'qish)."""
        return list(self._entries)

    @property
    def entry_count(self) -> int:
        """Sarflar soni."""
        return len(self._entries)

    def record(
        self,
        *,
        tier: ModelTier,
        model: str,
        input_tokens: int,
        output_tokens: int,
        usd: float,
        trace_id: str | None = None,
        run_id: str | None = None,
        tool_name: str | None = None,
        now: datetime | None = None,
    ) -> CostEntry:
        """Sarfni qayd qiladi.

        Returns:
            yaratilgan CostEntry
        """
        entry = CostEntry(
            tier=tier,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usd=usd,
            timestamp=now or datetime.now(tz=UTC),
            trace_id=trace_id,
            run_id=run_id,
            tool_name=tool_name,
        )
        self._entries.append(entry)
        self._total_usd += usd

        log.info(
            "cost.recorded",
            tier=tier.value,
            model=model,
            usd=f"{usd:.6f}",
            total=f"{self._total_usd:.6f}",
            remaining=f"{self.remaining_usd:.6f}",
        )
        return entry

    def is_over_budget(self) -> bool:
        """Budjet tugadimi."""
        return self._total_usd >= self.budget_usd

    def summary(self) -> dict[str, object]:
        """Qisqa hisobot — API va CLI uchun."""
        by_tier: dict[str, float] = {}
        by_model: dict[str, float] = {}
        total_input = 0
        total_output = 0

        for e in self._entries:
            by_tier[e.tier.value] = by_tier.get(e.tier.value, 0.0) + e.usd
            by_model[e.model] = by_model.get(e.model, 0.0) + e.usd
            total_input += e.input_tokens
            total_output += e.output_tokens

        return {
            "total_usd": round(self._total_usd, 6),
            "budget_usd": self.budget_usd,
            "remaining_usd": round(self.remaining_usd, 6),
            "entries": self.entry_count,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "by_tier": {k: round(v, 6) for k, v in by_tier.items()},
            "by_model": {k: round(v, 6) for k, v in by_model.items()},
        }

    def reset(self) -> None:
        """Hisoblagichni tozalash (test uchun)."""
        self._entries.clear()
        self._total_usd = 0.0
