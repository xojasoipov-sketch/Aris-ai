"""Workflow va trigger amallarini haqiqiy AgentRuntime orqali bajarish (Bo'lim 9).

Ilgari `AutomationEngine`/`WorkflowRunner` faqat ma'lumot modeli va
amal (Action) generatori edi — hech qanday kod ularni HAQIQATDA
bajarmasdi (`engine.py`ning o'z docstringi: "Orchestrator bu amallarni
bajaradi", lekin hech qanday Orchestrator/route buni qilmasdi).

`run_agent_command()` — Automation Engine, Workflow Executor va
`AutomationDaemon` bir xil yo'l bilan agentni ishga tushiradi.
`WorkflowExecutor` — bitta `WorkflowChain`ni boshidan oxirigacha
(barcha qadamlarni) shu funksiya orqali bajaradi.

Xavfsizlik:
    - `require_approval=True` qadamlar avtomatik BAJARILMAYDI — V-32
      talabini chetlab o'tmaslik uchun qadam xato bilan to'xtatiladi
      (approval kerak bo'lgan ishlarni hozircha faqat Orchestrator
      `/api/v1/run` orqali, tasdiq bilan bajaradi).
    - Har bir qadam `timeout_s`i bilan cheklangan (A-07).

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    V-32 — majburiy tasdiq
    A-07 — run tormozlari
"""

from __future__ import annotations

import asyncio

import structlog

from zet.agents.registry import AgentNotActiveError, AgentNotFoundError, AgentRegistry
from zet.agents.runtime import AgentRuntime
from zet.automation.workflow import WorkflowChain, WorkflowRunner, WorkflowStatus
from zet.domain.agent import AgentRunResult
from zet.domain.enums import TaskClass
from zet.llm.base import LLMProvider
from zet.llm.fake import FakeProvider
from zet.llm.routed_provider import task_class_for_tier
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


class AgentUnavailableError(RuntimeError):
    """Agent topilmadi yoki ACTIVE holatda emas."""


async def run_agent_command(
    agent_name: str,
    command: str,
    *,
    agent_registry: AgentRegistry,
    tool_registry: ToolRegistry,
    permission_policy: PermissionPolicy,
    timeout_s: int | None = None,
    provider: LLMProvider | None = None,
    task_class_override: TaskClass | None = None,
    killswitch: KillSwitchState | None = None,
) -> AgentRunResult:
    """Bitta agent buyrug'ini haqiqiy `AgentRuntime` orqali bajarish va metrikani yozish.

    `provider` berilmasa — `FakeProvider()` (default, testlar va eski
    chaqiruvchilar uchun o'zgarmagan xatti-harakat). Real LLM uchun
    chaqiruvchi `RoutedLLMProvider(router)` uzatishi kerak — `model`
    parametri odatda `agent.model_policy` asosida avtomatik hisoblanadi.

    `task_class_override` (JB-7): berilsa, `agent.model_policy`ning
    STATIK tier'i o'rniga shu `TaskClass` ishlatiladi. NEGA kerak:
    `agent.model_policy` butun agent uchun BIR MARTA belgilangan — ikkita
    turli task (biri oddiy `weather.now`, ikkinchisi murakkab `github.write`
    reasoning) BIR XIL agent orqali bajarilsa ham, ular haqiqatda TURLI
    reasoning chuqurligi talab qilishi mumkin. Chaqiruvchi (masalan
    `TaskGraphExecutor`, `core.model_routing.BrainModelRouter` orqali)
    har bitta vazifa uchun ALOHIDA, kontent-asoslangan qaror bera oladi.
    Berilmasa (default `None`) — eski xatti-harakat (agent tier) o'zgarmaydi.

    Raises:
        AgentUnavailableError: agent mavjud emas yoki ACTIVE emas.
        TimeoutError: `timeout_s` ichida tugamasa.
    """
    try:
        state = agent_registry.get_active(agent_name)
    except (AgentNotFoundError, AgentNotActiveError) as exc:
        raise AgentUnavailableError(str(exc)) from exc

    if task_class_override is not None:
        model = task_class_override.value
    elif provider:
        model = task_class_for_tier(state.spec.model_policy).value
    else:
        model = "fake"

    runtime = AgentRuntime(
        provider=provider or FakeProvider(),
        tool_registry=tool_registry,
        permission_policy=permission_policy,
        model=model,
        killswitch=killswitch,
    )
    coro = runtime.run(state.spec, command)
    result = await (asyncio.wait_for(coro, timeout=timeout_s) if timeout_s else coro)

    agent_registry.record_run(
        agent_name, success=result.success, tool_calls=result.tool_calls_count
    )
    return result


