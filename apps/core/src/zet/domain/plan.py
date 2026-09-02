"""Reja va qadam domen modellari.

DB dagi `plan`/`step` jadvallaridan mustaqil — bu Planner chiqishi va
Executor kirishi uchun toza kontraktlar.

Bog'liq qarorlar:
    A-01 — davomli holat mashinasi
    A-05 — trust level chegaralari
    A-07 — avtomatlashtirish tormozlari (max_steps, max_depth)
    V-31 — permission darajalar
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from zet.domain.enums import PermissionLevel, TrustLevel


class PlanStep(BaseModel, frozen=True):
    """Rejaning bitta qadami.

    Planner har bir qadamga tool/permission/dependency belgilaydi;
    Executor shu asosda ishlaydi.
    """

    position: int = Field(ge=0)
    """Qadam tartibi (0 dan boshlanadi)."""

    description: str = Field(min_length=1)
    """Qadam tavsifi (masalan: "Hozirgi vaqtni olib, eslatma matnini shakllantir")."""

    tool_name: str | None = None
    """Ishlatiladigan tool (None — faqat LLM fikrlashi)."""

    tool_params: dict[str, Any] = Field(default_factory=dict)
    """`tool_name` uchun kirish parametrlari (tool'ning JSON Schema'siga mos)."""

    agent_name: str | None = None
    """Sub-agent nomi (agar qadam boshqa agentga topshirilsa)."""

    permission_required: PermissionLevel = PermissionLevel.READ
    """Bu qadam bajarilishi uchun kerakli ruxsat darajasi (V-31)."""

    trust_context: TrustLevel = TrustLevel.OWNER
    """Qadamning kirish konteksti qayerdan kelgani (A-05)."""

    expected_outcome: str | None = None
    """Kutilgan natija tavsifi (verification uchun)."""

    depends_on: list[int] = Field(default_factory=list)
    """Oldingi qadamlarning `position` raqamlari (DAG qirralari)."""


class PlanValidationError(ValueError):
    """Reja validatsiyadan o'tmadi (sikl, ortiqcha qadamlar, va h.k.)."""


class Plan(BaseModel, frozen=True):
    """Planner yaratgan bajarish rejasi.

    `steps` — tartiblangan qadamlar ro'yxati;
    `depends_on` orqali DAG hosil qiladi.
    """

    summary: str = Field(min_length=1)
    """Reja xulosa qilingan tavsifi."""

    steps: list[PlanStep]
    """Tartiblangan qadamlar."""

    task_class: str = "normal"
    """Vazifa sinfi (Planner qayta aniqlashi mumkin)."""

    estimated_usd: float = Field(default=0.0, ge=0.0)
    """Taxminiy narxi (USD)."""

    raw_llm_output: dict[str, Any] = Field(default_factory=dict)
    """LLM qaytargan xom javob (debug/audit)."""

    @model_validator(mode="after")
    def _validate_dag(self) -> Plan:
        """DAG tekshiruvi: sikllar va noto'g'ri havolalar aniqlanadi."""
        positions = {s.position for s in self.steps}

        # 1. Har bir depends_on mavjud pozitsiyaga ishora qilishi kerak
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in positions:
                    raise PlanValidationError(
                        f"Qadam {step.position} mavjud bo'lmagan qadam {dep} ga bog'liq"
                    )
                if dep >= step.position:
                    raise PlanValidationError(
                        f"Qadam {step.position} o'zidan keyingi/o'ziga ({dep}) bog'liq"
                    )

        # 2. Topologik tartiblash — sikl aniqlash
        _detect_cycle(self.steps)
        return self

    @property
    def max_permission(self) -> PermissionLevel:
        """Rejadagi eng yuqori ruxsat talabi."""
        if not self.steps:
            return PermissionLevel.READ
        return max(self.steps, key=lambda s: s.permission_required.rank).permission_required

    @property
    def needs_approval(self) -> bool:
        """Reja EXECUTE yoki ADMIN ruxsatli qadamlarni o'z ichiga oladi (V-32)."""
        return self.max_permission >= PermissionLevel.EXECUTE


def _detect_cycle(steps: list[PlanStep]) -> None:
    """Topologik tartiblash yordamida DAG'da sikl bor-yo'qligini tekshiradi."""
    adj: dict[int, list[int]] = {s.position: list(s.depends_on) for s in steps}
    visited: set[int] = set()
    in_stack: set[int] = set()

    def dfs(node: int) -> None:
        if node in in_stack:
            raise PlanValidationError(f"Rejada sikl aniqlandi: qadam {node}")
        if node in visited:
            return
        in_stack.add(node)
        for dep in adj.get(node, []):
            dfs(dep)
        in_stack.discard(node)
        visited.add(node)

    for step in steps:
        dfs(step.position)
