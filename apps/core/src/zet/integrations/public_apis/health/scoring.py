"""Provayder sog'ligi — jarayon-xotirasidagi hisoblagichlar (Bo'lim 13).

ATAYLAB oddiy: EWMA/decay yo'q, faqat umr bo'yi hisob (Bo'lim 24 —
"don't overengineer" — MVP ko'lamida bu yetarli, kelajakda kerak
bo'lsa `TTLCache`ga o'xshab oyna qo'shish mumkin).

`total_calls == 0` bo'lganda `success_rate`/`health_score` — `None`
(0.0 EMAS): "hali tekshirilmagan" bilan "har doim muvaffaqiyatsiz"
o'rtasida FARQ bor — `discovery/ranker.py` buni neytral (0.5) deb
o'qiydi, jazolamaydi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class _ProviderStats:
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    rate_limited: int = 0
    latency_sum_ms: float = 0.0
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_checked: datetime | None = None


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Bitta provayderning HOZIRGI sog'lik holati — faqat o'qish uchun."""

    provider: str
    total_calls: int
    successes: int
    failures: int
    timeouts: int
    rate_limited: int
    avg_latency_ms: float
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_checked: datetime | None

    @property
    def success_rate(self) -> float | None:
        if self.total_calls == 0:
            return None
        return self.successes / self.total_calls


class ProviderHealthTracker:
    """Har bir provayder uchun muvaffaqiyat/kechikish hisoblagichlari."""

    def __init__(self) -> None:
        self._stats: dict[str, _ProviderStats] = {}

    def _get_or_create(self, provider: str) -> _ProviderStats:
        stats = self._stats.get(provider)
        if stats is None:
            stats = _ProviderStats()
            self._stats[provider] = stats
        return stats

    def record_success(self, provider: str, *, latency_ms: float, now: datetime) -> None:
        stats = self._get_or_create(provider)
        stats.total_calls += 1
        stats.successes += 1
        stats.latency_sum_ms += latency_ms
        stats.last_success_at = now
        stats.last_checked = now

    def record_failure(
        self,
        provider: str,
        *,
        latency_ms: float,
        now: datetime,
        rate_limited: bool = False,
        timeout: bool = False,
    ) -> None:
        stats = self._get_or_create(provider)
        stats.total_calls += 1
        stats.failures += 1
        stats.latency_sum_ms += latency_ms
        stats.last_failure_at = now
        stats.last_checked = now
        if rate_limited:
            stats.rate_limited += 1
        if timeout:
            stats.timeouts += 1

    def snapshot(self, provider: str) -> HealthSnapshot | None:
        stats = self._stats.get(provider)
        if stats is None:
            return None
        avg_latency = stats.latency_sum_ms / stats.total_calls if stats.total_calls else 0.0
        return HealthSnapshot(
            provider=provider,
            total_calls=stats.total_calls,
            successes=stats.successes,
            failures=stats.failures,
            timeouts=stats.timeouts,
            rate_limited=stats.rate_limited,
            avg_latency_ms=round(avg_latency, 1),
            last_success_at=stats.last_success_at,
            last_failure_at=stats.last_failure_at,
            last_checked=stats.last_checked,
        )

    def health_score(self, provider: str) -> float | None:
        """0..1 muvaffaqiyat nisbati, yoki `None` — hali chaqirilmagan."""
        snap = self.snapshot(provider)
        if snap is None:
            return None
        return snap.success_rate

    def all_snapshots(self) -> list[HealthSnapshot]:
        return [s for s in (self.snapshot(p) for p in self._stats) if s is not None]


__all__ = ["HealthSnapshot", "ProviderHealthTracker"]
