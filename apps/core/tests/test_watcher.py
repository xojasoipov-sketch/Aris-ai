"""Kuzatuv triggeri (watcher) testlari — agentning 3-xususiyati."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from zet.automation.watcher import (
    MetricRegistry,
    WatchComparison,
    WatcherRegistry,
    WatchRule,
)

NOW = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


def _rule(**kwargs: object) -> WatchRule:
    base: dict[str, object] = {"name": "test", "metric": "m"}
    base.update(kwargs)
    return WatchRule.model_validate(base)


async def _make(value: float | None) -> float | None:
    """Metrika o'lchovchisi uchun tayyor qiymat."""
    return value


class TestShouldFire:
    """Shart mantiqi — har bir taqqoslash turi."""

    def test_first_reading_never_fires(self) -> None:
        """Baza o'rnatiladi, signal berilmaydi — aks holda har restartda soxta signal."""
        for comparison in WatchComparison:
            rule = _rule(comparison=comparison, threshold=0.0, last_value=None)
            assert rule.should_fire(999.0) is False

    def test_changed_fires_on_any_difference(self) -> None:
        rule = _rule(comparison=WatchComparison.CHANGED, last_value=10.0)
        assert rule.should_fire(11.0) is True
        assert rule.should_fire(9.0) is True

    def test_changed_silent_when_equal(self) -> None:
        rule = _rule(comparison=WatchComparison.CHANGED, last_value=10.0)
        assert rule.should_fire(10.0) is False

    def test_above_is_level_triggered(self) -> None:
        """Chegaradan yuqori bo'lgan HAR o'lchovda signal beradi."""
        rule = _rule(comparison=WatchComparison.ABOVE, threshold=5.0, last_value=9.0)
        assert rule.should_fire(9.0) is True

    def test_below_is_level_triggered(self) -> None:
        rule = _rule(comparison=WatchComparison.BELOW, threshold=5.0, last_value=1.0)
        assert rule.should_fire(1.0) is True

    def test_crosses_above_fires_only_on_the_crossing(self) -> None:
        rule = _rule(comparison=WatchComparison.CROSSES_ABOVE, threshold=5.0, last_value=4.0)
        assert rule.should_fire(6.0) is True

    def test_crosses_above_silent_when_already_above(self) -> None:
        """Qirra-triggeri: ikkalasi ham yuqorida bo'lsa — o'tish yo'q."""
        rule = _rule(comparison=WatchComparison.CROSSES_ABOVE, threshold=5.0, last_value=6.0)
        assert rule.should_fire(7.0) is False

    def test_crosses_below_fires_only_on_the_crossing(self) -> None:
        rule = _rule(comparison=WatchComparison.CROSSES_BELOW, threshold=5.0, last_value=6.0)
        assert rule.should_fire(4.0) is True

    def test_crosses_below_silent_when_already_below(self) -> None:
        rule = _rule(comparison=WatchComparison.CROSSES_BELOW, threshold=5.0, last_value=4.0)
        assert rule.should_fire(3.0) is False

    def test_delta_pct_fires_above_threshold(self) -> None:
        rule = _rule(comparison=WatchComparison.DELTA_PCT, threshold=20.0, last_value=100.0)
        assert rule.should_fire(125.0) is True

    def test_delta_pct_silent_below_threshold(self) -> None:
        rule = _rule(comparison=WatchComparison.DELTA_PCT, threshold=20.0, last_value=100.0)
        assert rule.should_fire(110.0) is False

    def test_delta_pct_handles_zero_baseline(self) -> None:
        """Noldan siljish — nolga bo'lish xatosi bermaydi."""
        rule = _rule(comparison=WatchComparison.DELTA_PCT, threshold=20.0, last_value=0.0)
        assert rule.should_fire(5.0) is True
        assert rule.should_fire(0.0) is False

    def test_delta_pct_fires_on_drop_too(self) -> None:
        """Yo'nalish muhim emas — mutlaq siljish."""
        rule = _rule(comparison=WatchComparison.DELTA_PCT, threshold=20.0, last_value=100.0)
        assert rule.should_fire(50.0) is True


class TestCooldown:
    """Signal yog'ilishining oldini olish."""

    def test_in_cooldown_right_after_firing(self) -> None:
        rule = _rule(cooldown_s=300, last_fired_at=NOW)
        assert rule.in_cooldown(NOW + timedelta(seconds=60)) is True

    def test_out_of_cooldown_after_window(self) -> None:
        rule = _rule(cooldown_s=300, last_fired_at=NOW)
        assert rule.in_cooldown(NOW + timedelta(seconds=301)) is False

    def test_zero_cooldown_never_blocks(self) -> None:
        rule = _rule(cooldown_s=0, last_fired_at=NOW)
        assert rule.in_cooldown(NOW) is False


class TestIsActive:
    """Faollik va `max_fires` tormozi (A-07)."""

    def test_disabled_is_inactive(self) -> None:
        assert _rule(enabled=False).is_active is False

    def test_exhausted_max_fires_is_inactive(self) -> None:
        assert _rule(max_fires=3, fire_count=3).is_active is False

    def test_unlimited_stays_active(self) -> None:
        assert _rule(max_fires=None, fire_count=999).is_active is True


