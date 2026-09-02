"""Mustaqil maqsad tsikli testlari — agentning 5-xususiyati (L4).

Eng muhim invariant: baholash KONSERVATIV. Noaniq javob "yetildi" deb
o'qilsa, ega ish bitgan deb o'ylab tekshirmay qoladi — avtonom tizimda
eng qimmat xato shu.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.agents.registry import AgentRegistry
from zet.automation.autonomy import AutonomyLevel, AutonomyViolationError
from zet.automation.goal import (
    ACHIEVED_MARKER,
    NOT_ACHIEVED_MARKER,
    Goal,
    GoalIteration,
    GoalPursuit,
    GoalRegistry,
    GoalStatus,
    build_command,
    build_evaluation_command,
    parse_evaluation,
)
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


def _goal(**kwargs: object) -> Goal:
    base: dict[str, object] = {
        "name": "Test maqsad",
        "outcome": "Hisobot tayyor bo'lsin",
        "agent_name": "worker",
    }
    base.update(kwargs)
    return Goal.model_validate(base)


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(
        AgentSpec(name="worker", description="Ishchi", system_prompt="Sen ishchisan."),
        status=AgentStatus.ACTIVE,
    )
    return reg


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


class TestParseEvaluation:
    """Baholovchi javobini o'qish — konservativ."""

    def test_achieved_is_recognised(self) -> None:
        achieved, critique = parse_evaluation(f"{ACHIEVED_MARKER}: hammasi joyida")
        assert achieved is True
        assert critique == "hammasi joyida"

    def test_not_achieved_is_recognised(self) -> None:
        achieved, critique = parse_evaluation(f"{NOT_ACHIEVED_MARKER}: raqamlar yo'q")
        assert achieved is False
        assert critique == "raqamlar yo'q"

    def test_not_achieved_wins_over_substring_achieved(self) -> None:
        """'NOT_ACHIEVED' ichida 'ACHIEVED' bor — noto'g'ri o'qilmasin."""
        achieved, _ = parse_evaluation(NOT_ACHIEVED_MARKER)
        assert achieved is False

    def test_case_insensitive(self) -> None:
        achieved, _ = parse_evaluation("achieved: bo'ldi")
        assert achieved is True

    def test_unparseable_answer_counts_as_not_achieved(self) -> None:
        """Noaniqlikda g'alaba e'lon qilinmaydi."""
        achieved, critique = parse_evaluation("Menimcha yaxshi chiqdi, lekin bilmadim")
        assert achieved is False
        assert critique

    def test_empty_answer_counts_as_not_achieved(self) -> None:
        achieved, _ = parse_evaluation("")
        assert achieved is False


class TestCommandBuilding:
    """Reja matni — birinchi urinish va qayta urinish."""

    def test_first_attempt_has_no_critique(self) -> None:
        command = build_command(_goal(), previous=None)
        assert "MAQSAD:" in command
        assert "OLDINGI URINISH" not in command

    def test_retry_includes_previous_critique(self) -> None:
        """O'zini yaxshilash — tanqid keyingi rejaga kiradi."""
        previous = GoalIteration(index=0, command="c", output="natija", critique="manba yo'q")
        command = build_command(_goal(), previous=previous)
        assert "OLDINGI URINISH" in command
        assert "manba yo'q" in command
        assert "takrorlama" in command

    def test_success_criteria_included_when_set(self) -> None:
        command = build_command(_goal(success_criteria="Kamida 3 manba"), previous=None)
        assert "Kamida 3 manba" in command

    def test_evaluation_command_demands_strict_format(self) -> None:
        command = build_evaluation_command(_goal(), "natija matni")
        assert ACHIEVED_MARKER in command
        assert NOT_ACHIEVED_MARKER in command
        assert "natija matni" in command


class TestAutonomyGate:
    """Daraja tsiklga ruxsat beradimi."""

    def test_attempt_limit_comes_from_level(self) -> None:
        assert _goal(autonomy_level=AutonomyLevel.L3_AGENT).attempt_limit == 1
        assert _goal(autonomy_level=AutonomyLevel.L4_AUTONOMOUS).attempt_limit == 5

    async def test_low_level_cannot_pursue_a_goal(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        pursuit = GoalPursuit(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        with pytest.raises(AutonomyViolationError):
            await pursuit.pursue(_goal(autonomy_level=AutonomyLevel.L2_PIPELINE))


class TestPursuit:
    """Tsiklning haqiqiy ishlashi (FakeProvider orqali)."""

    async def test_l3_makes_exactly_one_attempt(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """L3 rejalashtiradi, lekin QAYTA urinmaydi."""
        pursuit = GoalPursuit(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        done = await pursuit.pursue(_goal(autonomy_level=AutonomyLevel.L3_AGENT))

        assert done.attempts_used == 1
        assert done.is_terminal

    async def test_l4_retries_until_limit(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """FakeProvider hech qachon ACHIEVED demaydi — chegarada to'xtaydi."""
        pursuit = GoalPursuit(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        done = await pursuit.pursue(_goal(autonomy_level=AutonomyLevel.L4_AUTONOMOUS))

        assert done.status == GoalStatus.EXHAUSTED
        assert done.attempts_used == 5

    async def test_missing_agent_fails_cleanly(self, tool_registry: ToolRegistry) -> None:
        pursuit = GoalPursuit(
            agent_registry=AgentRegistry(),
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        done = await pursuit.pursue(_goal(autonomy_level=AutonomyLevel.L3_AGENT))

        assert done.status == GoalStatus.FAILED
        assert done.iterations[0].error is not None

    async def test_killswitch_stops_the_loop(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        ks = KillSwitchState()
        ks.engage(reason="test", by="owner")
        pursuit = GoalPursuit(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
            killswitch=ks,
        )
        done = await pursuit.pursue(_goal(autonomy_level=AutonomyLevel.L4_AUTONOMOUS))

        assert done.status == GoalStatus.STOPPED
        assert done.attempts_used == 0

    async def test_retry_carries_critique_forward(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """2-urinish buyrug'ida 1-urinish tanqidi bo'ladi."""
        pursuit = GoalPursuit(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        done = await pursuit.pursue(_goal(autonomy_level=AutonomyLevel.L4_AUTONOMOUS))

        assert "OLDINGI URINISH" in done.iterations[1].command


class TestGoalRegistry:
    """Maqsadlar registri."""

    def test_add_get_remove(self) -> None:
        registry = GoalRegistry()
        goal = registry.add(_goal())
        assert registry.get(goal.id) is not None
        assert registry.remove(goal.id) is True
        assert registry.get(goal.id) is None

    def test_save_overwrites(self) -> None:
        registry = GoalRegistry()
        goal = registry.add(_goal())
        registry.save(goal.model_copy(update={"status": GoalStatus.ACHIEVED}))
        stored = registry.get(goal.id)
        assert stored is not None
        assert stored.status == GoalStatus.ACHIEVED

    def test_list_filtered_by_status(self) -> None:
        registry = GoalRegistry()
        registry.add(_goal())
        registry.add(_goal(status=GoalStatus.ACHIEVED))
        assert len(registry.list_goals(status=GoalStatus.ACHIEVED)) == 1
        assert len(registry.list_goals()) == 2

    def test_stats(self) -> None:
        registry = GoalRegistry()
        registry.add(_goal(status=GoalStatus.ACHIEVED))
        registry.add(_goal(status=GoalStatus.FAILED))
        stats = registry.stats
        assert stats["total"] == 2
        assert stats["achieved"] == 1
        assert stats["failed"] == 1
