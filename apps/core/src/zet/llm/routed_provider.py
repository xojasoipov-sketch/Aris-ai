"""RoutedLLMProvider — `ModelRouter`ni `AgentRuntime` kutgan `LLMProvider`ga moslaydi.

Ilgari `AgentRuntime`ning barcha real chaqiruvchilari (`/api/v1/agents/{name}/run`,
`DailyScheduleDaemon`, `automation/executor.py`) `FakeProvider()`ni qattiq
kodlangan holda ishlatardi — real LLM kaliti (`.env`da) bo'lsa ham agent
hech qachon chinakam javob bermas edi (faqat kirish matnini aks ettirardi).
Faqat Orchestrator'ning Intent/Plan bosqichi (`core/intent.py`, `core/planner.py`)
`ModelRouter`ga to'g'ridan-to'g'ri ulangan edi.

`AgentRuntime.provider.complete(model=..., ...)` chaqiradi (bitta model,
erkin satr); `ModelRouter.complete(task_class=..., ...)` esa vazifa sinfi
bo'yicha eng arzon ishlaydigan providerni tanlaydi (ADR-0006, budjet/kvota
bilan). Bu adapter ikkalasini bog'laydi: `model` maydoni `TaskClass` qiymati
sifatida talqin qilinadi (`task_class_for_tier()` orqali `AgentSpec.model_policy`
dan hosil qilinadi) — `AgentRuntime`ning o'zi o'zgarmaydi.

Bog'liq qarorlar:
    ADR-0006 — 4 darajali Model Router, budjet/kvota
    Bo'lim 3 — AgentRuntime
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import structlog

from zet.domain.enums import ModelTier, TaskClass
from zet.llm.base import ChatMessage, LLMResponse, ToolSpec
from zet.llm.router import ModelRouter

log = structlog.get_logger(__name__)

TIER_TASK_CLASS: dict[ModelTier, TaskClass] = {
    ModelTier.T0_LOCAL: TaskClass.SIMPLE,
    ModelTier.T1_FREE: TaskClass.NORMAL,
    ModelTier.T2_CHEAP: TaskClass.COMPLEX,
    ModelTier.T3_STRONG: TaskClass.COMPLEX,
}
"""`AgentSpec.model_policy` (tier) dan `TaskClass`ga taxminiy moslashtirish —
agentlar hozircha task_class emas, tier bilan belgilanadi (Bo'lim 3)."""


def task_class_for_tier(tier: ModelTier) -> TaskClass:
    """`AgentSpec.model_policy`ni `ModelRouter.complete()` kutgan `TaskClass`ga o'giradi."""
    return TIER_TASK_CLASS.get(tier, TaskClass.NORMAL)


class RoutedLLMProvider:
    """`ModelRouter`ni yagona `LLMProvider` sifatida ko'rsatuvchi adapter.

    Haqiqiy model tanlovi, budjet va kvota tekshiruvi butunlay
    `ModelRouter`da qoladi — bu klass faqat interfeys ko'prigi.
    """

    name = "router"
    tier = ModelTier.T1_FREE  # informatsion — haqiqiy tanlov ModelRouter'da hal bo'ladi

    def __init__(
        self,
        router: ModelRouter,
        *,
        run_id: uuid.UUID | None = None,
        is_autonomous: bool = False,
        run_spent_usd: float = 0.0,
        run_budget_usd: float | None = None,
    ) -> None:
        self._router = router
        self._run_id = run_id
        self._is_autonomous = is_autonomous
        self._run_spent_usd = run_spent_usd
        self._run_budget_usd = run_budget_usd

    @property
    def is_configured(self) -> bool:
        """`ModelRouter` o'zi ichki providerlarning sozlanganligini tekshiradi."""
        return True

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 2048,
        temperature: float = 0.0,
        timeout_s: float = 60.0,  # noqa: ARG002 — ModelRouter o'z ichida boshqaradi
    ) -> LLMResponse:
        """`model`ni `TaskClass` sifatida talqin qilib, `ModelRouter` orqali marshrutlaydi."""
        try:
            task_class = TaskClass(model)
        except ValueError:
            task_class = TaskClass.NORMAL

        result = await self._router.complete(
            task_class=task_class,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            run_id=self._run_id,
            is_autonomous=self._is_autonomous,
            run_spent_usd=self._run_spent_usd,
            run_budget_usd=self._run_budget_usd,
        )
        return result.response

    async def aclose(self) -> None:
        """Hech narsa qilmaydi — providerlarni `get_llm_providers()` egasi yopadi."""


__all__ = ["TIER_TASK_CLASS", "RoutedLLMProvider", "task_class_for_tier"]
