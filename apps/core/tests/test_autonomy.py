"""Avtonomiya darajalari L0-L4 testlari (yangi zip, slayd 8-9)."""

from __future__ import annotations

import itertools

import pytest

from zet.automation.autonomy import (
    AutonomyCapability,
    AutonomyLevel,
    AutonomyViolationError,
    allows,
    effective_permission,
    max_goal_iterations,
    policy_for,
    require,
)
from zet.domain.enums import PermissionLevel


class TestLevelOrdering:
    """Darajalar tartibi va yorliqlari."""

    def test_ranks_are_ordered(self) -> None:
        levels = [
            AutonomyLevel.L0_CHAT,
            AutonomyLevel.L1_CONNECTED,
            AutonomyLevel.L2_PIPELINE,
            AutonomyLevel.L3_AGENT,
            AutonomyLevel.L4_AUTONOMOUS,
        ]
        assert [lv.rank for lv in levels] == [0, 1, 2, 3, 4]

    def test_every_level_has_uzbek_label(self) -> None:
        for level in AutonomyLevel:
            assert level.label
            assert level.label != level.value


class TestCapabilities:
    """Har daraja aynan nima ochadi."""

    def test_l0_opens_nothing(self) -> None:
        for capability in AutonomyCapability:
            assert not allows(AutonomyLevel.L0_CHAT, capability)

    def test_l1_opens_only_tools(self) -> None:
        assert allows(AutonomyLevel.L1_CONNECTED, AutonomyCapability.USE_TOOLS)
        assert not allows(AutonomyLevel.L1_CONNECTED, AutonomyCapability.TRIGGERED_RUN)

    def test_l2_adds_triggered_run(self) -> None:
        assert allows(AutonomyLevel.L2_PIPELINE, AutonomyCapability.TRIGGERED_RUN)
        assert not allows(AutonomyLevel.L2_PIPELINE, AutonomyCapability.SELF_PLANNING)

    def test_l3_adds_self_planning_but_not_self_improve(self) -> None:
        assert allows(AutonomyLevel.L3_AGENT, AutonomyCapability.SELF_PLANNING)
        assert not allows(AutonomyLevel.L3_AGENT, AutonomyCapability.SELF_IMPROVE)

    def test_l4_opens_everything(self) -> None:
        for capability in AutonomyCapability:
            assert allows(AutonomyLevel.L4_AUTONOMOUS, capability)

    def test_capabilities_are_cumulative(self) -> None:
        """Yuqori daraja pastdagining hamma imkoniyatini o'z ichiga oladi."""
        ordered = sorted(AutonomyLevel, key=lambda lv: lv.rank)
        for lower, higher in itertools.pairwise(ordered):
            assert policy_for(lower).capabilities <= policy_for(higher).capabilities


class TestRequire:
    """`require()` — yo'q imkoniyatda xato."""

    def test_passes_when_allowed(self) -> None:
        require(AutonomyLevel.L4_AUTONOMOUS, AutonomyCapability.SELF_IMPROVE)

    def test_raises_when_denied(self) -> None:
        with pytest.raises(AutonomyViolationError):
            require(AutonomyLevel.L2_PIPELINE, AutonomyCapability.SELF_PLANNING)

    def test_error_names_the_subject_and_minimum_level(self) -> None:
        with pytest.raises(AutonomyViolationError) as exc:
            require(
                AutonomyLevel.L0_CHAT,
                AutonomyCapability.SELF_IMPROVE,
                subject="smm",
            )
        message = str(exc.value)
        assert "smm" in message
        assert AutonomyLevel.L4_AUTONOMOUS.value in message


class TestEffectivePermission:
    """Daraja ruxsatni FAQAT pasaytiradi — hech qachon ko'tarmaydi."""

    def test_l0_caps_at_read(self) -> None:
        got = effective_permission(AutonomyLevel.L0_CHAT, PermissionLevel.EXECUTE)
        assert got == PermissionLevel.READ

    def test_l1_caps_at_write(self) -> None:
        got = effective_permission(AutonomyLevel.L1_CONNECTED, PermissionLevel.ADMIN)
        assert got == PermissionLevel.WRITE

    def test_never_raises_requested_permission(self) -> None:
        """L4 ham READ agentni EXECUTE ga ko'tarmaydi."""
        got = effective_permission(AutonomyLevel.L4_AUTONOMOUS, PermissionLevel.READ)
        assert got == PermissionLevel.READ

    def test_admin_never_granted_by_autonomy(self) -> None:
        """ADMIN faqat eganing aniq sozlamasi bilan — daraja orqali emas."""
        for level in AutonomyLevel:
            got = effective_permission(level, PermissionLevel.ADMIN)
            assert got != PermissionLevel.ADMIN


class TestApprovalInvariant:
    """V-32 hech bir darajada bekor qilinmaydi."""

    def test_every_level_requires_approval_for_execute(self) -> None:
        for level in AutonomyLevel:
            assert policy_for(level).requires_approval_for_execute is True


class TestGoalIterations:
    """Maqsad tsikli chegarasi darajaga bog'liq."""

    def test_low_levels_have_no_goal_loop(self) -> None:
        for level in (
            AutonomyLevel.L0_CHAT,
            AutonomyLevel.L1_CONNECTED,
            AutonomyLevel.L2_PIPELINE,
        ):
            assert max_goal_iterations(level) == 0

    def test_l3_gets_single_attempt(self) -> None:
        assert max_goal_iterations(AutonomyLevel.L3_AGENT) == 1

    def test_l4_gets_multiple_attempts(self) -> None:
        assert max_goal_iterations(AutonomyLevel.L4_AUTONOMOUS) > 1
