"""Planner — Intent'dan executable Plan yaratadi (Z1.8).

Kirish: `Intent` (Z1.7 chiqishi)
Chiqish: `Plan` (tartiblangan qadamlar — DAG)

Ishlash tartibi:
    1. Intent asosida LLM'ga buyruq yuboriladi (tool_use orqali)
    2. LLM `create_plan` tool'ini chaqiradi
    3. Javob `Plan` Pydantic modeliga validatsiya qilinadi
    4. Validatsiya: DAG tekshiruvi, max_steps, mavjud toollar
    5. Agar noto'g'ri tool bo'lsa — 1 marta qayta urinadi (repair)
    6. Ikkinchi urinish ham muvaffaqiyatsiz — PlannerError

Bog'liq qarorlar:
    A-01 — reja bazaga saqlanadi
    A-07 — max_steps, max_depth chegaralari
    V-31 — har bir qadamda permission_required
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog

from zet.domain.command import Intent
from zet.domain.enums import PermissionLevel, TaskClass, TrustLevel
from zet.domain.plan import Plan, PlanStep, PlanValidationError
from zet.llm.base import ChatMessage, ToolSpec
from zet.llm.router import ModelRouter, RouteResult
from zet.prompts.planner import PLANNER_SYSTEM, PLANNER_TOOL_SCHEMA
from zet.tools.registry import ToolSignature

log = structlog.get_logger(__name__)

_MAX_REPAIR_ATTEMPTS = 1
"""Noto'g'ri reja bo'lsa, necha marta qayta urinish (repair)."""


class PlannerError(Exception):
    """Reja yaratishda xato."""


_MODALITY_CLASSES = frozenset({TaskClass.VISION, TaskClass.SPEECH})
"""Vazifa MAZMUNI rasm/ovoz bo'lgan sinflar."""


def _planning_task_class(task_class: TaskClass) -> TaskClass:
    """Reja tuzish uchun model sinfini tanlaydi.

    `vision`/`speech` — vazifaning MAZMUNI haqida, reja tuzish haqida
    emas. Planner prompti sof matn (`_build_user_prompt`), rasm yoki
    ovoz unga umuman kirmaydi; rasmni tool o'zi ko'radi.

    Ilgari bu sinf to'g'ridan-to'g'ri routerga uzatilardi va ega video
    havolasi yuborganda reja tuzish bosqichi yiqilardi:

        "Reja tuzib bo'lmadi: vision uchun provayder topilmadi —
         google:gemini-flash: RateLimitError; anthropic:haiku: sozlanmagan"

    Ya'ni ZET matn model bilan reja yozishi mumkin edi, lekin vision
    zanjiri bo'sh bo'lgani uchun butun buyruq yiqildi.
    """
    return TaskClass.NORMAL if task_class in _MODALITY_CLASSES else task_class


_PLAN_TOOL = ToolSpec(
    name="create_plan",
    description="Buyruqdan yaratilgan bajarish rejasi",
    input_schema=PLANNER_TOOL_SCHEMA,
)