class TestPolling:
    """`WatcherRegistry.poll()` — o'lchash va hodisa chiqarish."""

    async def test_baseline_poll_emits_nothing(self) -> None:
        registry = WatcherRegistry()
        rule = registry.add(_rule(comparison=WatchComparison.CHANGED))
        metrics = MetricRegistry()
        metrics.register("m", lambda: _make(10.0))

        events = await registry.poll(metrics, now=NOW)

        assert events == []
        assert registry.get(rule.id) is not None
        stored = registry.get(rule.id)
        assert stored is not None
        assert stored.last_value == 10.0

    async def test_second_poll_with_change_emits_event(self) -> None:
        registry = WatcherRegistry()
        rule = registry.add(_rule(comparison=WatchComparison.CHANGED, cooldown_s=0))
        metrics = MetricRegistry()
        values = iter([10.0, 12.0])
        metrics.register("m", lambda: _make(next(values)))

        await registry.poll(metrics, now=NOW)
        events = await registry.poll(metrics, now=NOW + timedelta(minutes=1))

        assert len(events) == 1
        event = events[0]
        assert event.event_type == "watch.m"
        assert event.data["value"] == "12"
        assert event.data["previous"] == "10"
        assert event.data["direction"] == "up"
        assert event.data["watch_rule_id"] == rule.id

    async def test_direction_down_on_drop(self) -> None:
        registry = WatcherRegistry()
        registry.add(_rule(comparison=WatchComparison.CHANGED, cooldown_s=0))
        metrics = MetricRegistry()
        values = iter([10.0, 4.0])
        metrics.register("m", lambda: _make(next(values)))

        await registry.poll(metrics, now=NOW)
        events = await registry.poll(metrics, now=NOW + timedelta(minutes=1))

        assert events[0].data["direction"] == "down"

    async def test_cooldown_suppresses_second_event(self) -> None:
        registry = WatcherRegistry()
        registry.add(_rule(comparison=WatchComparison.CHANGED, cooldown_s=600))
        metrics = MetricRegistry()
        values = iter([10.0, 12.0, 14.0])
        metrics.register("m", lambda: _make(next(values)))

        await registry.poll(metrics, now=NOW)
        first = await registry.poll(metrics, now=NOW + timedelta(minutes=1))
        second = await registry.poll(metrics, now=NOW + timedelta(minutes=2))

        assert len(first) == 1
        assert second == []

    async def test_unavailable_metric_is_skipped_not_crashed(self) -> None:
        """Manba yo'q — watcher jim o'tadi, tizim yiqilmaydi."""
        registry = WatcherRegistry()
        registry.add(_rule(metric="yoq"))

        events = await registry.poll(MetricRegistry(), now=NOW)

        assert events == []

    async def test_failing_probe_is_swallowed(self) -> None:
        """O'lchovchi xato bersa — fail-open."""
        registry = WatcherRegistry()
        registry.add(_rule(comparison=WatchComparison.CHANGED))
        metrics = MetricRegistry()

        async def _boom() -> float | None:
            raise RuntimeError("o'lchab bo'lmadi")

        metrics.register("m", _boom)

        assert await registry.poll(metrics, now=NOW) == []

    async def test_disabled_rule_not_polled(self) -> None:
        registry = WatcherRegistry()
        registry.add(_rule(enabled=False, last_value=1.0, comparison=WatchComparison.CHANGED))
        metrics = MetricRegistry()
        metrics.register("m", lambda: _make(99.0))

        assert await registry.poll(metrics, now=NOW) == []

    async def test_fire_count_increments_and_respects_max(self) -> None:
        registry = WatcherRegistry()
        rule = registry.add(_rule(comparison=WatchComparison.CHANGED, cooldown_s=0, max_fires=1))
        metrics = MetricRegistry()
        values = iter([1.0, 2.0, 3.0])
        metrics.register("m", lambda: _make(next(values)))

        await registry.poll(metrics, now=NOW)
        await registry.poll(metrics, now=NOW + timedelta(minutes=1))
        third = await registry.poll(metrics, now=NOW + timedelta(minutes=2))

        stored = registry.get(rule.id)
        assert stored is not None
        assert stored.fire_count == 1
        assert stored.is_active is False
        assert third == []


class TestRegistryManagement:
    """Registry boshqaruvi."""

    def test_disable_then_enable(self) -> None:
        registry = WatcherRegistry()
        rule = registry.add(_rule())

        assert registry.disable(rule.id) is not None
        disabled = registry.get(rule.id)
        assert disabled is not None and disabled.enabled is False

        assert registry.enable(rule.id) is not None
        enabled = registry.get(rule.id)
        assert enabled is not None and enabled.enabled is True

    def test_remove(self) -> None:
        registry = WatcherRegistry()
        rule = registry.add(_rule())
        assert registry.remove(rule.id) is True
        assert registry.get(rule.id) is None
        assert registry.remove(rule.id) is False

    def test_list_filtered_by_metric(self) -> None:
        registry = WatcherRegistry()
        registry.add(_rule(metric="a"))
        registry.add(_rule(metric="b"))
        assert len(registry.list_rules(metric="a")) == 1
        assert len(registry.list_rules()) == 2

    def test_stats(self) -> None:
        registry = WatcherRegistry()
        registry.add(_rule())
        registry.add(_rule(enabled=False))
        stats = registry.stats
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["disabled"] == 1


class TestDescribe:
    """Ega o'qiydigan tavsif — har taqqoslash uchun matn bor."""

    @pytest.mark.parametrize("comparison", list(WatchComparison))
    def test_every_comparison_has_description(self, comparison: WatchComparison) -> None:
        text = _rule(comparison=comparison, threshold=5.0).describe()
        assert text
        assert "m" in text


class TestMetricRegistry:
    """Metrika manbalari."""

    async def test_read_unknown_metric_returns_none(self) -> None:
        assert await MetricRegistry().read("yoq") is None

    def test_known_lists_sorted(self) -> None:
        registry = MetricRegistry()
        registry.register("z", lambda: _make(1.0))
        registry.register("a", lambda: _make(1.0))
        assert registry.known == ["a", "z"]

    def test_unregister(self) -> None:
        registry = MetricRegistry()
        registry.register("a", lambda: _make(1.0))
        assert registry.unregister("a") is True
        assert registry.unregister("a") is False
