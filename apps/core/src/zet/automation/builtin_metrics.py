"""Watcher uchun tayyor metrikalar — kuzatiladigan birinchi qiymatlar.

`WatcherRegistry` metrikani qayerdan olishni bilmaydi: u `MetricRegistry`
dan so'raydi. Bu modul ZET'ning O'ZI haqidagi metrikalarni ro'yxatdan
o'tkazadi — tashqi API'siz, kalitlarsiz, darhol ishlaydigan.

Shu sabab kuzatuv xususiyati (3-xususiyat) birinchi kundan sinab
ko'riladigan bo'ladi: ega kalendar yoki Instagram ulanishini kutmasdan
"agent xatolari oshsa xabar ber" qoidasini yoza oladi.

Tashqi metrikalar (kanal obunachilari, lidlar soni) keyin shu yerga
qo'shiladi — `WatchRule`ning o'zi umuman o'zgarmaydi.

Bog'liq qarorlar:
    Yangi zip — 3-xususiyat (kuzatuv)
    Bo'lim 9 — avtomatlashtirish
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from zet.agents.registry import AgentRegistry
    from zet.automation.engine import AutomationEngine

log = structlog.get_logger(__name__)

AGENTS_ACTIVE = "agents.active"
"""Faol agentlar soni."""

AGENTS_FAILED_RUNS = "agents.failed_runs"
"""Barcha agentlar bo'yicha muvaffaqiyatsiz run'lar yig'indisi."""

AGENTS_TOTAL_RUNS = "agents.total_runs"
"""Barcha run'lar yig'indisi."""

AUTOMATION_EVENTS = "automation.events"
"""Qayta ishlangan hodisalar soni."""

SCHEDULES_ACTIVE = "automation.schedules_active"
"""Faol jadval qoidalari soni."""


def register_builtin_metrics(
    engine: AutomationEngine,
    agent_registry: AgentRegistry,
) -> None:
    """ZET'ning o'zi haqidagi metrikalarni `engine.metrics` ga qo'shish.

    Barcha o'lchovchilar sinxron ma'lumotdan o'qiydi va hech qachon
    xato ko'tarmaydi — `MetricRegistry.read()` baribir ushlaydi, lekin
    watcher tsikli toza qolgani ma'qul.
    """
    from zet.domain.enums import AgentStatus

    async def active_agents() -> float | None:
        return float(len(agent_registry.list_agents(status=AgentStatus.ACTIVE)))

    async def failed_runs() -> float | None:
        return float(sum(a.failed_runs for a in agent_registry.list_agents()))

    async def total_runs() -> float | None:
        return float(sum(a.total_runs for a in agent_registry.list_agents()))

    async def events() -> float | None:
        return float(engine.event_count)

    async def schedules_active() -> float | None:
        return float(len(engine.scheduler.active_rules))

    engine.metrics.register(AGENTS_ACTIVE, active_agents)
    engine.metrics.register(AGENTS_FAILED_RUNS, failed_runs)
    engine.metrics.register(AGENTS_TOTAL_RUNS, total_runs)
    engine.metrics.register(AUTOMATION_EVENTS, events)
    engine.metrics.register(SCHEDULES_ACTIVE, schedules_active)

    log.info("watcher.builtin_metrics_registered", count=len(engine.metrics.known))


__all__ = [
    "AGENTS_ACTIVE",
    "AGENTS_FAILED_RUNS",
    "AGENTS_TOTAL_RUNS",
    "AUTOMATION_EVENTS",
    "SCHEDULES_ACTIVE",
    "register_builtin_metrics",
]
