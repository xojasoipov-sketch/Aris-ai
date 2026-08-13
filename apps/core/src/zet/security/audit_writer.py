"""Audit log INSERT yordamchisi (V-33, GAP_ANALYSIS SR-02).

`db/models/security.AuditLog` jadvali qurilgan, immutability trigger
o'rnatilgan — ammo hech qayerdan yozilmasdi (jadval doim bo'sh).
Bu modul yozish nuqtasini yopadi.

FAIL-OPEN: DB yetib bo'lmasa xato yutiladi, tool bajarilishi
to'xtatilmaydi. Audit — ikkinchi darajali muhim, birinchi darajali
majburiy emas. Bu qoida `security/killswitch_store.py` bilan bir xil.

Chaqirish nuqtalari:
    - `tools/registry.py::execute()` — har muvaffaqiyatli tool call
    - `security/permissions.py` orqali rad etilgan chaqiruv (via executor)
    - `security/killswitch_store.persist_killswitch` yonida
      engage/disengage
    - Approval qabul/rad etish (`orchestrator.approve`/`reject`)
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.models.security import AuditLog
from zet.db.session import session_scope
from zet.domain.enums import PermissionLevel

log = structlog.get_logger(__name__)


async def write_audit(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    actor: str,
    action: str,
    target: str | None = None,
    permission_level: PermissionLevel | None = None,
    run_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Bitta audit yozuvini bazaga qo'shadi (fail-open).

    Args:
        session_factory: DB sessiya fabrikasi. `None` bo'lsa hech narsa
            qilinmaydi (test/lean rejim).
        actor: kim/nima harakat qildi ("owner", "agent:ceo", "system:daemon" ...)
        action: nima qilindi ("tool.execute", "approval.granted", "killswitch.engaged" ...)
        target: harakat maqsadi (tool nomi, chat_id, resurs id ...)
        permission_level: talab qilingan ruxsat darajasi (bo'lsa)
        run_id: shu run bilan bog'liqmi
        detail: qo'shimcha ma'lumot (JSON'ga sig'adigan dict)
    """
    if session_factory is None:
        return
    try:
        async with session_scope(session_factory) as session:
            entry = AuditLog(
                actor=actor,
                action=action,
                target=target,
                permission_level=permission_level,
                run_id=run_id,
                detail=detail or {},
            )
            session.add(entry)
    except Exception:
        log.warning("audit.write_failed", action=action, actor=actor)


__all__ = ["write_audit"]
