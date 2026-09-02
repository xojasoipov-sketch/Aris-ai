"""Bo'lim 3 — Agent domen modellari va AgentStatus testlari.

Tekshiriladi:
    - AgentStatus holat mashinasi (V-11)
    - AgentSpec validatsiyasi
    - AgentState metrikalar
    - AgentRunResult
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zet.domain.agent import AgentRunResult, AgentSpec, AgentState
from zet.domain.enums import (
    AGENT_TRANSITIONS,
    AgentStatus,
    ModelTier,
    PermissionLevel,
)


class TestAgentStatus:
    """V-11 holat mashinasi testlari."""

    def test_all_statuses_exist(self) -> None:
        """6 ta holat mavjud."""
        assert len(AgentStatus) == 6

    def test_draft_is_not_active(self) -> None:
        assert not AgentStatus.DRAFT.is_active

    def test_active_is_active(self) -> None:
        assert AgentStatus.ACTIVE.is_active

    def test_archived_is_terminal(self) -> None:
        assert AgentStatus.ARCHIVED.is_terminal

    def test_active_is_not_terminal(self) -> None:
        assert not AgentStatus.ACTIVE.is_terminal

    def test_draft_to_testing(self) -> None:
        assert AgentStatus.DRAFT.can_transition_to(AgentStatus.TESTING)

    def test_draft_to_active_blocked(self) -> None:
        """DRAFT dan to'g'ridan-to'g'ri ACTIVE ga o'tib bo'lmaydi."""
        assert not AgentStatus.DRAFT.can_transition_to(AgentStatus.ACTIVE)

    def test_testing_to_active(self) -> None:
        assert AgentStatus.TESTING.can_transition_to(AgentStatus.ACTIVE)

    def test_testing_to_draft(self) -> None:
        """TESTING dan DRAFT ga qaytish mumkin."""
        assert AgentStatus.TESTING.can_transition_to(AgentStatus.DRAFT)

    def test_active_to_paused(self) -> None:
        assert AgentStatus.ACTIVE.can_transition_to(AgentStatus.PAUSED)

    def test_paused_to_active(self) -> None:
        assert AgentStatus.PAUSED.can_transition_to(AgentStatus.ACTIVE)

    def test_disabled_to_draft(self) -> None:
        """Tuzatish uchun DRAFT ga qaytish."""
        assert AgentStatus.DISABLED.can_transition_to(AgentStatus.DRAFT)

    def test_archived_has_no_transitions(self) -> None:
        """Terminal holat — hech qayerga o'ta olmaydi."""
        for status in AgentStatus:
            assert not AgentStatus.ARCHIVED.can_transition_to(status)

    def test_all_non_archived_can_archive(self) -> None:
        """Barcha holatlardan arxivlash mumkin (ARCHIVED dan tashqari)."""
        for status in AgentStatus:
            if status != AgentStatus.ARCHIVED:
                assert status.can_transition_to(AgentStatus.ARCHIVED)

    def test_transitions_dict_covers_all(self) -> None:
        """AGENT_TRANSITIONS har bir holatni o'z ichiga oladi."""
        for status in AgentStatus:
            assert status in AGENT_TRANSITIONS


class TestAgentSpec:
    def test_basic_creation(self) -> None:
        spec = AgentSpec(
            name="test_agent",
            description="Test uchun agent",
            system_prompt="Sen test agentisan.",
        )
        assert spec.name == "test_agent"
        assert spec.version == 1
        assert spec.model_policy == ModelTier.T1_FREE
        assert spec.permission_level == PermissionLevel.READ

    def test_name_validation(self) -> None:
        with pytest.raises(ValidationError):
            AgentSpec(name="", description="test", system_prompt="test")

    def test_name_max_length(self) -> None:
        with pytest.raises(ValidationError):
            AgentSpec(name="a" * 65, description="test", system_prompt="test")

    def test_frozen(self) -> None:
        spec = AgentSpec(
            name="test",
            description="test",
            system_prompt="test",
        )
        with pytest.raises(ValidationError):
            spec.name = "changed"  # type: ignore[misc]

    def test_max_steps_validation(self) -> None:
        with pytest.raises(ValidationError):
            AgentSpec(
                name="test",
                description="test",
                system_prompt="test",
                max_steps=0,
            )

    def test_timeout_validation(self) -> None:
        with pytest.raises(ValidationError):
            AgentSpec(
                name="test",
                description="test",
                system_prompt="test",
                timeout_s=5,  # Minimum 10
            )

    def test_tool_allowlist(self) -> None:
        spec = AgentSpec(
            name="test",
            description="test",
            system_prompt="test",
            tool_allowlist=["time.now", "web.search"],
        )
        assert "time.now" in spec.tool_allowlist
        assert len(spec.tool_allowlist) == 2


class TestAgentState:
    def test_success_rate_zero(self) -> None:
        state = AgentState(
            spec=AgentSpec(name="t", description="t", system_prompt="t"),
        )
        assert state.success_rate == 0.0

    def test_success_rate_calculation(self) -> None:
        state = AgentState(
            spec=AgentSpec(name="t", description="t", system_prompt="t"),
            total_runs=10,
            successful_runs=7,
            failed_runs=3,
        )
        assert state.success_rate == pytest.approx(0.7)

    def test_default_status_is_draft(self) -> None:
        state = AgentState(
            spec=AgentSpec(name="t", description="t", system_prompt="t"),
        )
        assert state.status == AgentStatus.DRAFT


class TestAgentRunResult:
    def test_success_result(self) -> None:
        result = AgentRunResult(
            agent_name="research",
            success=True,
            output="Hisobot matni",
            sources=["https://example.com"],
            tool_calls_count=3,
            steps_count=2,
        )
        assert result.success
        assert result.output == "Hisobot matni"
        assert len(result.sources) == 1

    def test_failure_result(self) -> None:
        result = AgentRunResult(
            agent_name="research",
            success=False,
            error="Timeout",
        )
        assert not result.success
        assert result.error == "Timeout"
        assert result.tool_calls_count == 0
