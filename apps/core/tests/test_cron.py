"""automation/cron.py testlari — soddalashtirilgan cron mos kelish tekshiruvi."""

from __future__ import annotations

from datetime import UTC, datetime

from zet.automation.cron import is_due


def _dt(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


class TestIsDue:
    def test_wildcard_always_due(self) -> None:
        assert is_due("* * * * *", _dt(8, 12, 9, 30))

    def test_exact_minute_hour_match(self) -> None:
        assert is_due("30 9 * * *", _dt(8, 12, 9, 30))

    def test_wrong_minute_not_due(self) -> None:
        assert not is_due("30 9 * * *", _dt(8, 12, 9, 31))

    def test_wrong_hour_not_due(self) -> None:
        assert not is_due("30 9 * * *", _dt(8, 12, 10, 30))

    def test_shortcut_daily(self) -> None:
        assert is_due("@daily", _dt(8, 12, 0, 0))
        assert not is_due("@daily", _dt(8, 12, 0, 1))

    def test_shortcut_hourly(self) -> None:
        assert is_due("@hourly", _dt(8, 12, 14, 0))
        assert not is_due("@hourly", _dt(8, 12, 14, 5))

    def test_shortcut_weekly_sunday(self) -> None:
        # 2026-08-16 — yakshanba
        assert is_due("@weekly", _dt(8, 16, 0, 0))
        assert not is_due("@weekly", _dt(8, 17, 0, 0))

    def test_shortcut_monthly(self) -> None:
        assert is_due("@monthly", _dt(9, 1, 0, 0))
        assert not is_due("@monthly", _dt(9, 2, 0, 0))

    def test_step_field_every_15_minutes(self) -> None:
        assert is_due("*/15 * * * *", _dt(8, 12, 9, 0))
        assert is_due("*/15 * * * *", _dt(8, 12, 9, 15))
        assert not is_due("*/15 * * * *", _dt(8, 12, 9, 5))

    def test_list_field(self) -> None:
        assert is_due("0 8,18 * * *", _dt(8, 12, 18, 0))
        assert not is_due("0 8,18 * * *", _dt(8, 12, 12, 0))

    def test_range_field(self) -> None:
        assert is_due("0 9-17 * * *", _dt(8, 12, 12, 0))
        assert not is_due("0 9-17 * * *", _dt(8, 12, 20, 0))

    def test_weekday_field_monday_friday(self) -> None:
        # 2026-08-10 — dushanba, 2026-08-15 — shanba
        assert is_due("0 9 * * 1-5", _dt(8, 10, 9, 0))
        assert not is_due("0 9 * * 1-5", _dt(8, 15, 9, 0))

    def test_invalid_field_count_returns_false(self) -> None:
        assert not is_due("* * *", _dt(8, 12, 9, 0))

    def test_invalid_expression_fails_closed(self) -> None:
        assert not is_due("not-a-cron", _dt(8, 12, 9, 0))

    def test_month_field(self) -> None:
        assert is_due("0 0 1 8 *", _dt(8, 1, 0, 0))
        assert not is_due("0 0 1 8 *", _dt(9, 1, 0, 0))
