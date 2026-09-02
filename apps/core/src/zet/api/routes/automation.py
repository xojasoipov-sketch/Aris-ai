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

    GET    /api/v1/automation/recipes                  — 6 TIZIM retsepti + HALOL holat
    GET    /api/v1/automation/recipes/{code}            — bitta retsept
    POST   /api/v1/automation/recipes/{code}/install    — tayyorini o'rnatish

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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.agents.registry import AgentRegistry
from zet.api.deps import (
    get_agent_registry,
    get_automation_engine,
    get_config,
    get_goal_registry,
    get_killswitch,
    get_model_router,
    get_permission_policy,
    get_tool_registry,
    get_workflow_executor,
)
from zet.automation.autonomy import AutonomyLevel, AutonomyViolationError
from zet.automation.engine import AutomationAction, AutomationEngine, AutomationEvent
from zet.automation.executor import AgentUnavailableError, WorkflowExecutor, run_agent_command
from zet.automation.goal import Goal, GoalPursuit, GoalRegistry, GoalStatus
from zet.automation.persistence import persist_automation
from zet.automation.recipes import (
    RECIPES,
    Capability,
    Recipe,
    RecipeNotReadyError,
    RecipeReadiness,
    RecipeStatus,
    TriggerKind,
    detect_capabilities,
    evaluate,
    get_recipe,
    install,
)
from zet.automation.scheduler import ScheduleRule, ScheduleStatus
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType
from zet.automation.watcher import WatchComparison, WatchRule
from zet.automation.workflow import WorkflowChain, WorkflowStatus, WorkflowStep
from zet.config import Settings, get_settings
from zet.llm.routed_provider import RoutedLLMProvider
from zet.llm.router import ModelRouter
from zet.security.killswitch import KillSwitchState
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


# ── Holatni saqlash ────────────────────────────────────────────────


def _persist(background: BackgroundTasks, engine: AutomationEngine) -> None:
    """Dvigatel holatini bazaga yozishni navbatga qo'yadi.

    `BackgroundTasks` — javob YUBORILGANDAN KEYIN ishlaydi. Bu ataylab:
    saqlash yiqilsa ham ega qo'shgan qoida XOTIRADA ishlab turaveradi va
    so'rov 500 bo'lmaydi. Yagona yo'qotish — qayta ishga tushishdan omon
    qolmaslik, va u log'da ko'rinadi (`automation.persist_failed`).
    """
    from zet.api.deps import get_session_factory

    background.add_task(
        persist_automation,
        engine,
        get_session_factory(),
        owner_external_id=get_settings().owner_id,
    )


# ── Jadvallar (Scheduler) ──────────────────────────────────────────


