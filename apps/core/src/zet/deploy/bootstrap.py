"""Ilova ishga tushishida bajariladigan bootstrap qadamlar (Bo'lim 12).

API (`api/app.py` lifespan) va CLI (`z daemon`) ikkalasi ham shu modul
orqali agentlarni ro'yxatga oladi — mantiq bir joyda, takrorlanmaydi.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)


def bootstrap_agents() -> int:
    """12 ta builtin agentni registry'ga (mavjud bo'lmasa) ACTIVE holatda qo'shadi.

    Returns:
        Ro'yxatga olingan builtin agentlar soni (jami, mavjud bo'lganlar ham).
    """
    import zet.agents.builtin as builtin_module
    from zet.api.deps import get_agent_registry
    from zet.domain.enums import AgentStatus

    registry = get_agent_registry()
    for spec_name in builtin_module.__all__:
        spec = getattr(builtin_module, spec_name)
        if not registry.has(spec.name):
            registry.register(spec, status=AgentStatus.ACTIVE)
    log.info("zet.agents_bootstrapped", count=len(builtin_module.__all__))
    return len(builtin_module.__all__)


__all__ = ["bootstrap_agents"]
