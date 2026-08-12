"""Avtonomiya darajalari L0-L4 — agent qanchalik mustaqil (yangi zip, slayd 8-9).

Ega yuborgan ko'rsatmalar besh darajani belgilaydi:

    L0  Chat            — savol-javob, hech narsa bajarilmaydi
    L1  Bog'lash        — tool'larga ulanadi, ega buyurganda ishlatadi
    L2  Pipeline        — hodisa tushganda oldindan belgilangan zanjir ishlaydi
    L3  Agent           — NATIJA aytiladi, yo'lni o'zi topadi
    L4  Mustaqil agent  — o'ziga buyruq beradi, o'zini yaxshilaydi

MUHIM — daraja RUXSAT BERMAYDI, RUXSATNI CHEKLAYDI.

Ikki o'q bir-birini almashtirmaydi:

    `PermissionLevel` — agent QANDAY tool chaqira oladi (V-31)
    `AutonomyLevel`   — agentni KIM/NIMA ishga tushira oladi va u o'ziga
                        o'zi ish topa oladimi

Shuning uchun `effective_permission()` faqat pasaytiradi, hech qachon
ko'tarmaydi. L4 agent ham `PermissionLevel.ADMIN` ni avtonomiya orqali
OLMAYDI — ADMIN faqat eganing aniq sozlamasi bilan beriladi.

V-32 hech bir darajada bekor qilinmaydi: L4 agent *rejalashtirishda*
mustaqil, *bajarishda* emas — EXECUTE amal baribir tasdiqdan o'tadi.

Bog'liq qarorlar:
    Yangi zip — 5 avtonomiya darajasi
    V-31 — ruxsat darajalari
    V-32 — majburiy approval (daraja bundan ozod qilmaydi)
    A-07 — run tormozlari (daraja qo'shimcha tormoz beradi)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import structlog
from pydantic import BaseModel, Field

from zet.domain.enums import PermissionLevel

log = structlog.get_logger(__name__)


class AutonomyViolationError(RuntimeError):
    """Agent o'z avtonomiya darajasidan yuqori imkoniyatni so'radi."""


class AutonomyLevel(StrEnum):
    """Avtonomiya darajasi. Tartiblangan: L0 < L1 < L2 < L3 < L4."""

    L0_CHAT = "l0_chat"
    """Suhbat — javob beradi, hech narsani bajarmaydi."""

    L1_CONNECTED = "l1_connected"
    """Bog'langan — tool'lardan foydalanadi, lekin faqat ega so'raganda."""

    L2_PIPELINE = "l2_pipeline"
    """Pipeline — hodisa/vaqt uni ishga tushira oladi, yo'l oldindan belgilangan."""

    L3_AGENT = "l3_agent"
    """Agent — maqsad beriladi, qadamlarni o'zi tuzadi."""

    L4_AUTONOMOUS = "l4_autonomous"
    """Mustaqil — o'ziga vazifa qo'yadi va muvaffaqiyatsizlikdan keyin qayta rejalashtiradi."""

    @property
    def rank(self) -> int:
        """Tartib raqami (taqqoslash uchun)."""
        return _LEVEL_RANK[self]

    @property
    def label(self) -> str:
        """Ega ko'radigan qisqa nom (o'zbekcha)."""
        return _LEVEL_LABEL[self]


_LEVEL_RANK: Final[dict[AutonomyLevel, int]] = {
    AutonomyLevel.L0_CHAT: 0,
    AutonomyLevel.L1_CONNECTED: 1,
    AutonomyLevel.L2_PIPELINE: 2,
    AutonomyLevel.L3_AGENT: 3,
    AutonomyLevel.L4_AUTONOMOUS: 4,
}

_LEVEL_LABEL: Final[dict[AutonomyLevel, str]] = {
    AutonomyLevel.L0_CHAT: "Suhbat",
    AutonomyLevel.L1_CONNECTED: "Bog'lash",
    AutonomyLevel.L2_PIPELINE: "Pipeline",
    AutonomyLevel.L3_AGENT: "Agent",
    AutonomyLevel.L4_AUTONOMOUS: "Mustaqil agent",
}


class AutonomyCapability(StrEnum):
    """Daraja ochadigan aniq imkoniyat."""

    USE_TOOLS = "use_tools"
    """Tool chaqirish (L1+)."""

    TRIGGERED_RUN = "triggered_run"
    """Ega yozmasdan — cron/webhook/watcher orqali ishga tushish (L2+)."""

    SELF_PLANNING = "self_planning"
    """Qadamlarni o'zi tuzish; faqat natija aytiladi (L3+)."""

    SELF_COMMAND = "self_command"
    """O'ziga yangi vazifa/jadval qo'yish (L4)."""

    SELF_IMPROVE = "self_improve"
    """Muvaffaqiyatsizlikdan keyin rejani qayta yozib, qayta urinish (L4)."""


