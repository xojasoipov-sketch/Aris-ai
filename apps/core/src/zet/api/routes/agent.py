"""Agent API endpoint'lari (Bo'lim 3-4).

Agent CRUD, lifecycle, run va factory:
    POST   /api/v1/agents           — yangi agent ro'yxatga olish
    GET    /api/v1/agents           — agentlar ro'yxati
    GET    /api/v1/agents/{name}    — agent ma'lumotlari
    PATCH  /api/v1/agents/{name}/status — holat o'zgartirish (V-11)
    POST   /api/v1/agents/{name}/run    — agentni ishga tushirish
    POST   /api/v1/agents/factory   — tabiy tildan agent yaratish (V-10)

Bog'liq qarorlar:
    A-02 — agent = ma'lumot
    V-10 — Agent Factory oqimi
    V-11 — lifecycle avtomati
    A-07 — tormozlar
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.agents.lifecycle import AgentLifecycle, AgentLifecycleError
from zet.agents.registry import (
    AgentNotActiveError,
    AgentNotFoundError,
    AgentRegistry,
)
from zet.agents.runtime import AgentRuntime
from zet.api.deps import get_agent_registry, get_permission_policy, get_tool_registry
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, TrustLevel
from zet.llm.fake import FakeProvider
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Request / Response modellari ──────────────────────────────────


class AgentCreateRequest(BaseModel):
    """Yangi agent yaratish so'rovi."""

    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=500)
    system_prompt: str = Field(..., min_length=1)
    division: str = Field(default="general", max_length=64)
    role: str = Field(default="assistant", max_length=64)
    goal: str = Field(default="", max_length=1000)
    tool_allowlist: list[str] = Field(default_factory=list)
    model_policy: ModelTier = ModelTier.T1_FREE
    permission_level: PermissionLevel = PermissionLevel.READ
    trust_level: TrustLevel = TrustLevel.SYSTEM
    max_steps: int = Field(default=10, ge=1, le=50)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    timeout_s: int = Field(default=120, ge=10, le=600)


class AgentStatusUpdateRequest(BaseModel):
    """Holat o'zgartirish so'rovi."""

    action: str = Field(
        ...,
        description="Lifecycle amal: activate, start_testing, pause, disable, archive, reset_to_draft",
    )
    reason: str = Field(default="", description="Sabab (disable uchun)")


class AgentRunRequest(BaseModel):
    """Agent run so'rovi."""

    task: str = Field(..., min_length=1, max_length=10_000)


class AgentResponse(BaseModel):
    """Agent javobi."""

    name: str
    description: str
    division: str
    role: str
    goal: str
    status: str
    model_policy: str
    permission_level: str
    trust_level: str
    tool_allowlist: list[str]
    max_steps: int
    max_tool_calls: int
    timeout_s: int
    version: int
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    total_tool_calls: int


class AgentRunResponse(BaseModel):
    """Agent run natijasi javobi."""

    agent_name: str
    success: bool
    output: str
    sources: list[str]
    tool_calls_count: int
    steps_count: int
    error: str | None = None


class FactoryCreateRequest(BaseModel):
    """Factory: tabiy til bilan agent yaratish so'rovi (V-10)."""

    description: str = Field(..., min_length=5, max_length=2000)
    auto_activate: bool = False


class EvalCaseResponse(BaseModel):
    """Eval holat natijasi."""

    name: str
    description: str
    passed: bool
    error: str | None = None


class EvalResultResponse(BaseModel):
    """Eval natijasi javobi."""

    agent_name: str
    total: int
    passed: int
    failed: int
    success: bool
    cases: list[EvalCaseResponse]


class FactoryCreateResponse(BaseModel):
    """Factory natijasi javobi."""

    success: bool
    agent: AgentResponse | None = None
    eval_result: EvalResultResponse | None = None
    steps: list[str]
    error: str | None = None


# ── Yordamchi ─────────────────────────────────────────────────────


def _state_to_response(state: object) -> AgentResponse:
    """AgentState ni response ga o'girish."""
    from zet.domain.agent import AgentState

    if not isinstance(state, AgentState):  # pragma: no cover
        msg = f"AgentState kutildi, {type(state).__name__} keldi"
        raise TypeError(msg)
    return AgentResponse(
        name=state.spec.name,
        description=state.spec.description,
        division=state.spec.division,
        role=state.spec.role,
        goal=state.spec.goal,
        status=state.status.value,
        model_policy=state.spec.model_policy.value,
        permission_level=state.spec.permission_level.value,
        trust_level=state.spec.trust_level.value,
        tool_allowlist=list(state.spec.tool_allowlist),
        max_steps=state.spec.max_steps,
        max_tool_calls=state.spec.max_tool_calls,
        timeout_s=state.spec.timeout_s,
        version=state.spec.version,
        total_runs=state.total_runs,
        successful_runs=state.successful_runs,
        failed_runs=state.failed_runs,
        success_rate=state.success_rate,
        total_tool_calls=state.total_tool_calls,
    )


