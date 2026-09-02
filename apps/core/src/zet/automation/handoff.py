"""Agent navbati (handoff) — agentning 4-xususiyati (yangi zip, slayd 10).

Ega ta'rifi: *"Boshqa agent [navbat] — ishni keyingi agentga/bosqichga
uzatadi."*

`WorkflowChain` bu ishni allaqachon qiladi, lekin **qat'iy**: zanjir
oldindan to'liq yozilgan bo'lishi kerak. Handoff **reaktiv** yo'lni
qo'shadi:

    agent 'research' muvaffaqiyatli tugadi
        → `agent.completed` hodisasi
        → shartga mos `AGENT_HANDOFF` triggerlar
        → agent 'ceo' natija bilan ishga tushadi

Ya'ni yangi bo'g'in qo'shish uchun mavjud zanjirni qayta yozish shart
emas — trigger qo'shiladi, xolos.

XAVFSIZLIK — cheksiz tsikl asosiy xavf. Agent A → B → A → ... zanjiri
tizimni budjetsiz qoldirishi mumkin. Ikki tormoz:

    1. `MAX_HANDOFF_DEPTH` — zanjir chuqurligi chegarasi
    2. Tashrif buyurilgan agentlar to'plami — bitta zanjirda bir agent
       ikki marta ishga tushmaydi

Ikkalasi ham A-07 ruhida: avtonomiya cheksiz emas, tormozli.

Bog'liq qarorlar:
    Yangi zip — 4-xususiyat (navbat)
    Bo'lim 9 — avtomatlashtirish
    A-07 — run tormozlari
    V-32 — tasdiq handoff orqali chetlab o'tilmaydi
"""

from __future__ import annotations

import structlog

from zet.agents.registry import AgentRegistry
from zet.automation.engine import AutomationEngine
from zet.automation.events import AutomationEvent
from zet.automation.executor import AgentUnavailableError, run_agent_command
from zet.domain.agent import AgentRunResult
from zet.llm.base import LLMProvider
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

MAX_HANDOFF_DEPTH = 5
"""Bitta zanjirda ketma-ket nechta handoff bo'lishi mumkin."""

HANDOFF_EVENT_TYPE = "agent.completed"
"""Agent tugaganda chiqadigan hodisa turi."""

MAX_OUTPUT_IN_EVENT = 4000
"""Hodisa ma'lumotiga kiritiladigan natijaning maksimal uzunligi."""


def completion_event(
    agent_name: str,
    result: AgentRunResult,
    *,
    source: str = "",
) -> AutomationEvent:
    """Agent tugaganidan `agent.completed` hodisasini yasash.

    Shablon o'zgaruvchilari (`command_template` ichida ishlatiladi):
        `{agent}` `{success}` `{output}` `{error}` `{tool_calls}`
    """
    output = result.output or ""
    if len(output) > MAX_OUTPUT_IN_EVENT:
        output = output[:MAX_OUTPUT_IN_EVENT] + "…"

    return AutomationEvent(
        event_type=HANDOFF_EVENT_TYPE,
        source=source or f"agent.{agent_name}",
        data={
            "agent": agent_name,
            "success": "true" if result.success else "false",
            "output": output,
            "error": result.error or "",
            "tool_calls": str(result.tool_calls_count),
        },
    )


class HandoffDispatcher:
    """Agent tugagach navbatdagi agentlarni ishga tushiruvchi.

    `dispatch()` rekursiv: ishga tushirilgan agent ham o'z navbatida
    `agent.completed` chiqaradi. Rekursiya `MAX_HANDOFF_DEPTH` va
    tashrif to'plami bilan cheklangan.
    """

    def __init__(
        self,
        *,
        engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy,
        killswitch: KillSwitchState | None = None,
        provider: LLMProvider | None = None,
        max_depth: int = MAX_HANDOFF_DEPTH,
    ) -> None:
        self._engine = engine
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._killswitch = killswitch
        self._provider = provider
        self._max_depth = max_depth

    async def dispatch(
        self,
        agent_name: str,
        result: AgentRunResult,
        *,
        _depth: int = 0,
        _visited: frozenset[str] | None = None,
    ) -> list[str]:
        """Tugagan agent uchun navbatni ishga tushirish.

        Args:
            agent_name: Endi tugagan agent
            result: Uning natijasi
            _depth: Ichki — joriy zanjir chuqurligi
            _visited: Ichki — shu zanjirda allaqachon ishlagan agentlar

        Returns:
            Ishga tushirilgan agentlar nomlari (zanjir bo'ylab, tekis ro'yxat)
        """
        visited = (_visited or frozenset()) | {agent_name}
        started: list[str] = []

        if _depth >= self._max_depth:
            log.warning(
                "handoff.depth_exceeded",
                agent=agent_name,
                depth=_depth,
                max_depth=self._max_depth,
            )
            return started

        if self._killswitch is not None and self._killswitch.is_engaged:
            log.info("handoff.skipped", agent=agent_name, reason="killswitch")
            return started

        event = completion_event(agent_name, result)
        for action in self._engine.process_event(event):
            if action.agent_name in visited:
                log.warning(
                    "handoff.cycle_blocked",
                    from_agent=agent_name,
                    to_agent=action.agent_name,
                    visited=sorted(visited),
                )
                continue

            try:
                next_result = await run_agent_command(
                    action.agent_name,
                    action.command,
                    agent_registry=self._agent_registry,
                    tool_registry=self._tool_registry,
                    permission_policy=self._permission_policy,
                    provider=self._provider,
                )
            except AgentUnavailableError as exc:
                log.warning(
                    "handoff.agent_unavailable",
                    agent=action.agent_name,
                    error=str(exc),
                )
                continue

            started.append(action.agent_name)
            log.info(
                "handoff.dispatched",
                from_agent=agent_name,
                to_agent=action.agent_name,
                trigger=action.trigger_name,
                depth=_depth + 1,
                success=next_result.success,
            )

            started.extend(
                await self.dispatch(
                    action.agent_name,
                    next_result,
                    _depth=_depth + 1,
                    _visited=visited,
                )
            )

        return started


__all__ = [
    "HANDOFF_EVENT_TYPE",
    "MAX_HANDOFF_DEPTH",
    "MAX_OUTPUT_IN_EVENT",
    "HandoffDispatcher",
    "completion_event",
]
