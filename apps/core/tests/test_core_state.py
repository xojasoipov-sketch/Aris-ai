"""CoreState — Sleep/Active AI Core interfeysi testlari (gap-analysis #20)."""

from __future__ import annotations

from datetime import UTC, datetime

from zet.core.state import CoreMode, CoreState


def _fixed_now() -> datetime:
    return datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)


class TestCoreState:
    def test_default_is_active(self) -> None:
        state = CoreState()
        assert state.mode is CoreMode.ACTIVE
        assert state.is_sleeping is False
        assert state.reason is None
        assert state.changed_at is None

    def test_sleep(self) -> None:
        state = CoreState()
        state.sleep(reason="Ta'til", by="owner", now=_fixed_now())
        assert state.mode is CoreMode.SLEEPING
        assert state.is_sleeping is True
        assert state.reason == "Ta'til"
        assert state.changed_by == "owner"
        assert state.changed_at == _fixed_now()

    def test_wake(self) -> None:
        state = CoreState()
        state.sleep(reason="Ta'til")
        state.wake(reason="Qaytdim", by="telegram", now=_fixed_now())
        assert state.mode is CoreMode.ACTIVE
        assert state.is_sleeping is False
        assert state.reason == "Qaytdim"
        assert state.changed_by == "telegram"

    def test_sleep_idempotent(self) -> None:
        """Ketma-ket sleep() chaqirish xato bermaydi — faqat sababni yangilaydi."""
        state = CoreState()
        state.sleep(reason="Birinchi")
        state.sleep(reason="Ikkinchi")
        assert state.reason == "Ikkinchi"
        assert state.is_sleeping is True

    def test_to_dict(self) -> None:
        state = CoreState()
        state.sleep(reason="Test", by="cli", now=_fixed_now())
        data = state.to_dict()
        assert data["mode"] == "sleeping"
        assert data["reason"] == "Test"
        assert data["changed_by"] == "cli"
        assert data["changed_at"] == _fixed_now().isoformat()

    def test_default_to_dict(self) -> None:
        data = CoreState().to_dict()
        assert data["mode"] == "active"
        assert data["reason"] is None
        assert data["changed_at"] is None
        assert data["changed_by"] is None

    def test_core_mode_values(self) -> None:
        assert CoreMode.ACTIVE.value == "active"
        assert CoreMode.SLEEPING.value == "sleeping"