def _get_lifecycle(
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentLifecycle:
    """AgentLifecycle dependency."""
    return AgentLifecycle(registry)


# ── Endpoint'lar ──────────────────────────────────────────────────


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    request: AgentCreateRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentResponse:
    """Yangi agent ro'yxatga olish."""
    from zet.domain.agent import AgentSpec

    try:
        spec = AgentSpec(
            name=request.name,
            description=request.description,
            system_prompt=request.system_prompt,
            division=request.division,
            role=request.role,
            goal=request.goal,
            tool_allowlist=request.tool_allowlist,
            model_policy=request.model_policy,
            permission_level=request.permission_level,
            trust_level=request.trust_level,
            max_steps=request.max_steps,
            max_tool_calls=request.max_tool_calls,
            timeout_s=request.timeout_s,
        )
        state = registry.register(spec)
        return _state_to_response(state)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/factory", response_model=FactoryCreateResponse, status_code=201)
async def factory_create_agent(
    request: FactoryCreateRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> FactoryCreateResponse:
    """Tabiy til buyrug'i bilan agent yaratish (V-10 Factory).

    Oqim: UNDERSTAND → CHECK EXISTING → DESIGN → TOOLS → PERMISSIONS
    → PROMPT → REGISTER → TESTING → EVAL → (ixtiyoriy ACTIVATE)
    """
    from zet.agents.eval import EvalRunner
    from zet.agents.factory import AgentFactory, FactoryRequest

    lifecycle = AgentLifecycle(registry)
    factory = AgentFactory(registry, lifecycle, EvalRunner())

    factory_request = FactoryRequest(
        description=request.description,
        auto_activate=request.auto_activate,
    )
    result = factory.create(factory_request)

    # Eval natijasini response ga o'girish
    eval_response = None
    if result.eval_result is not None:
        eval_response = EvalResultResponse(
            agent_name=result.eval_result.agent_name,
            total=result.eval_result.total,
            passed=result.eval_result.passed,
            failed=result.eval_result.failed,
            success=result.eval_result.success,
            cases=[
                EvalCaseResponse(
                    name=c.name,
                    description=c.description,
                    passed=c.passed,
                    error=c.error,
                )
                for c in result.eval_result.cases
            ],
        )

    agent_response = _state_to_response(result.agent_state) if result.agent_state else None

    return FactoryCreateResponse(
        success=result.success,
        agent=agent_response,
        eval_result=eval_response,
        steps=list(result.steps),
        error=result.error,
    )


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    status: AgentStatus | None = None,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> list[AgentResponse]:
    """Agentlar ro'yxati (ixtiyoriy status filtri)."""
    agents = registry.list_agents(status=status)
    return [_state_to_response(a) for a in agents]


@router.get("/{name}", response_model=AgentResponse)
async def get_agent(
    name: str,
    registry: AgentRegistry = Depends(get_agent_registry),
) -> AgentResponse:
    """Agent ma'lumotlari."""
    try:
        state = registry.get(name)
        return _state_to_response(state)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{name}/status", response_model=AgentResponse)
async def update_agent_status(
    name: str,
    request: AgentStatusUpdateRequest,
    lifecycle: AgentLifecycle = Depends(_get_lifecycle),
) -> AgentResponse:
    """Agent holatini o'zgartirish (V-11 lifecycle)."""
    action_map = {
        "activate": lifecycle.activate,
        "start_testing": lifecycle.start_testing,
        "pause": lifecycle.pause,
        "archive": lifecycle.archive,
        "reset_to_draft": lifecycle.reset_to_draft,
    }

    try:
        if request.action == "disable":
            state = lifecycle.disable(name, reason=request.reason)
        elif request.action in action_map:
            state = action_map[request.action](name)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Noto'g'ri amal: {request.action}. "
                f"Mumkin: {', '.join([*action_map, 'disable'])}",
            )
        return _state_to_response(state)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{name}/run", response_model=AgentRunResponse)
async def run_agent(
    name: str,
    request: AgentRunRequest,
    registry: AgentRegistry = Depends(get_agent_registry),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
) -> AgentRunResponse:
    """Agentni ishga tushirish.

    Faqat ACTIVE agentlar ishga tushirilishi mumkin (V-11).
    LLM hali FakeProvider bilan — real ModelRouter integratsiyasi
    (agent.model_policy → tier tanlash) keyingi bosqichda.
    """
    try:
        state = registry.get_active(name)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentNotActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    provider = FakeProvider()
    runtime = AgentRuntime(
        provider=provider,
        tool_registry=tool_registry,
        permission_policy=permission_policy,
    )

    result = await runtime.run(state.spec, request.task)

    # Metrikalarni yangilash
    registry.record_run(name, success=result.success, tool_calls=result.tool_calls_count)

    return AgentRunResponse(
        agent_name=result.agent_name,
        success=result.success,
        output=result.output,
        sources=list(result.sources),
        tool_calls_count=result.tool_calls_count,
        steps_count=result.steps_count,
        error=result.error,
    )
