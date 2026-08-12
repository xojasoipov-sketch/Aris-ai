"""Ilova ishga tushishida bajariladigan bootstrap qadamlar (Bo'lim 12).

API (`api/app.py` lifespan) va CLI (`z daemon`) ikkalasi ham shu modul
orqali agentlarni ro'yxatga oladi — mantiq bir joyda, takrorlanmaydi.
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

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


async def load_persisted_agents(session: AsyncSession) -> int:
    """DB'da saqlangan (Factory orqali yaratilgan) agentlarni registry'ga qayta yuklaydi.

    Ilgari Agent Factory orqali yaratilgan har qanday agent faqat
    in-memory `AgentRegistry`da yashardi — protsess qayta ishga
    tushganda yo'qolardi (gap-analysis #1). Endi `AgentRepository`
    orqali DB'ga yozilgan agentlar shu funksiya bilan qayta tiklanadi.

    DB ulanmagan/mavjud bo'lmagan bo'lsa — jim o'tkazib yuboriladi
    (fail-open: bu ixtiyoriy qulaylik, ilova ishga tushishining sharti
    emas — builtin agentlar baribir `bootstrap_agents()` bilan mavjud).

    Returns:
        Registry'ga qo'shilgan (avval mavjud bo'lmagan) agentlar soni.
    """
    from zet.agents.repository import AgentRepository
    from zet.api.deps import get_agent_registry

    registry = get_agent_registry()
    repo = AgentRepository(session)

    try:
        persisted = await repo.load_all()
    except Exception:
        log.warning("zet.agents_reload_skipped", reason="DB o'qib bo'lmadi")
        return 0

    added = 0
    for state in persisted:
        if not registry.has(state.spec.name):
            registry.register(state.spec, status=state.status)
            added += 1
    if added:
        log.info("zet.agents_reloaded_from_db", count=added)
    return added


__all__ = ["bootstrap_agents", "load_persisted_agents"]