class Planner:
    """Intent'dan Plan yaratuvchi modul.

    LLM `create_plan` tool'ini chaqiradi — shu orqali strukturalangan
    reja olinadi. Reja DAG tekshiruvidan va tool validatsiyasidan o'tadi.
    """

    def __init__(
        self,
        router: ModelRouter,
        *,
        max_steps: int = 20,
    ) -> None:
        self._router = router
        self._max_steps = max_steps

    async def plan(
        self,
        intent: Intent,
        *,
        available_tools: Sequence[str] = (),
        tool_specs: Sequence[ToolSignature] = (),
        task_class: TaskClass | None = None,
    ) -> Plan:
        """Intent'dan Plan yaratadi.

        Args:
            intent: strukturalangan niyat (Z1.7 chiqishi)
            available_tools: mavjud tool nomlari
            tool_specs: tool imzolari (nom + majburiy parametrlar). Berilsa,
                promptda nomlar o'rniga imzolar ko'rsatiladi va majburiy
                parametrlar tekshiriladi. Berilmasa — eski xatti-harakat.
            task_class: model tanlash uchun sinf (None → intent'dagi qiymat)

        Returns:
            Validatsiya qilingan Plan

        Raises:
            PlannerError: LLM reja yasa olmadi
        """
        effective_task_class = _planning_task_class(task_class or intent.task_class)
        if not available_tools and tool_specs:
            available_tools = [spec.name for spec in tool_specs]

        # Imzolar bo'lsa — nomlar emas, majburiy parametrlari bilan.
        # Faqat nom ko'rsatilganda model qaysi maydon kerakligini
        # taxmin qilardi va uni tushirib qoldirardi.
        if tool_specs:
            tools_str = "\n" + "\n".join(spec.render() for spec in tool_specs)
        elif available_tools:
            tools_str = ", ".join(available_tools)
        else:
            tools_str = "hech qanday tool mavjud emas"

        system = PLANNER_SYSTEM.format(
            max_steps=self._max_steps,
            available_tools=tools_str,
        )

        user_prompt = self._build_user_prompt(intent)
        messages = [ChatMessage(role="user", content=user_prompt)]

        for attempt in range(_MAX_REPAIR_ATTEMPTS + 1):
            route_result = await self._router.complete(
                task_class=effective_task_class,
                messages=messages,
                system=system,
                tools=[_PLAN_TOOL],
            )

            plan, errors = self._extract_and_validate(
                route_result, intent, available_tools, tool_specs
            )

            if plan is not None and not errors:
                log.info(
                    "planner.plan_created",
                    steps=len(plan.steps),
                    max_permission=plan.max_permission.value,
                    needs_approval=plan.needs_approval,
                    attempt=attempt,
                )
                return plan

            if attempt < _MAX_REPAIR_ATTEMPTS:
                repair_msg = self._build_repair_message(errors, plan)
                log.warning(
                    "planner.repair",
                    attempt=attempt,
                    errors=errors,
                )
                messages.append(ChatMessage(role="user", content=repair_msg))
            else:
                error_detail = "; ".join(errors) if errors else "create_plan tool chaqirilmadi"
                raise PlannerError(
                    f"Reja yaratib bo'lmadi ({_MAX_REPAIR_ATTEMPTS + 1} urinishdan keyin): {error_detail}"
                )

        # Shu yerga yetib kelmasligi kerak, lekin mypy uchun
        raise PlannerError("Reja yaratib bo'lmadi")  # pragma: no cover

    def _build_user_prompt(self, intent: Intent) -> str:
        """Intent asosida LLM uchun prompt yaratish."""
        parts = [f"BUYRUQ: {intent.original_text or intent.action}"]
        parts.append(f"HARAKAT: {intent.action}")

        if intent.objects:
            parts.append(f"OBYEKTLAR: {', '.join(intent.objects)}")
        if intent.constraints:
            parts.append(f"CHEKLOVLAR: {', '.join(intent.constraints)}")
        if intent.requires_tools:
            parts.append(f"KERAKLI TOOLLAR: {', '.join(intent.requires_tools)}")

        parts.append(f"SHOSHILINCHLIK: {intent.urgency}")
        parts.append(f"VAZIFA SINFI: {intent.task_class.value}")

        return "\n".join(parts)

    def _extract_and_validate(
        self,
        route_result: RouteResult,
        _intent: Intent,
        available_tools: Sequence[str],
        tool_specs: Sequence[ToolSignature] = (),
    ) -> tuple[Plan | None, list[str]]:
        """LLM javobidan Plan ajratadi va validatsiya qiladi.

        Returns:
            (plan, errors) — plan None bo'lsa tool chaqirilmagan,
            errors bo'sh bo'lsa validatsiya muvaffaqiyatli.
        """
        response = route_result.response
        errors: list[str] = []

        # Tool chaqiruvini qidirish
        raw_plan: dict[str, Any] | None = None
        for tu in response.tool_uses:
            if tu.name == "create_plan":
                raw_plan = tu.arguments
                break

        if raw_plan is None:
            return None, ["LLM create_plan tool'ini chaqirmadi"]

        # Plan Pydantic modeliga aylantirish
        try:
            plan = self._parse_raw_plan(raw_plan)
        except (PlanValidationError, ValueError) as exc:
            return None, [f"Reja validatsiyadan o'tmadi: {exc}"]

        # Max steps tekshiruvi
        if len(plan.steps) > self._max_steps:
            errors.append(
                f"Qadamlar soni ({len(plan.steps)}) maksimumdan ({self._max_steps}) oshib ketdi"
            )

        # Tool mavjudligi tekshiruvi
        if available_tools:
            tool_set = set(available_tools)
            for step in plan.steps:
                if step.tool_name and step.tool_name not in tool_set:
                    errors.append(
                        f"Qadam {step.position}: '{step.tool_name}' "
                        f"tool mavjud emas (mavjudlar: {', '.join(sorted(tool_set))})"
                    )

        # Majburiy parametrlar tekshiruvi.
        #
        # Ilgari bu yerda faqat tool NOMI tekshirilardi. Reja qabul
        # qilinar, so'ng Executor'da `ToolValidationError` otilardi va u
        # hech kim ushlamagani uchun HTTP 500 bo'lib chiqardi. Endi xato
        # shu yerda topiladi va repair urinishi uni to'g'rilay oladi.
        by_name = {spec.name: spec for spec in tool_specs}
        for step in plan.steps:
            spec = by_name.get(step.tool_name or "")
            if spec is None:
                continue
            missing = [key for key in spec.required if key not in (step.tool_params or {})]
            if missing:
                errors.append(
                    f"Qadam {step.position}: '{step.tool_name}' uchun majburiy "
                    f"parametr(lar) berilmagan: {', '.join(missing)}"
                )

        if errors:
            return plan, errors
        return plan, []

    def _parse_raw_plan(self, raw: dict[str, Any]) -> Plan:
        """LLM javobidagi xom dict'ni Plan'ga aylantiradi (xavfsiz default'lar bilan)."""
        raw_steps = raw.get("steps") or []

        steps: list[PlanStep] = []
        for i, raw_step in enumerate(raw_steps):
            # permission_required ni validatsiya
            raw_perm = raw_step.get("permission_required", "read")
            try:
                permission = PermissionLevel(raw_perm)
            except ValueError:
                permission = PermissionLevel.READ

            # trust_context ni validatsiya
            raw_trust = raw_step.get("trust_context", "owner")
            try:
                trust = TrustLevel(raw_trust)
            except ValueError:
                trust = TrustLevel.OWNER

            raw_params = raw_step.get("tool_params")
            tool_params = raw_params if isinstance(raw_params, dict) else {}

            steps.append(
                PlanStep(
                    position=int(raw_step.get("position", i)),
                    description=str(raw_step.get("description", f"Qadam {i}")),
                    tool_name=raw_step.get("tool_name"),
                    tool_params=tool_params,
                    permission_required=permission,
                    trust_context=trust,
                    expected_outcome=raw_step.get("expected_outcome"),
                    depends_on=[int(d) for d in (raw_step.get("depends_on") or [])],
                )
            )

        return Plan(
            summary=str(raw.get("summary", "Reja")),
            steps=steps,
            task_class=raw.get("task_class", "normal"),
            raw_llm_output=raw,
        )

    def _build_repair_message(self, errors: list[str], plan: Plan | None) -> str:
        """Repair urinishi uchun xato xabarini shakllantirish."""
        parts = ["Rejada quyidagi xatolar topildi:"]
        for error in errors:
            parts.append(f"  - {error}")
        parts.append("")
        parts.append("Iltimos, create_plan tool'ini qayta chaqiring va xatolarni to'g'rilang.")
        if plan is not None and any("tool mavjud emas" in e for e in errors):
            parts.append(
                "Faqat mavjud toollarni ishlating yoki `tool_name` maydonini "
                "umuman qo'shmang (fikrlash qadami)."
            )
        return "\n".join(parts)
