"""Reja va tool shartnomasi (Z45.3).

NEGA BU TESTLAR BOR.

Ega prod'da video havolasini yubordi. ZET reja tuzdi, tasdiq so'radi,
tasdiqlangandan keyin esa API **HTTP 500** qaytardi:

    ToolValidationError: Tool 'video.learn' uchun noto'g'ri parametrlar:
    'url' is a required property

Ikki alohida kamchilik:

1. Planner'ga faqat tool NOMLARI berilardi ("time.now, video.learn, …"),
   lekin undan `tool_params`ni to'liq to'ldirish talab qilinardi. Model
   `video.learn` `url` talab qilishini bilishning imkoni yo'q edi.

2. `registry.execute` shartnoma xatosini ISTISNO qilib otadi, uni esa
   `Executor` ushlamasdi — istisno butun `execute_plan`dan chiqib
   ketib, 500 bo'lardi. Ega hech qanday tushuntirish ko'rmadi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from zet.core.executor import Executor
from zet.core.planner import Planner
from zet.domain.enums import PermissionLevel, StepStatus
from zet.domain.plan import Plan, PlanStep
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry, ToolSignature


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


class TestToolSignatures:
    """Planner tool imzosini ko'rishi kerak, faqat nomni emas."""

    def test_required_params_are_exposed(self, tool_registry: ToolRegistry) -> None:
        by_name = {spec.name: spec for spec in tool_registry.tool_signatures()}

        assert "url" in by_name["video.learn"].required
        assert "query" in by_name["memory.search"].required

    def test_optional_params_are_separated(self, tool_registry: ToolRegistry) -> None:
        spec = next(s for s in tool_registry.tool_signatures() if s.name == "memory.search")

        assert "limit" in spec.optional
        assert "limit" not in spec.required

    def test_render_shows_required_fields(self) -> None:
        spec = ToolSignature(
            name="video.learn",
            description="Videoni o'rganadi",
            required=["url"],
            optional=["language"],
        )
        rendered = spec.render()

        assert "video.learn" in rendered
        assert "majburiy: url" in rendered
        assert "ixtiyoriy: language" in rendered


class TestPlannerRejectsMissingRequiredParams:
    """Xato Executor'ga yetib bormasligi kerak — repair uni tuzatsin."""

    def _planner(self) -> Planner:
        return Planner(router=None)  # type: ignore[arg-type]

    def _plan_with(self, params: dict[str, Any]) -> Plan:
        return Plan(
            summary="reja",
            steps=[
                PlanStep(
                    position=0,
                    description="Videoni o'rgan",
                    tool_name="video.learn",
                    tool_params=params,
                    permission_required=PermissionLevel.READ,
                )
            ],
        )

    def _validate(self, plan: Plan, specs: list[ToolSignature]) -> list[str]:
        planner = self._planner()
        route_result = _FakeRoute(plan)
        _, errors = planner._extract_and_validate(
            route_result,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            [spec.name for spec in specs],
            specs,
        )
        return errors

    def test_missing_required_param_is_an_error(self, tool_registry: ToolRegistry) -> None:
        specs = list(tool_registry.tool_signatures())

        errors = self._validate(self._plan_with({}), specs)

        assert any("url" in e for e in errors)

    def test_complete_params_pass(self, tool_registry: ToolRegistry) -> None:
        specs = list(tool_registry.tool_signatures())

        errors = self._validate(self._plan_with({"url": "https://youtu.be/x"}), specs)

        assert errors == []

    def test_without_specs_nothing_is_checked(self, tool_registry: ToolRegistry) -> None:
        """Eski chaqiruvchilar (imzosiz) avvalgidek ishlaydi."""
        errors = self._validate(self._plan_with({}), [])

        assert errors == []


class _FakeRoute:
    """`RouteResult` o'rniga — `create_plan` chaqiruvini taqlid qiladi."""

    def __init__(self, plan: Plan) -> None:
        self.response = _FakeResponse(plan)


class _FakeResponse:
    def __init__(self, plan: Plan) -> None:
        self.tool_uses = [_FakeToolUse(plan)]


class _FakeToolUse:
    def __init__(self, plan: Plan) -> None:
        self.name = "create_plan"
        self.arguments = {
            "summary": plan.summary,
            "steps": [
                {
                    "position": s.position,
                    "description": s.description,
                    "tool_name": s.tool_name,
                    "tool_params": s.tool_params,
                    "permission_required": s.permission_required.value,
                }
                for s in plan.steps
            ],
        }


class TestContractErrorDoesNotCrashTheRun:
    """`ToolValidationError` yiqilgan qadam bo'lsin, 500 emas."""

    async def test_missing_param_becomes_a_failed_step(
        self, tool_registry: ToolRegistry
    ) -> None:
        plan = Plan(
            summary="reja",
            steps=[
                PlanStep(
                    position=0,
                    description="Videoni o'rgan",
                    tool_name="video.learn",
                    tool_params={},  # `url` yo'q
                    permission_required=PermissionLevel.READ,
                )
            ],
        )
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
        )

        ctx = await executor.execute_plan(plan)

        assert ctx.results[0].status == StepStatus.FAILED
        assert "url" in (ctx.results[0].error or "")

    async def test_contract_error_is_not_retried(self, tool_registry: ToolRegistry) -> None:
        """Qayta urinish bir xil xatoni beradi — vaqt va pul isrofi."""
        plan = Plan(
            summary="reja",
            steps=[
                PlanStep(
                    position=0,
                    description="Videoni o'rgan",
                    tool_name="video.learn",
                    tool_params={},
                    permission_required=PermissionLevel.READ,
                )
            ],
        )
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
        )

        ctx = await executor.execute_plan(plan)

        assert ctx.results[0].retries == 0
