"""Z1.12 — PermissionPolicy testlari.

Tekshiriladi:
    - READ → har doim avtomatik
    - WRITE → sozlanadigan (default avtomatik)
    - EXECUTE → har doim tasdiq
    - ADMIN → har doim tasdiq
    - UNTRUSTED + WRITE → tasdiq
    - UNTRUSTED + READ → avtomatik
    - Yuqori xavfli tool → har doim tasdiq
    - auto_approve_write=False → WRITE tasdiq
"""

from __future__ import annotations

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.security.permissions import HIGH_RISK_TOOLS, PermissionPolicy


class TestPermissionPolicy:
    """PermissionPolicy testlari."""

    def test_read_always_allowed(self) -> None:
        """READ — har doim avtomatik."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.READ, TrustLevel.OWNER)

        assert decision.allowed is True
        assert decision.needs_approval is False

    def test_read_untrusted_allowed(self) -> None:
        """UNTRUSTED kontekst + READ → avtomatik."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.READ, TrustLevel.UNTRUSTED)

        assert decision.allowed is True
        assert decision.needs_approval is False

    def test_write_default_allowed(self) -> None:
        """WRITE — default avtomatik."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.WRITE, TrustLevel.OWNER)

        assert decision.allowed is True
        assert decision.needs_approval is False

    def test_write_untrusted_needs_approval(self) -> None:
        """UNTRUSTED + WRITE → tasdiq kerak."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.WRITE, TrustLevel.UNTRUSTED)

        assert decision.allowed is False
        assert decision.needs_approval is True
        assert "UNTRUSTED" in decision.reason

    def test_write_auto_approve_disabled(self) -> None:
        """auto_approve_write=False → WRITE tasdiq kerak."""
        policy = PermissionPolicy(auto_approve_write=False)
        decision = policy.check(PermissionLevel.WRITE, TrustLevel.OWNER)

        assert decision.allowed is False
        assert decision.needs_approval is True

    def test_execute_always_needs_approval(self) -> None:
        """EXECUTE — har doim tasdiq."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.EXECUTE, TrustLevel.OWNER)

        assert decision.allowed is False
        assert decision.needs_approval is True

    def test_admin_always_needs_approval(self) -> None:
        """ADMIN — har doim tasdiq."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.ADMIN, TrustLevel.OWNER)

        assert decision.allowed is False
        assert decision.needs_approval is True

    def test_execute_untrusted_needs_approval(self) -> None:
        """UNTRUSTED + EXECUTE → tasdiq."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.EXECUTE, TrustLevel.UNTRUSTED)

        assert decision.allowed is False
        assert decision.needs_approval is True

    def test_high_risk_tool_always_needs_approval(self) -> None:
        """Yuqori xavfli tool — har doim tasdiq, hatto READ bo'lsa ham."""
        policy = PermissionPolicy()
        decision = policy.check(
            PermissionLevel.READ,
            TrustLevel.OWNER,
            tool_name="shell.exec",
        )

        assert decision.allowed is False
        assert decision.needs_approval is True
        assert "xavfli" in decision.reason.lower()

    def test_high_risk_tool_write(self) -> None:
        """Yuqori xavfli tool + WRITE — tasdiq."""
        policy = PermissionPolicy()
        decision = policy.check(
            PermissionLevel.WRITE,
            TrustLevel.OWNER,
            tool_name="file.delete",
        )

        assert decision.allowed is False
        assert decision.needs_approval is True

    def test_system_trust_write_allowed(self) -> None:
        """SYSTEM trust + WRITE → avtomatik."""
        policy = PermissionPolicy()
        decision = policy.check(PermissionLevel.WRITE, TrustLevel.SYSTEM)

        assert decision.allowed is True
        assert decision.needs_approval is False

    def test_custom_high_risk_tools(self) -> None:
        """Maxsus yuqori xavfli toollar."""
        policy = PermissionPolicy(high_risk_tools=frozenset({"custom.dangerous"}))

        # shell.exec endi HIGH_RISK emas
        decision = policy.check(
            PermissionLevel.READ,
            TrustLevel.OWNER,
            tool_name="shell.exec",
        )
        assert decision.allowed is True

        # custom.dangerous — tasdiq
        decision2 = policy.check(
            PermissionLevel.READ,
            TrustLevel.OWNER,
            tool_name="custom.dangerous",
        )
        assert decision2.needs_approval is True

    def test_normal_tool_not_high_risk(self) -> None:
        """Oddiy tool — yuqori xavfli emas."""
        policy = PermissionPolicy()
        decision = policy.check(
            PermissionLevel.READ,
            TrustLevel.OWNER,
            tool_name="time.now",
        )

        assert decision.allowed is True
        assert decision.needs_approval is False

    def test_high_risk_tools_constant(self) -> None:
        """HIGH_RISK_TOOLS ro'yxati shell.exec ni o'z ichiga oladi."""
        assert "shell.exec" in HIGH_RISK_TOOLS
        assert "file.delete" in HIGH_RISK_TOOLS

    def test_no_tool_name_not_high_risk(self) -> None:
        """tool_name=None — yuqori xavfli tekshiruvi o'tkazib yuboriladi."""
        policy = PermissionPolicy()
        decision = policy.check(
            PermissionLevel.READ,
            TrustLevel.OWNER,
            tool_name=None,
        )
        assert decision.allowed is True
