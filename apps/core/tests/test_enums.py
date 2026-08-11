"""Z1.4 / Z1.6 — domen enum'lari va holat mashinasi testlari."""

from __future__ import annotations

from itertools import pairwise

import pytest

from zet.domain.enums import (
    RUN_TRANSITIONS,
    ModelTier,
    PermissionLevel,
    RunStatus,
    RunTrigger,
    StepStatus,
    TrustLevel,
)


class TestPermissionLevel:
    """V-31: READ < WRITE < EXECUTE < ADMIN."""

    def test_ordering(self) -> None:
        assert PermissionLevel.READ < PermissionLevel.WRITE
        assert PermissionLevel.WRITE < PermissionLevel.EXECUTE
        assert PermissionLevel.EXECUTE < PermissionLevel.ADMIN

    def test_ge_works(self) -> None:
        assert PermissionLevel.ADMIN >= PermissionLevel.READ
        assert PermissionLevel.READ >= PermissionLevel.READ
        assert not (PermissionLevel.READ >= PermissionLevel.WRITE)

    def test_sorting(self) -> None:
        levels = [PermissionLevel.ADMIN, PermissionLevel.READ, PermissionLevel.EXECUTE]
        assert sorted(levels) == [
            PermissionLevel.READ,
            PermissionLevel.EXECUTE,
            PermissionLevel.ADMIN,
        ]

    def test_serializes_as_string(self) -> None:
        """DB'da matn sifatida saqlanadi."""
        assert str(PermissionLevel.EXECUTE) == "execute"

    def test_comparison_with_other_type_is_not_implemented(self) -> None:
        with pytest.raises(TypeError):
            _ = PermissionLevel.READ < 5  # type: ignore[operator]


class TestModelTier:
    """ADR-0006: T0 -> T1 -> T2 -> T3 tartibi."""

    def test_rank_order(self) -> None:
        ranks = [t.rank for t in (ModelTier.T0_LOCAL, ModelTier.T1_FREE, ModelTier.T2_CHEAP)]
        assert ranks == sorted(ranks)

    def test_strong_tier_is_last(self) -> None:
        assert ModelTier.T3_STRONG.rank == max(t.rank for t in ModelTier)


class TestRunStateMachine:
    """A-01: o'tishlar cheklangan, terminal holatlardan chiqib bo'lmaydi."""

    def test_happy_path(self) -> None:
        path = [
            RunStatus.PENDING,
            RunStatus.PLANNING,
            RunStatus.EXECUTING,
            RunStatus.VERIFYING,
            RunStatus.DONE,
        ]
        for src, dst in pairwise(path):
            assert src.can_transition_to(dst), f"{src} -> {dst} ruxsat etilishi kerak"

    def test_approval_path(self) -> None:
        assert RunStatus.PLANNING.can_transition_to(RunStatus.AWAITING_APPROVAL)
        assert RunStatus.EXECUTING.can_transition_to(RunStatus.AWAITING_APPROVAL)
        assert RunStatus.AWAITING_APPROVAL.can_transition_to(RunStatus.EXECUTING)

    def test_verifier_can_send_back_to_executing(self) -> None:
        """Verifier natijani rad etsa, qayta bajarish mumkin."""
        assert RunStatus.VERIFYING.can_transition_to(RunStatus.EXECUTING)

    def test_terminal_states_are_final(self) -> None:
        for status in (RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED):
            assert status.is_terminal
            assert RUN_TRANSITIONS[status] == frozenset()

    def test_done_cannot_go_back_to_planning(self) -> None:
        assert not RunStatus.DONE.can_transition_to(RunStatus.PLANNING)

    def test_cannot_skip_planning(self) -> None:
        assert not RunStatus.PENDING.can_transition_to(RunStatus.EXECUTING)

    def test_every_status_has_transition_entry(self) -> None:
        assert set(RUN_TRANSITIONS) == set(RunStatus)

    def test_any_active_state_can_be_cancelled(self) -> None:
        """Emergency stop (V-33) istalgan faol holatdan ishlashi kerak."""
        for status in RunStatus:
            if not status.is_terminal:
                assert status.can_transition_to(RunStatus.CANCELLED), status


class TestStepStatus:
    def test_terminal_set(self) -> None:
        assert StepStatus.DONE.is_terminal
        assert StepStatus.FAILED.is_terminal
        assert StepStatus.SKIPPED.is_terminal
        assert not StepStatus.RUNNING.is_terminal
        assert not StepStatus.AWAITING_APPROVAL.is_terminal


class TestRunTrigger:
    def test_only_manual_is_not_autonomous(self) -> None:
        assert RunTrigger.MANUAL.is_autonomous is False
        for trigger in (
            RunTrigger.SCHEDULE,
            RunTrigger.WEBHOOK,
            RunTrigger.EVENT,
            RunTrigger.AGENT,
        ):
            assert trigger.is_autonomous is True, trigger


class TestTrustLevel:
    def test_three_levels_exist(self) -> None:
        """A-05: owner / system / untrusted."""
        assert set(TrustLevel) == {
            TrustLevel.OWNER,
            TrustLevel.SYSTEM,
            TrustLevel.UNTRUSTED,
        }