class AutonomyPolicy(BaseModel, frozen=True):
    """Bitta daraja uchun qoidalar to'plami."""

    level: AutonomyLevel
    """Qaysi daraja."""

    capabilities: frozenset[AutonomyCapability]
    """Shu darajada ochiq imkoniyatlar."""

    max_permission: PermissionLevel
    """Avtonomiya berishi mumkin bo'lgan eng yuqori ruxsat (ADMIN hech qachon)."""

    max_goal_iterations: int = Field(default=0, ge=0, le=20)
    """Maqsad tsikli necha marta qayta rejalashtira oladi (0 = tsikl yo'q)."""

    requires_approval_for_execute: bool = True
    """EXECUTE amal uchun tasdiq (V-32). Hech bir darajada `False` emas."""

    def allows(self, capability: AutonomyCapability) -> bool:
        """Shu daraja `capability` ni beradimi."""
        return capability in self.capabilities


_POLICIES: Final[dict[AutonomyLevel, AutonomyPolicy]] = {
    AutonomyLevel.L0_CHAT: AutonomyPolicy(
        level=AutonomyLevel.L0_CHAT,
        capabilities=frozenset(),
        max_permission=PermissionLevel.READ,
    ),
    AutonomyLevel.L1_CONNECTED: AutonomyPolicy(
        level=AutonomyLevel.L1_CONNECTED,
        capabilities=frozenset({AutonomyCapability.USE_TOOLS}),
        max_permission=PermissionLevel.WRITE,
    ),
    AutonomyLevel.L2_PIPELINE: AutonomyPolicy(
        level=AutonomyLevel.L2_PIPELINE,
        capabilities=frozenset({AutonomyCapability.USE_TOOLS, AutonomyCapability.TRIGGERED_RUN}),
        max_permission=PermissionLevel.EXECUTE,
    ),
    AutonomyLevel.L3_AGENT: AutonomyPolicy(
        level=AutonomyLevel.L3_AGENT,
        capabilities=frozenset(
            {
                AutonomyCapability.USE_TOOLS,
                AutonomyCapability.TRIGGERED_RUN,
                AutonomyCapability.SELF_PLANNING,
            }
        ),
        max_permission=PermissionLevel.EXECUTE,
        max_goal_iterations=1,
    ),
    AutonomyLevel.L4_AUTONOMOUS: AutonomyPolicy(
        level=AutonomyLevel.L4_AUTONOMOUS,
        capabilities=frozenset(
            {
                AutonomyCapability.USE_TOOLS,
                AutonomyCapability.TRIGGERED_RUN,
                AutonomyCapability.SELF_PLANNING,
                AutonomyCapability.SELF_COMMAND,
                AutonomyCapability.SELF_IMPROVE,
            }
        ),
        max_permission=PermissionLevel.EXECUTE,
        max_goal_iterations=5,
    ),
}


def policy_for(level: AutonomyLevel) -> AutonomyPolicy:
    """Daraja siyosatini olish."""
    return _POLICIES[level]


def allows(level: AutonomyLevel, capability: AutonomyCapability) -> bool:
    """`level` `capability` ni beradimi."""
    return _POLICIES[level].allows(capability)


def require(level: AutonomyLevel, capability: AutonomyCapability, *, subject: str = "") -> None:
    """Imkoniyatni talab qilish — yo'q bo'lsa xato.

    Args:
        level: Agentning avtonomiya darajasi
        capability: Talab qilinayotgan imkoniyat
        subject: Log uchun kim so'radi (agent nomi)

    Raises:
        AutonomyViolationError: daraja bu imkoniyatni bermaydi
    """
    if allows(level, capability):
        return
    log.warning(
        "autonomy.denied",
        level=level.value,
        capability=capability.value,
        subject=subject,
    )
    msg = (
        f"'{subject or 'agent'}' avtonomiya darajasi {level.value} "
        f"({level.label}) '{capability.value}' imkoniyatini bermaydi — "
        f"kamida {_min_level_for(capability).value} kerak"
    )
    raise AutonomyViolationError(msg)


def _min_level_for(capability: AutonomyCapability) -> AutonomyLevel:
    """`capability` ochiladigan eng past daraja."""
    for level in sorted(AutonomyLevel, key=lambda lv: lv.rank):
        if allows(level, capability):
            return level
    return AutonomyLevel.L4_AUTONOMOUS  # pragma: no cover — har imkoniyat L4'da bor


def effective_permission(level: AutonomyLevel, requested: PermissionLevel) -> PermissionLevel:
    """Avtonomiya darajasi bilan cheklangan haqiqiy ruxsat.

    FAQAT pasaytiradi. Agent `permission_level=READ` bo'lsa, L4 uni
    EXECUTE ga ko'tarmaydi — daraja tormoz, kalit emas.
    """
    cap = _POLICIES[level].max_permission
    return requested if requested <= cap else cap


def max_goal_iterations(level: AutonomyLevel) -> int:
    """Maqsad tsikli uchun ruxsat etilgan qayta rejalash soni."""
    return _POLICIES[level].max_goal_iterations


__all__ = [
    "AutonomyCapability",
    "AutonomyLevel",
    "AutonomyPolicy",
    "AutonomyViolationError",
    "allows",
    "effective_permission",
    "max_goal_iterations",
    "policy_for",
    "require",
]
