"""Z1.12 — KillSwitch testlari.

Tekshiriladi:
    - Default holatda o'chirilgan
    - engage() yoqadi
    - check() yoqilganda KillSwitchEngagedError beradi
    - disengage() o'chiradi
    - Ikki marta engage() idempotent
    - O'chirilgan killswitch'ni disengage() → ValueError
    - to_dict() holat qaytaradi
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState

_NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)


class TestKillSwitch:
    """KillSwitch testlari."""

    def test_default_disengaged(self) -> None:
        """Default holatda o'chirilgan."""
        ks = KillSwitchState()
        assert ks.is_engaged is False
        assert ks.reason is None
        assert ks.engaged_at is None

    def test_check_disengaged_ok(self) -> None:
        """O'chirilgan holatda check() xato bermaydi."""
        ks = KillSwitchState()
        ks.check()  # Xato bo'lmasligi kerak

    def test_engage(self) -> None:
        """engage() yoqadi."""
        ks = KillSwitchState()
        ks.engage(reason="Test xavf", by="owner", now=_NOW)

        assert ks.is_engaged is True
        assert ks.reason == "Test xavf"
        assert ks.engaged_at == _NOW
        assert ks.engaged_by == "owner"

    def test_check_engaged_raises(self) -> None:
        """Yoqilganda check() → KillSwitchEngagedError."""
        ks = KillSwitchState()
        ks.engage(reason="Xavf", now=_NOW)

        with pytest.raises(KillSwitchEngagedError, match="Xavf"):
            ks.check()

    def test_disengage(self) -> None:
        """disengage() o'chiradi."""
        ks = KillSwitchState()
        ks.engage(reason="Test", now=_NOW)
        ks.disengage(by="owner")

        assert ks.is_engaged is False
        assert ks.reason is None
        assert ks.engaged_at is None

    def test_check_after_disengage_ok(self) -> None:
        """O'chirilgandan keyin check() xato bermaydi."""
        ks = KillSwitchState()
        ks.engage(reason="Test", now=_NOW)
        ks.disengage()
        ks.check()  # Xato bo'lmasligi kerak

    def test_engage_idempotent(self) -> None:
        """Ikki marta engage() — ikkinchisi e'tiborga olinmaydi."""
        ks = KillSwitchState()
        ks.engage(reason="Birinchi", now=_NOW)
        ks.engage(reason="Ikkinchi", now=_NOW)

        assert ks.reason == "Birinchi"  # Birinchi sabab saqlanadi

    def test_disengage_when_off_raises(self) -> None:
        """O'chirilgan killswitch'ni disengage() → ValueError."""
        ks = KillSwitchState()

        with pytest.raises(ValueError, match="o'chirilgan"):
            ks.disengage()

    def test_to_dict_disengaged(self) -> None:
        """to_dict — o'chirilgan holat."""
        ks = KillSwitchState()
        d = ks.to_dict()

        assert d["engaged"] is False
        assert d["reason"] is None
        assert d["engaged_at"] is None
        assert d["engaged_by"] is None

    def test_to_dict_engaged(self) -> None:
        """to_dict — yoqilgan holat."""
        ks = KillSwitchState()
        ks.engage(reason="Test", by="admin", now=_NOW)
        d = ks.to_dict()

        assert d["engaged"] is True
        assert d["reason"] == "Test"
        assert d["engaged_by"] == "admin"
        assert d["engaged_at"] is not None

    def test_engage_default_values(self) -> None:
        """Default qiymatlar bilan engage()."""
        ks = KillSwitchState()
        ks.engage()

        assert ks.is_engaged is True
        assert ks.reason == "Emergency stop"
        assert ks.engaged_by == "owner"
        assert ks.engaged_at is not None
