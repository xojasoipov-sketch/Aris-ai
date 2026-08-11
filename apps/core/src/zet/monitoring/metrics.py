"""Metrics Collector — tizim metrikalari (Bo'lim 10).

Oddiy in-memory metrikalar yig'uvchi.
Produksiyada Prometheus yoki boshqa metrika tizimiga almashtiriladi.

Metrikalar:
    - counter: monoton o'suvchi hisoblagich
    - gauge: o'zgaruvchan qiymat
    - histogram: vaqt taqsimoti (oddiy)

Bog'liq qarorlar:
    Bo'lim 10 — monitoring
    ADR-0006 — budjet kuzatish
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class MetricType(StrEnum):
    """Metrika turi."""

    COUNTER = "counter"
    """Monoton o'suvchi (masalan: jami so'rovlar soni)."""

    GAUGE = "gauge"
    """O'zgaruvchan qiymat (masalan: joriy foydalanuvchilar)."""


class MetricSnapshot(BaseModel, frozen=True):
    """Metrika surati — joriy holat."""

    name: str
    """Metrika nomi."""

    metric_type: MetricType
    """Metrika turi."""

    value: float
    """Joriy qiymat."""

    labels: dict[str, str] = Field(default_factory=dict)
    """Teglar (masalan: agent='research', tier='t1_free')."""

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Oxirgi yangilangan vaqt."""


class MetricsCollector:
    """Metrikalar yig'uvchi (in-memory).

    Sodda counter va gauge lar bilan ishlaydi.
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._updated: dict[str, datetime] = {}

    def increment(self, name: str, value: float = 1.0) -> float:
        """Counter ni oshirish.

        Args:
            name: Counter nomi
            value: Oshirish qiymati (default: 1)

        Returns:
            Yangi qiymat
        """
        current = self._counters.get(name, 0.0)
        new_val = current + value
        self._counters[name] = new_val
        self._updated[name] = datetime.now(UTC)
        return new_val

    def set_gauge(self, name: str, value: float) -> None:
        """Gauge qiymatini o'rnatish.

        Args:
            name: Gauge nomi
            value: Yangi qiymat
        """
        self._gauges[name] = value
        self._updated[name] = datetime.now(UTC)

    def get_counter(self, name: str) -> float:
        """Counter qiymatini olish."""
        return self._counters.get(name, 0.0)

    def get_gauge(self, name: str) -> float:
        """Gauge qiymatini olish."""
        return self._gauges.get(name, 0.0)

    def snapshot(self, name: str) -> MetricSnapshot | None:
        """Bitta metrikaning surati.

        Args:
            name: Metrika nomi

        Returns:
            MetricSnapshot yoki None
        """
        if name in self._counters:
            return MetricSnapshot(
                name=name,
                metric_type=MetricType.COUNTER,
                value=self._counters[name],
                updated_at=self._updated.get(name, datetime.now(UTC)),
            )
        if name in self._gauges:
            return MetricSnapshot(
                name=name,
                metric_type=MetricType.GAUGE,
                value=self._gauges[name],
                updated_at=self._updated.get(name, datetime.now(UTC)),
            )
        return None

    def all_snapshots(self) -> list[MetricSnapshot]:
        """Barcha metrikalar surati."""
        results: list[MetricSnapshot] = []
        for name, value in self._counters.items():
            results.append(
                MetricSnapshot(
                    name=name,
                    metric_type=MetricType.COUNTER,
                    value=value,
                    updated_at=self._updated.get(name, datetime.now(UTC)),
                )
            )
        for name, value in self._gauges.items():
            results.append(
                MetricSnapshot(
                    name=name,
                    metric_type=MetricType.GAUGE,
                    value=value,
                    updated_at=self._updated.get(name, datetime.now(UTC)),
                )
            )
        return results

    def reset(self) -> None:
        """Barcha metrikalarni tozalash (test uchun)."""
        self._counters.clear()
        self._gauges.clear()
        self._updated.clear()

    @property
    def stats(self) -> dict[str, int]:
        """Metrikalar soni."""
        return {
            "counters": len(self._counters),
            "gauges": len(self._gauges),
            "total": len(self._counters) + len(self._gauges),
        }
