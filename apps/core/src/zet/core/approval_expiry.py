"""Tasdiq (Approval) TTL muddati — proaktiv sweep (JB-12).

MUAMMO (JB-12 auditi topgan, `security/approvals.py`ning o'z docstring'i
"Fail-closed: TTL tugasa → EXPIRED → run CANCELLED" deb da'vo qiladi,
lekin bu HECH QANDAY ishlayotgan kod yo'li orqali TA'MINLANMAGAN edi):

`ApprovalService.expire_all_pending()` (mavjud, to'g'ri yozilgan) hech
qachon HECH QAYERDAN — daemon'dan, tick'dan, startup'dan — chaqirilmasdi.
Grep bo'yicha bitta chaqiruvchi ham topilmadi (faqat o'z testlari).
Amaliy natija: muddati tugagan tasdiq faqat KIMDIR uni `approve()`/
`reject()` qilishga urinib ko'rganda REAKTIV ravishda EXPIRED bo'lardi
(`ApprovalRequest.approve/reject` ichida `is_expired()` tekshiruvi bor).
Agar ega hech qachon amal qilmasa — run/mission ABADIY WAITING_APPROVAL/
AWAITING_APPROVAL holatida osilib qolardi, hech kim uni CANCELLED
qilmasdi.

YECHIM: bu modul `sweep_expired_approvals()` — mavjud
`ApprovalService.expire_all_pending()`ni (yangi kod EMAS, faqat
CHAQIRUVCHI) davriy ravishda ishga tushiradigan yordamchi. Chaqiruvchi
(`AutomationDaemon.tick()`, JB-12) buni har tikda (allaqachon 60
soniyada bir ishlaydigan mavjud tsikl — yangi daemon SHART EMAS)
chaqiradi.

Mission-level muddati tugagan tasdiqlar uchun — bog'liq Mission haqiqatan
CANCELLED qilinadi (`MissionEngine.cancel()`, mavjud metod — boshqa
maqsad uchun yozilgan, bu yerga aynan mos). Run-level (mission_id=None)
muddati tugagan tasdiqlar uchun — HALOL CHEGARA: bog'liq `Run`ning o'zi
FAOL RAVISHDA CANCELLED qilinmaydi (quyidagi docstring'ga qarang) —
faqat `ApprovalRequest.status` EXPIRED qilinadi (bu allaqachon
`approve()`/`resume()`ning keyingi har qanday urinishini fail-closed
rad etadi — mavjud `is_expired()` tekshiruvi orqali). Bu YANGI xavfsizlik
teshigi EMAS (approve/resume baribir rad etiladi), faqat "run darajasi
proaktiv CANCELLED bo'ladimi" degan savolga halol javob: yo'q, hali emas.

Bog'liq qarorlar:
    JB-12 §27 — Approval TTL expiry
    security/approvals.py — ApprovalService.expire_all_pending()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import structlog

from zet.db.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from zet.security.approvals import ApprovalService

log = structlog.get_logger(__name__)


class _MissionEngineLike(Protocol):
    """`MissionEngine.cancel()` uchun minimal shartnoma (aylanma importdan qochish)."""

    async def cancel(self, mission_id: Any, reason: str) -> Any: ...  # pragma: no cover — protocol


async def sweep_expired_approvals(
    approvals: ApprovalService,
    *,
    mission_engine_factory: Callable[[AsyncSession], Awaitable[_MissionEngineLike]] | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Muddati tugagan barcha tasdiqlarni EXPIRED qiladi va bog'liq
    Mission'larni bekor qiladi.

    Fail-open — har bosqich xatoni yutadi: bitta buzuq mission-cancel
    urinishi qolgan tasdiqlarni sweep qilishni to'xtatmasligi kerak
    (bu — davriy fon vazifasi, `AutomationDaemon.tick()` ichida
    chaqiriladi, xato butun tikni yiqitmasligi kerak).

    Args:
        approvals: sweep qilinadigan `ApprovalService`.
        mission_engine_factory: berilsa — mission-level muddati tugagan
            tasdiqlar uchun `MissionEngine.cancel()` chaqiriladi.
            Berilmasa (masalan `session_factory=None` muhitda) — faqat
            `ApprovalRequest.status` EXPIRED qilinadi, mission'ga
            tegilmaydi (fail-open, eski xatti-harakat).
        session_factory: `mission_engine_factory` uchun sessiya manbai.

    Returns:
        Muddati tugagan (EXPIRED qilingan) tasdiqlar soni.
    """
    expired = approvals.expire_all_pending()
    for req in expired:
        # AR-01 bilan bir xil naqsh: `approve()`/`reject()` ham
        # `persist_pending()`ni ANGLAB (deterministik) kutadi — bu yerda
        # ham xuddi shunday, background fire-and-forget'ga TAYANMAYMIZ
        # (daemon tick tugagach process qulasa, EXPIRED holat DB'ga
        # yozilmay qolishi mumkin edi).
        try:
            await approvals.persist_pending(req)
        except Exception:
            log.warning("approval_expiry.persist_failed", approval_id=str(req.id))

        if (
            req.mission_id is not None
            and mission_engine_factory is not None
            and session_factory is not None
        ):
            try:
                async with session_scope(session_factory) as session:
                    engine = await mission_engine_factory(session)
                    await engine.cancel(
                        req.mission_id, "tasdiq muddati tugadi (TTL, JB-12 sweep)"
                    )
                log.warning(
                    "approval_expiry.mission_cancelled",
                    mission_id=str(req.mission_id),
                    approval_id=str(req.id),
                )
            except Exception:
                # Fail-open: mission allaqachon terminal holatda bo'lishi
                # mumkin (masalan owner tasdiq TTL tugashidan bir lahza
                # OLDIN ✅ bosgan bo'lishi mumkin — kamdan-kam, lekin
                # xavfsiz race) — bu XATO emas, shunchaki keyingi qadam
                # kerak emas.
                log.warning(
                    "approval_expiry.mission_cancel_failed",
                    mission_id=str(req.mission_id),
                    approval_id=str(req.id),
                )
        elif req.mission_id is None:
            log.warning(
                "approval_expiry.run_level_expired_no_active_cancel",
                approval_id=str(req.id),
                run_id=str(req.run_id),
            )

    if expired:
        log.warning("approval_expiry.swept", count=len(expired))
    return len(expired)


__all__ = ["sweep_expired_approvals"]
