"""Automation Engine endpoint'lari (Bo'lim 9).

    POST   /api/v1/automation/schedules              — jadval qoidasi yaratish
    GET    /api/v1/automation/schedules               — jadval qoidalari ro'yxati
    POST   /api/v1/automation/schedules/{id}/pause     — to'xtatish
    POST   /api/v1/automation/schedules/{id}/resume    — qayta boshlash
    DELETE /api/v1/automation/schedules/{id}           — o'chirish

    POST   /api/v1/automation/triggers                — trigger yaratish
    GET    /api/v1/automation/triggers                 — triggerlar ro'yxati
    DELETE /api/v1/automation/triggers/{id}            — o'chirish

    POST   /api/v1/automation/workflows                — workflow zanjiri yaratish
    GET    /api/v1/automation/workflows                 — workflowlar ro'yxati
    GET    /api/v1/automation/workflows/{id}            — bitta workflow
    POST   /api/v1/automation/workflows/{id}/run        — oxirigacha bajarish

    POST   /api/v1/automation/events                  — hodisa yuborish (mos
                                                          triggerlarni haqiqatan bajaradi)
    GET    /api/v1/automation/stats                    — umumiy statistika

Ilgari `AutomationEngine`/`WorkflowRunner`/`Scheduler` faqat ma'lumot
modeli edi — hech qanday API route yoki kod ularni ishlatmasdi
(gap-analysis: "wired to nothing"). Endi shu route'lar orqali haqiqiy
`AgentRuntime` bilan bog'langan (`automation/executor.py`).

Bog'liq qarorlar:
    Bo'lim 9 — avtomatlashtirish
    V-32 — majburiy tasdiq (workflow `require_approval` qadamlari
           avtomatik bajarilmaydi)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.agents.registry import AgentRegistry
from zet.api.deps import (
    get_agent_registry,
    get_automation_engine,
    get_model_router,
    get_permission_policy,
    get_tool_registry,
    get_workflow_executor,
)
from zet.automation.engine import AutomationEngine, AutomationEvent
from zet.automation.executor import AgentUnavailableError, WorkflowExecutor, run_agent_command
from zet.automation.scheduler import ScheduleRule, ScheduleStatus
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType
from zet.automation.workflow import WorkflowChain, WorkflowStatus, WorkflowStep
from zet.llm.routed_provider import RoutedLLMProvider
from zet.llm.router import ModelRouter
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/automation", tags=["automation"])


# ── Request modellari ────────────────────────────────────────────────


class ScheduleCreateRequest(BaseModel):
    """Yangi jadval qoidasi so'rovi."""

    name: str = Field(..., min_length=1, max_length=100)
    agent_name: str = Field(..., min_length=1)
    cron_expr: str = Field(..., min_length=1)
    command: str = ""
    max_runs: int | None = None


class TriggerConditionRequest(BaseModel):
    """Trigger sharti so'rovi."""

    field: str
    operator: str = "eq"
    value: str = ""


class TriggerCreateRequest(BaseModel):
    """Yangi trigger so'rovi."""

    name: str = Field(..., min_length=1, max_length=100)
    trigger_type: TriggerType
    agent_name: str = Field(..., min_length=1)
    conditions: list[TriggerConditionRequest] = Field(default_factory=list)
    command_template: str = ""
    max_fires: int | None = None
    cooldown_s: int = Field(default=0, ge=0)


class WorkflowStepRequest(BaseModel):
    """Workflow qadami so'rovi."""

    agent_name: str = Field(..., min_length=1)
    command_template: str = ""
    timeout_s: int = Field(default=120, ge=10, le=600)
    require_approval: bool = False


class WorkflowCreateRequest(BaseModel):
    """Yangi workflow so'rovi."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    steps: list[WorkflowStepRequest] = Field(..., min_length=1)


class AutomationEventRequest(BaseModel):
    """Hodisa yuborish so'rovi."""

    event_type: str = Field(..., min_length=1)
    source: str = ""
    data: dict[str, str] = Field(default_factory=dict)


class ActionResultResponse(BaseModel):
    """Bitta amal (trigger natijasida) bajarilish natijasi."""

    agent_name: str
    command: str
    trigger_id: str
    trigger_name: str
    success: bool
    output: str
    error: str | None = None


class AutomationEventResponse(BaseModel):
    """Hodisa qayta ishlash natijasi."""

    event_type: str
    actions: list[ActionResultResponse]


# ── Jadvallar (Scheduler) ──────────────────────────────────────────