@router.post("/schedules", response_model=ScheduleRule, status_code=201)
def create_schedule(
    request: ScheduleCreateRequest,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> ScheduleRule:
    """Yangi jadval qoidasi qo'shish (cron)."""
    try:
        rule = engine.add_schedule(
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
    _persist(background, engine)
    return rule


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
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> ScheduleRule:
    """Jadval qoidasini to'xtatish."""
    rule = engine.scheduler.pause_rule(schedule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Jadval qoidasi topilmadi")
    _persist(background, engine)
    return rule


@router.post("/schedules/{schedule_id}/resume", response_model=ScheduleRule)
def resume_schedule(
    schedule_id: str,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> ScheduleRule:
    """Jadval qoidasini qayta boshlash."""
    rule = engine.scheduler.resume_rule(schedule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Jadval qoidasi topilmadi")
    _persist(background, engine)
    return rule


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> None:
    """Jadval qoidasini o'chirish."""
    if not engine.scheduler.remove_rule(schedule_id):
        raise HTTPException(status_code=404, detail="Jadval qoidasi topilmadi")
    _persist(background, engine)


# ── Triggerlar ────────────────────────────────────────────────────


@router.post("/triggers", response_model=EventTrigger, status_code=201)
def create_trigger(
    request: TriggerCreateRequest,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> EventTrigger:
    """Yangi hodisaga asoslangan trigger qo'shish."""
    trigger = engine.add_trigger(
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
    _persist(background, engine)
    return trigger


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
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> None:
    """Triggerni o'chirish."""
    if not engine.triggers.remove(trigger_id):
        raise HTTPException(status_code=404, detail="Trigger topilmadi")
    _persist(background, engine)


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

    results = [
        await _run_action(
            action,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=permission_policy,
            provider=provider,
        )
        for action in actions
    ]
    return AutomationEventResponse(event_type=request.event_type, actions=results)


async def _run_action(
    action: AutomationAction,
    *,
    agent_registry: AgentRegistry,
    tool_registry: ToolRegistry,
    permission_policy: PermissionPolicy,
    provider: RoutedLLMProvider,
) -> ActionResultResponse:
    """Bitta trigger amalini bajarish va natijani javob modeliga o'girish.

    Hodisa yo'li ham, watcher yo'li ham shu funksiyadan o'tadi — ikkalasi
    uchun alohida bajarish mantiqi yozilmaydi.
    """
    try:
        result = await run_agent_command(
            action.agent_name,
            action.command,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=permission_policy,
            provider=provider,
        )
    except AgentUnavailableError as exc:
        return ActionResultResponse(
            agent_name=action.agent_name,
            command=action.command,
            trigger_id=action.trigger_id,
            trigger_name=action.trigger_name,
            success=False,
            output="",
            error=str(exc),
        )

    return ActionResultResponse(
        agent_name=action.agent_name,
        command=action.command,
        trigger_id=action.trigger_id,
        trigger_name=action.trigger_name,
        success=result.success,
        output=result.output,
        error=result.error,
    )


@router.get("/stats")
def get_stats(
    engine: AutomationEngine = Depends(get_automation_engine),
) -> dict[str, dict[str, int]]:
    """Umumiy statistika (jadvallar, triggerlar, workflowlar, hodisalar)."""
    return engine.stats


# ── Kuzatuv qoidalari (3-xususiyat) ───────────────────────────────


class WatchCreateRequest(BaseModel):
    """Yangi kuzatuv qoidasi so'rovi."""

    name: str = Field(..., min_length=1, max_length=100)
    metric: str = Field(..., min_length=1, max_length=120)
    comparison: WatchComparison = WatchComparison.CHANGED
    threshold: float = 0.0
    cooldown_s: int = Field(default=300, ge=0)
    max_fires: int | None = None


class WatchFiredResponse(BaseModel):
    """Signal bergan bitta qoida."""

    rule_id: str
    rule_name: str
    metric: str
    value: str
    previous: str
    direction: str


class WatchPollResponse(BaseModel):
    """Qo'lda o'lchash natijasi.

    `fired` va `actions` BIR XIL SON EMAS: qoida signal berishi mumkin-u,
    unga ulangan trigger bo'lmasa hech qanday agent ishga tushmaydi.
    Shu sabab ikkalasi alohida ko'rsatiladi — aks holda triggersiz qoida
    "kuzatuv ishlamadi" degan taassurot berardi.
    """

    fired: list[WatchFiredResponse]
    """Signal bergan kuzatuv qoidalari."""

    actions: list[ActionResultResponse]
    """Signalga ULANGAN triggerlar ishga tushirgan agentlar."""


@router.get("/metrics", response_model=list[str])
def list_metrics(
    engine: AutomationEngine = Depends(get_automation_engine),
) -> list[str]:
    """Kuzatish mumkin bo'lgan metrikalar ro'yxati.

    Kuzatuv qoidasi yozishdan oldin shu ro'yxatga qaraladi — mavjud
    bo'lmagan metrika uchun qoida jimgina hech qachon ishlamasdi.
    """
    return engine.metrics.known


@router.post("/watchers", response_model=WatchRule, status_code=201)
def create_watcher(
    request: WatchCreateRequest,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> WatchRule:
    """Yangi kuzatuv qoidasi (metrika o'zgarganda uyg'onadi).

    Metrika ro'yxatdan o'tmagan bo'lsa — 422. Jimgina hech qachon
    ishlamaydigan qoida yaratilmaydi.
    """
    if request.metric not in engine.metrics.known:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{request.metric}' metrikasi yo'q. "
                f"Mavjudlari: {', '.join(engine.metrics.known) or '(hech qanday)'}"
            ),
        )
    rule = engine.add_watch(
        WatchRule(
            name=request.name,
            metric=request.metric,
            comparison=request.comparison,
            threshold=request.threshold,
            cooldown_s=request.cooldown_s,
            max_fires=request.max_fires,
        )
    )
    _persist(background, engine)
    return rule


@router.get("/watchers", response_model=list[WatchRule])
def list_watchers(
    metric: str | None = None,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> list[WatchRule]:
    """Kuzatuv qoidalari ro'yxati."""
    return engine.watchers.list_rules(metric=metric)


@router.delete("/watchers/{rule_id}", status_code=204)
def delete_watcher(
    rule_id: str,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
) -> None:
    """Kuzatuv qoidasini o'chirish."""
    if not engine.watchers.remove(rule_id):
        raise HTTPException(status_code=404, detail="Kuzatuv qoidasi topilmadi")
    _persist(background, engine)


@router.post("/watchers/poll", response_model=WatchPollResponse)
async def poll_watchers(
    engine: AutomationEngine = Depends(get_automation_engine),
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    model_router: ModelRouter = Depends(get_model_router),
) -> WatchPollResponse:
    """Barcha kuzatuv qoidalarini HOZIR o'lchash va signal berganlarini bajarish.

    Fon daemon buni o'zi qiladi; bu endpoint sinash va darhol tekshirish
    uchun. Birinchi chaqiruv odatda hech narsa qaytarmaydi — u faqat
    baza qiymatlarni o'rnatadi.
    """
    poll = await engine.poll_watchers()
    provider = RoutedLLMProvider(model_router)

    results = [
        await _run_action(
            action,
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=permission_policy,
            provider=provider,
        )
        for action in poll.actions
    ]

    return WatchPollResponse(
        fired=[
            WatchFiredResponse(
                rule_id=event.data.get("watch_rule_id", ""),
                rule_name=event.data.get("watch_rule_name", ""),
                metric=event.data.get("metric", ""),
                value=event.data.get("value", ""),
                previous=event.data.get("previous", ""),
                direction=event.data.get("direction", ""),
            )
            for event in poll.events
        ],
        actions=results,
    )


# ── Maqsadlar (5-xususiyat, L4) ───────────────────────────────────


class GoalCreateRequest(BaseModel):
    """Yangi maqsad so'rovi — NATIJA aytiladi, yo'l aytilmaydi."""

    name: str = Field(..., min_length=1, max_length=100)
    outcome: str = Field(..., min_length=1, max_length=2000)
    agent_name: str = Field(..., min_length=1)
    success_criteria: str = Field(default="", max_length=2000)
    evaluator_agent: str = ""
    autonomy_level: AutonomyLevel = AutonomyLevel.L3_AGENT


@router.post("/goals", response_model=Goal, status_code=201)
def create_goal(
    request: GoalCreateRequest,
    goals: GoalRegistry = Depends(get_goal_registry),
) -> Goal:
    """Yangi maqsad yaratish (hali quvilmagan, PENDING)."""
    return goals.add(
        Goal(
            name=request.name,
            outcome=request.outcome,
            agent_name=request.agent_name,
            success_criteria=request.success_criteria,
            evaluator_agent=request.evaluator_agent,
            autonomy_level=request.autonomy_level,
        )
    )


@router.get("/goals", response_model=list[Goal])
def list_goals(
    status: GoalStatus | None = None,
    goals: GoalRegistry = Depends(get_goal_registry),
) -> list[Goal]:
    """Maqsadlar ro'yxati."""
    return goals.list_goals(status=status)


@router.get("/goals/{goal_id}", response_model=Goal)
def get_goal(
    goal_id: str,
    goals: GoalRegistry = Depends(get_goal_registry),
) -> Goal:
    """Bitta maqsad — barcha urinishlar tarixi bilan."""
    goal = goals.get(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Maqsad topilmadi")
    return goal


@router.post("/goals/{goal_id}/pursue", response_model=Goal)
async def pursue_goal(
    goal_id: str,
    goals: GoalRegistry = Depends(get_goal_registry),
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    killswitch: KillSwitchState = Depends(get_killswitch),
    model_router: ModelRouter = Depends(get_model_router),
) -> Goal:
    """Maqsadni yetgunicha (yoki urinishlar tugagunicha) quvish.

    Urinishlar soni AVTONOMIYA DARAJASIDAN: L3 = 1, L4 = 5.
    L0-L2 maqsad tsikliga umuman ruxsat bermaydi (409).
    """
    goal = goals.get(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Maqsad topilmadi")

    pursuit = GoalPursuit(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        permission_policy=permission_policy,
        killswitch=killswitch,
        provider=RoutedLLMProvider(model_router, is_autonomous=True),
    )
    try:
        finished = await pursuit.pursue(goal)
    except AutonomyViolationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return goals.save(finished)


# ── TIZIM retseptlari (yangi zip) ─────────────────────────────────


class RecipeDetailResponse(BaseModel):
    """Retsept + uning HAQIQIY tayyorlik holati."""

    code: str
    name: str
    promise: str
    trigger_kind: TriggerKind
    trigger_spec: str
    also_at: list[str] = []
    """Qo'shimcha ishga tushish vaqtlari (T06 kuniga ikki marta ishlaydi).

    Bo'sh ro'yxat — retsept faqat `trigger_spec` bo'yicha ishlaydi. Ega
    interfeysda "09:20" ni ko'rib, kechqurun ham hisobot kelganda buni
    kutilmagan deb o'ylamasligi uchun kerak."""

    result: str
    steps: list[dict[str, str]]
    status: RecipeStatus
    missing: list[Capability]
    blocked_steps: list[int]


class RecipeInstallResponse(BaseModel):
    """O'rnatish natijasi."""

    code: str
    installed_id: str
    kind: TriggerKind


def _detail(recipe: Recipe, readiness: RecipeReadiness) -> RecipeDetailResponse:
    return RecipeDetailResponse(
        code=recipe.code,
        name=recipe.name,
        promise=recipe.promise,
        trigger_kind=recipe.trigger_kind,
        trigger_spec=recipe.trigger_spec,
        also_at=list(recipe.also_at),
        result=recipe.result,
        steps=[
            {"order": str(s.order), "title": s.title, "agent_name": s.agent_name}
            for s in recipe.steps
        ],
        status=readiness.status,
        missing=readiness.missing,
        blocked_steps=readiness.blocked_steps,
    )


@router.get("/recipes", response_model=list[RecipeDetailResponse])
def list_recipes(
    settings: Settings = Depends(get_config),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> list[RecipeDetailResponse]:
    """Oltita TIZIM retsepti va ularning HALOL holati.

    Imkoniyati yetishmagan retsept "ready" deb ko'rsatilmaydi — aynan
    qaysi imkoniyat yo'qligi `missing` da qaytadi.
    """
    available = detect_capabilities(settings, tool_registry)
    return [_detail(recipe, evaluate(recipe, available)) for recipe in RECIPES]


@router.get("/recipes/{code}", response_model=RecipeDetailResponse)
def get_recipe_detail(
    code: str,
    settings: Settings = Depends(get_config),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> RecipeDetailResponse:
    """Bitta retsept tafsiloti."""
    recipe = get_recipe(code)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    available = detect_capabilities(settings, tool_registry)
    return _detail(recipe, evaluate(recipe, available))


@router.post("/recipes/{code}/install", response_model=RecipeInstallResponse, status_code=201)
def install_recipe(
    code: str,
    background: BackgroundTasks,
    engine: AutomationEngine = Depends(get_automation_engine),
    settings: Settings = Depends(get_config),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> RecipeInstallResponse:
    """Tayyor retseptni o'rnatish (jadval yoki trigger sifatida).

    Imkoniyati yetishmasa — 409, sababi bilan. Chala ishlaydigan
    avtomatlashtirish o'rnatilmaydi.
    """
    recipe = get_recipe(code)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")

    available = detect_capabilities(settings, tool_registry)
    try:
        installed_id = install(recipe, engine, available)
    except RecipeNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Yoqilgan retsept qayta ishga tushishdan omon qolishi SHART: ega
    # "Yoqilgan" yozuvini ko'rib, hisobot kelishini kutib qoladi.
    _persist(background, engine)

    return RecipeInstallResponse(
        code=recipe.code,
        installed_id=installed_id,
        kind=recipe.trigger_kind,
    )
