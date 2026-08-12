"""automation/executor.py testlari — Workflow zanjirini haqiqiy AgentRuntime bilan bajarish."""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.agents.registry import AgentRegistry
from zet.automation.executor import AgentUnavailableError, WorkflowExecutor, run_agent_command
from zet.automation.workflow import WorkflowRunner, WorkflowStatus, WorkflowStep
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


def _spec(name: str = "worker") -> AgentSpec:
    return AgentSpec(
        name=name,
        description="Test ishchisi",
        system_prompt="Sen ishchisan.",
    )


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(_spec(), status=AgentStatus.ACTIVE)
    return reg


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


class TestRunAgentCommand:
    async def test_runs_active_agent(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        result = await run_agent_command(
            "worker",
            "Vazifani bajar",
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        assert result.agent_name == "worker"

    async def test_records_run_metrics(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        await run_agent_command(
            "worker",
            "Vazifa",
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        state = agent_registry.get("worker")
        assert state.total_runs == 1

    async def test_unavailable_agent_raises(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        with pytest.raises(AgentUnavailableError):
            await run_agent_command(
                "nonexistent",
                "Vazifa",
                agent_registry=agent_registry,
                tool_registry=tool_registry,
                permission_policy=PermissionPolicy(),
            )

    async def test_not_active_agent_raises(self, tool_registry: ToolRegistry) -> None:
        reg = AgentRegistry()
        reg.register(_spec())  # DRAFT, faol emas
        with pytest.raises(AgentUnavailableError):
            await run_agent_command(
                "worker",
                "Vazifa",
                agent_registry=reg,
                tool_registry=tool_registry,
                permission_policy=PermissionPolicy(),
            )


class TestWorkflowExecutor:
    @pytest.fixture()
    def workflows(self) -> WorkflowRunner:
        return WorkflowRunner()

    @pytest.fixture()
    def executor(
        self,
        workflows: WorkflowRunner,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
    ) -> WorkflowExecutor:
        return WorkflowExecutor(
            workflows=workflows,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )

    async def test_single_step_completes(
        self, executor: WorkflowExecutor, workflows: WorkflowRunner
    ) -> None:
        chain = workflows.create(
            name="Bitta qadam",
            steps=[WorkflowStep(agent_name="worker", command_template="Ishla")],
        )
        result = await executor.run_to_completion(chain.id)
        assert result.status == WorkflowStatus.COMPLETED
        assert result.steps[0].status == WorkflowStatus.COMPLETED

    async def test_two_step_chain_passes_prev_output(
        self, executor: WorkflowExecutor, workflows: WorkflowRunner
    ) -> None:
        chain = workflows.create(
            name="Ikki qadam",
            steps=[
                WorkflowStep(agent_name="worker", command_template="Birinchi qadam"),
                WorkflowStep(agent_name="worker", command_template="Oldingi: {prev_output}"),
            ],
        )
        result = await executor.run_to_completion(chain.id)
        assert result.status == WorkflowStatus.COMPLETED
        assert result.completed_steps == 2

    async def test_unknown_agent_fails_chain(
        self, executor: WorkflowExecutor, workflows: WorkflowRunner
    ) -> None:
        chain = workflows.create(
            name="Noma'lum agent",
            steps=[WorkflowStep(agent_name="ghost", command_template="Ishla")],
        )
        result = await executor.run_to_completion(chain.id)
        assert result.status == WorkflowStatus.FAILED
        assert result.steps[0].error is not None

    async def test_approval_required_step_fails_not_bypassed(
        self, executor: WorkflowExecutor, workflows: WorkflowRunner
    ) -> None:
        chain = workflows.create(
            name="Tasdiq talab qiladi",
            steps=[
                WorkflowStep(
                    agent_name="worker", command_template="Xavfli amal", require_approval=True
                )
            ],
        )
        result = await executor.run_to_completion(chain.id)
        assert result.status == WorkflowStatus.FAILED
        assert "tasdiq" in (result.steps[0].error or "").lower()

    async def test_approval_step_never_runs_agent(
        self,
        workflows: WorkflowRunner,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        """require_approval qadam agentni HECH QACHON chaqirmasligini tekshiradi (V-32)."""
        executor = WorkflowExecutor(
            workflows=workflows,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        chain = workflows.create(
            name="Tasdiq",
            steps=[
                WorkflowStep(agent_name="worker", command_template="Xavfli", require_approval=True)
            ],
        )
        await executor.run_to_completion(chain.id)
        assert agent_registry.get("worker").total_runs == 0

    async def test_unknown_workflow_raises(self, executor: WorkflowExecutor) -> None:
        with pytest.raises(ValueError, match="topilmadi"):
            await executor.run_to_completion("no-such-id")


class TestRealProviderWiring:
    """`provider` berilsa — `FakeProvider()` o'rniga real (yoki har qanday
    berilgan) LLMProvider ishlatiladi, model esa agent.model_policy'dan
    hisoblanadi (`task_class_for_tier`)."""

    async def test_run_agent_command_uses_given_provider(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        from zet.llm.fake import FakeProvider

        custom_provider = FakeProvider(name="custom")
        result = await run_agent_command(
            "worker",
            "Vazifa",
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
            provider=custom_provider,
        )
        assert result.agent_name == "worker"
        assert custom_provider.calls  # haqiqatan chaqirilgan
        # model_policy default T1_FREE -> TaskClass.NORMAL
        assert custom_provider.calls[0]["model"] == "normal"

    async def test_run_agent_command_default_provider_uses_fake_model(
        self, agent_registry: AgentRegistry, tool_registry: ToolRegistry
    ) -> None:
        """`provider` berilmasa — eski xatti-harakat: model='fake'."""
        result = await run_agent_command(
            "worker",
            "Vazifa",
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
        )
        assert result.success is True

    async def test_workflow_executor_passes_provider_through(
        self,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        from zet.llm.fake import FakeProvider

        custom_provider = FakeProvider(name="custom")
        workflows = WorkflowRunner()
        executor = WorkflowExecutor(
            workflows=workflows,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(),
            provider=custom_provider,
        )
        chain = workflows.create(
            name="Real provider",
            steps=[WorkflowStep(agent_name="worker", command_template="Ishla")],
        )
        result = await executor.run_to_completion(chain.id)
        assert result.status == WorkflowStatus.COMPLETED
        assert custom_provider.calls