class WorkflowExecutor:
    """Workflow zanjirini boshidan oxirigacha bajaradi (`WorkflowRunner` + `AgentRuntime`).

    Har bir qadam natijasi (`output`) keyingi qadamning `{prev_output}`
    o'rniga qo'yiladi — `workflow.py`dagi `WorkflowStep.command_template`
    hujjatlashtirilgan shartnomasi.
    """

    def __init__(
        self,
        *,
        workflows: WorkflowRunner,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy,
        provider: LLMProvider | None = None,
    ) -> None:
        self._workflows = workflows
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._provider = provider

    async def run_to_completion(self, workflow_id: str) -> WorkflowChain:
        """Workflow'ni oxirigacha bajaradi — COMPLETED yoki FAILED holatida qaytaradi.

        Raises:
            ValueError: workflow topilmadi.
        """
        chain = self._workflows.get(workflow_id)
        if chain is None:
            msg = f"Workflow topilmadi: {workflow_id}"
            raise ValueError(msg)

        if chain.status == WorkflowStatus.PENDING:
            started = self._workflows.start(workflow_id)
            if started is None:  # pragma: no cover — start() faqat PENDING'da None qaytaradi
                msg = f"Workflow boshlanmadi: {workflow_id}"
                raise ValueError(msg)
            chain = started

        prev_output = ""
        while chain.status == WorkflowStatus.RUNNING:
            index = chain.current_step_index
            if index is None:  # pragma: no cover — RUNNING holatda har doim mavjud
                break
            step = chain.steps[index]

            if step.require_approval:
                log.warning(
                    "workflow.approval_required",
                    workflow_id=workflow_id,
                    step=index,
                )
                updated = self._workflows.fail_step(
                    workflow_id,
                    index,
                    error="Bu qadam tasdiq talab qiladi — avtomatik ijrochi buni bajara "
                    "olmaydi (V-32). /api/v1/run orqali tasdiq bilan bajaring.",
                )
                chain = updated if updated is not None else chain
                break

            command = step.command_template.replace("{prev_output}", prev_output)
            try:
                result = await run_agent_command(
                    step.agent_name,
                    command,
                    agent_registry=self._agent_registry,
                    tool_registry=self._tool_registry,
                    permission_policy=self._permission_policy,
                    timeout_s=step.timeout_s,
                    provider=self._provider,
                )
            except AgentUnavailableError as exc:
                updated = self._workflows.fail_step(workflow_id, index, error=str(exc))
                chain = updated if updated is not None else chain
                break
            except TimeoutError:
                updated = self._workflows.fail_step(
                    workflow_id, index, error="vaqt tugadi (timeout)"
                )
                chain = updated if updated is not None else chain
                break

            if not result.success:
                updated = self._workflows.fail_step(
                    workflow_id, index, error=result.error or "agent muvaffaqiyatsiz"
                )
                chain = updated if updated is not None else chain
                break

            prev_output = result.output
            updated = self._workflows.complete_step(workflow_id, index, output=result.output)
            if updated is None:  # pragma: no cover
                break
            chain = updated

        return chain


__all__ = ["AgentUnavailableError", "WorkflowExecutor", "run_agent_command"]