@router.post("/schedules", response_model=ScheduleRule, status_code=201)
def create_schedule(
    request: ScheduleCreateRequest,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> ScheduleRule:
    """Yangi jadval qoidasi qo'shish (cron)."""
    try:
        return engine.add_schedule(
            ScheduleRule(
                name=request.name,
                agent_name=request.agent_name,
                cron_expr=request.cron_expr,
                command=request.command,
                max_runs=request.max_runs,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/schedules", response_model=list[ScheduleRule])
def list_schedules(
    status: ScheduleStatus | None = None,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> list[ScheduleRule]:
    """Jadval qoidalari ro'yxati."""
    return engine.scheduler.list_rules(status=status)


@router.post("/schedules/{schedule_id}/pause", response_model=ScheduleRule)
def pause_schedule(
    schedule_id: str,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> ScheduleRule:
    """Jadval qoidasini to'xtatish."""
    rule = engine.scheduler.pause_rule(schedule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Jadval qoidasi topilmadi")
    return rule


@router.post("/schedules/{schedule_id}/resume", response_model=ScheduleRule)
def resume_schedule(
    schedule_id: str,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> ScheduleRule:
    """Jadval qoidasini qayta boshlash."""
    rule = engine.scheduler.resume_rule(schedule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Jadval qoidasi topilmadi")
    return rule


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> None:
    """Jadval qoidasini o'chirish."""
    if not engine.scheduler.remove_rule(schedule_id):
        raise HTTPException(status_code=404, detail="Jadval qoidasi topilmadi")


# ── Triggerlar ────────────────────────────────────────────────────


@router.post("/triggers", response_model=EventTrigger, status_code=201)
def create_trigger(
    request: TriggerCreateRequest,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> EventTrigger:
    """Yangi hodisaga asoslangan trigger qo'shish."""
    return engine.add_trigger(
        EventTrigger(
            name=request.name,
            trigger_type=request.trigger_type,
            agent_name=request.agent_name,
            conditions=[
                TriggerCondition(field=c.field, operator=c.operator, value=c.value)
                for c in request.conditions
            ],
            command_template=request.command_template,
            max_fires=request.max_fires,
            cooldown_s=request.cooldown_s,
        )
    )


@router.get("/triggers", response_model=list[EventTrigger])
def list_triggers(
    trigger_type: TriggerType | None = None,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> list[EventTrigger]:
    """Triggerlar ro'yxati."""
    return engine.triggers.list_triggers(trigger_type=trigger_type)


@router.delete("/triggers/{trigger_id}", status_code=204)
def delete_trigger(
    trigger_id: str,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> None:
    """Triggerni o'chirish."""
    if not engine.triggers.remove(trigger_id):
        raise HTTPException(status_code=404, detail="Trigger topilmadi")


# ── Workflowlar ───────────────────────────────────────────────────


@router.post("/workflows", response_model=WorkflowChain, status_code=201)
def create_workflow(
    request: WorkflowCreateRequest,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> WorkflowChain:
    """Yangi workflow zanjiri yaratish (hali boshlanmagan, PENDING)."""
    try:
        return engine.create_workflow(
            name=request.name,
            description=request.description,
            steps=[
                WorkflowStep(
                    agent_name=s.agent_name,
                    command_template=s.command_template,
                    timeout_s=s.timeout_s,
                    require_approval=s.require_approval,
                )
                for s in request.steps
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workflows", response_model=list[WorkflowChain])
def list_workflows(
    status: WorkflowStatus | None = None,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> list[WorkflowChain]:
    """Workflowlar ro'yxati."""
    return engine.workflows.list_workflows(status=status)


@router.get("/workflows/{workflow_id}", response_model=WorkflowChain)
def get_workflow(
    workflow_id: str,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> WorkflowChain:
    """Bitta workflow ma'lumotlari."""
    chain = engine.workflows.get(workflow_id)
    if chain is None:
        raise HTTPException(status_code=404, detail="Workflow topilmadi")
    return chain


@router.post("/workflows/{workflow_id}/run", response_model=WorkflowChain)
async def run_workflow(
    workflow_id: str,
    executor: WorkflowExecutor = Depends(get_workflow_executor),
) -> WorkflowChain:
    """Workflow'ni oxirigacha (barcha qadamlarni) bajarish.

    `require_approval=True` qadamlarda avtomatik to'xtaydi (V-32) —
    natija FAILED holatida, sababi tushuntirilgan holda qaytadi.
    """
    try:
        return await executor.run_to_completion(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Hodisalar (events) ────────────────────────────────────────────


@router.post("/events", response_model=AutomationEventResponse)
async def submit_event(
    request: AutomationEventRequest,
    engine: AutomationEngine = Depends(get_automation_engine),
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    router: ModelRouter = Depends(get_model_router),
) -> AutomationEventResponse:
    """Hodisa yuborish — mos triggerlarni topadi va HAQIQATDA bajaradi.

    Har bir mos trigger uchun agent haqiqiy `AgentRuntime` orqali (real
    `ModelRouter` bilan) ishga tushiriladi (sinxron — javobda barcha
    natijalar bilan).
    """
    event = AutomationEvent(
        event_type=request.event_type,
        source=request.source,
        data=request.data,
    )
    actions = engine.process_event(event)
    provider = RoutedLLMProvider(router)

    results: list[ActionResultResponse] = []
    for action in actions:
        try:
            run_result = await run_agent_command(
                action.agent_name,
                action.command,
                agent_registry=agent_registry,
                tool_registry=tool_registry,
                permission_policy=permission_policy,
                provider=provider,
            )
            results.append(
                ActionResultResponse(
                    agent_name=action.agent_name,
                    command=action.command,
                    trigger_id=action.trigger_id,
                    trigger_name=action.trigger_name,
                    success=run_result.success,
                    output=run_result.output,
                    error=run_result.error,
                )
            )
        except AgentUnavailableError as exc:
            results.append(
                ActionResultResponse(
                    agent_name=action.agent_name,
                    command=action.command,
                    trigger_id=action.trigger_id,
                    trigger_name=action.trigger_name,
                    success=False,
                    output="",
                    error=str(exc),
                )
            )

    return AutomationEventResponse(event_type=request.event_type, actions=results)


@router.get("/stats")
def get_stats(
    engine: AutomationEngine = Depends(get_automation_engine),
) -> dict[str, dict[str, int]]:
    """Umumiy statistika (jadvallar, triggerlar, workflowlar, hodisalar)."""
    return engine.stats
