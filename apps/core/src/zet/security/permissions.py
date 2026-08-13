"""Ruxsat siyosati — qaysi amal avtomatik, qaysi biri tasdiq talab qiladi (Z1.12).

Fail-closed dizayn: shubha bo'lsa — rad etiladi.

Qoidalar (V-31, V-32, A-05):
    1. READ — har doim avtomatik
    2. WRITE — sozlanadigan (default: avtomatik, UNTRUSTED → tasdiq)
    3. EXECUTE — HAR DOIM tasdiq
    4. ADMIN — HAR DOIM tasdiq
    5. UNTRUSTED kontekstdan kelgan WRITE/EXECUTE/ADMIN → HAR DOIM tasdiq

Risk kengaytmasi (V-32 + PART 5 of ZET_ASS_MASTER):
    6. HIGH risk tool — HAR DOIM tasdiq (siyosat/avtonomiya chetlab
       o'tolmaydi)
    7. MEDIUM risk tool — default tasdiq; `auto_approve_medium=True` va
       autonomy L2+ bo'lsa avtomatik
    8. LOW risk tool — yuqoridagi umumiy qoidalarga ergashadi

Bog'liq qarorlar:
    V-31 — ruxsat darajalari
    V-32 — yuqori xavfli amallar ro'yxati (risk_level.HIGH)
    A-05 — trust level chegaralari
    ZET_ASS_AUTONOMY_AUDIT §2.8 — risk-based approval oqimi
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from zet.domain.enums import PermissionLevel, RiskLevel, TrustLevel
from zet.security.risk import TOOL_RISK_LEVELS

if TYPE_CHECKING:  # pragma: no cover — faqat type-check
    from zet.automation.autonomy import AutonomyLevel
    from zet.tools.base import Tool

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PermissionDecision:
    """Ruxsat tekshiruvi natijasi."""

    allowed: bool
    """Avtomatik bajarishga ruxsat berildi."""

    needs_approval: bool
    """Ega tasdig'i kerak."""

    reason: str
    """Qaror sababi."""


# ── Yuqori xavfli amallar (V-32) — hech qachon avtomatik emas ──────
#
# NEGA `TOOL_RISK_LEVELS`dan alohida saqlanadi: bu bir necha qadim
# testlar va `PermissionPolicy(high_risk_tools=…)` API'sining aniq
# shartnomasi. Yangi jadval qo'shildi, lekin eskisini o'zgartirmadik —
# ular bir-birini to'ldiradi (ikkalasi ham HIGH risk deb qaraladi).
HIGH_RISK_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "shell.exec",
        "file.delete",
        "db.execute",
        "system.shutdown",
        "config.modify",
        "network.request",
    }
)
"""Bu toollar qo'shimcha himoyaga ega — har doim tasdiq, hatto WRITE bo'lsa ham."""


class PermissionPolicy:
    """Ruxsat siyosati — qanday amallar avtomatik, qaysi biri tasdiq talab qiladi.

    Default siyosat:
        - READ: avtomatik
        - WRITE: avtomatik (lekin UNTRUSTED → tasdiq)
        - EXECUTE: tasdiq
        - ADMIN: tasdiq
        - HIGH risk tool: har doim tasdiq
        - MEDIUM risk tool: default tasdiq (`auto_approve_medium=False`)
    """

    def __init__(
        self,
        *,
        auto_approve_write: bool = True,
        auto_approve_medium: bool = False,
        high_risk_tools: frozenset[str] | None = None,
    ) -> None:
        """
        Args:
            auto_approve_write: WRITE ruxsatli amallar avtomatik o'tsinmi
            auto_approve_medium: MEDIUM risk toollar avtomatik o'tsinmi
                (default: False — fail-closed; ega yoqishi kerak)
            high_risk_tools: qo'shimcha yuqori xavfli toollar
        """
        self._auto_approve_write = auto_approve_write
        self._auto_approve_medium = auto_approve_medium
        self._high_risk_tools = high_risk_tools if high_risk_tools is not None else HIGH_RISK_TOOLS

    def check(
        self,
        permission: PermissionLevel,
        trust: TrustLevel,
        tool_name: str | None = None,
    ) -> PermissionDecision:
        """Eski API — risk axis'siz. Yangi callers `requires_approval` ni ishlatadi.

        Ilgari (Z1.12) faqat ushbu metod bor edi va risk axis yo'q edi;
        chaqiruvchi qismlar hozircha shundoq qoladi. Yangi risk-aware
        qaror uchun `requires_approval()` ga o'ting.

        Args:
            permission: talab qilingan ruxsat darajasi
            trust: kontekst ishonch darajasi
            tool_name: tool nomi (yuqori xavfli ro'yxat uchun)

        Returns:
            PermissionDecision
        """
        # Yuqori xavfli tool — har doim tasdiq
        if tool_name and tool_name in self._high_risk_tools:
            log.info(
                "permission.high_risk_tool",
                tool=tool_name,
                permission=permission.value,
            )
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason=f"Yuqori xavfli tool: {tool_name}",
            )

        # UNTRUSTED kontekst — WRITE va undan yuqori tasdiq talab qiladi
        if trust == TrustLevel.UNTRUSTED and permission >= PermissionLevel.WRITE:
            log.info(
                "permission.untrusted_escalation",
                permission=permission.value,
                trust=trust.value,
            )
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason=(f"UNTRUSTED kontekstdan {permission.value} ruxsat — tasdiq kerak"),
            )

        # READ — har doim avtomatik
        if permission == PermissionLevel.READ:
            return PermissionDecision(
                allowed=True,
                needs_approval=False,
                reason="READ ruxsat — avtomatik",
            )

        # WRITE — sozlanadigan
        if permission == PermissionLevel.WRITE:
            if self._auto_approve_write:
                return PermissionDecision(
                    allowed=True,
                    needs_approval=False,
                    reason="WRITE ruxsat — avtomatik (siyosat bo'yicha)",
                )
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason="WRITE ruxsat — tasdiq kerak (siyosat bo'yicha)",
            )

        # EXECUTE va ADMIN — har doim tasdiq
        return PermissionDecision(
            allowed=False,
            needs_approval=True,
            reason=f"{permission.value} ruxsat — HAR DOIM tasdiq kerak",
        )

    def requires_approval(
        self,
        *,
        permission: PermissionLevel,
        trust: TrustLevel,
        tool: Tool | None = None,
        tool_name: str | None = None,
        risk: RiskLevel | None = None,
        autonomy_level: AutonomyLevel | None = None,
    ) -> PermissionDecision:
        """Risk-aware ruxsat qarori — permission, trust va risk axis birlashtirilgan.

        NEGA yangi metod: eski `check()` faqat permission + trust bilan
        ishlar edi va risk axis'ni ko'rmas edi. Endi tool o'zining
        `risk_level`ini xabar qiladi — MEDIUM biznes yozuvlar
        (`order.set_status`, `note.write` va h.k.) avtomatik ketmasin,
        HIGH esa hech qanday siyosat/avtonomiya bilan chetlab o'tilmasin
        (V-32 kafolat).

        Risk hal qilish tartibi (birinchi topilgan g'olib):
            1. Aniq `risk` argument
            2. `tool.risk_level` (agar `tool` berilgan bo'lsa) — subclass
               override jadvaldan yuqori
            3. `TOOL_RISK_LEVELS[tool_name]` — jadval bo'shliqni to'ldiradi
            4. `RiskLevel.LOW` — default

        Qaror tartibi (fail-closed):
            a. HIGH risk → DOIM tasdiq (V-32; siyosat/autonomy chetlab
               o'tolmaydi)
            b. Eski HIGH_RISK_TOOLS ro'yxati — 2/3 orqali HIGH sifatida
               keladi, lekin nom mos kelsa ham DOIM tasdiq (back-compat)
            c. UNTRUSTED + WRITE+ → tasdiq
            d. EXECUTE/ADMIN → tasdiq (V-32)
            e. MEDIUM risk → agar `auto_approve_medium=True` VA autonomy
               L2+ (yoki autonomy berilmagan) → avtomatik; aks holda tasdiq.
               NEGA autonomy sharti: L0/L1'da ega har chaqiruvda bor —
               inson-tsiklda MEDIUM ni majburiy tasdiqqa berish mantiqan
               to'g'ri (autonomy pasay tortsin, o'zi bilan permission
               ham).
            f. WRITE + LOW → `auto_approve_write` (eski xatti-harakat)
            g. READ + LOW/MEDIUM → avtomatik

        Args:
            permission: talab qilingan ruxsat
            trust: kontekst ishonch darajasi
            tool: Tool obyekti (risk_level va nomni o'zi biladi)
            tool_name: agar Tool obyekti bo'lmasa — nom
            risk: aniq risk darajasi (yuqoridagilarni bosadi)
            autonomy_level: agentning avtonomiya darajasi (MEDIUM qaror
                uchun); None bo'lsa L0-L1 majburiyat qo'llanmaydi

        Returns:
            PermissionDecision
        """
        # 1) Risk aniqlash
        effective_name = tool_name or (tool.name if tool is not None else None)
        if risk is None:
            if tool is not None:
                risk = tool.risk_level
            elif effective_name is not None:
                risk = TOOL_RISK_LEVELS.get(effective_name, RiskLevel.LOW)
            else:
                risk = RiskLevel.LOW

        # 2) Back-compat: eski HIGH_RISK_TOOLS ro'yxati ham HIGH deb qaraladi
        if effective_name and effective_name in self._high_risk_tools:
            risk = max(risk, RiskLevel.HIGH, key=lambda r: r.rank)

        # a) HIGH — DOIM tasdiq, hech narsa chetlab o'tolmaydi
        if risk >= RiskLevel.HIGH:
            log.info(
                "permission.high_risk",
                tool=effective_name,
                risk=risk.value,
                permission=permission.value,
            )
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason=(
                    f"HIGH risk: {effective_name or permission.value} — har doim ega tasdig'i kerak"
                ),
            )

        # c) UNTRUSTED + WRITE+ → tasdiq
        if trust == TrustLevel.UNTRUSTED and permission >= PermissionLevel.WRITE:
            log.info(
                "permission.untrusted_escalation",
                permission=permission.value,
                trust=trust.value,
            )
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason=(f"UNTRUSTED kontekstdan {permission.value} ruxsat — tasdiq kerak"),
            )

        # d) EXECUTE/ADMIN — doim tasdiq (V-32 asosiy qoidasi)
        if permission >= PermissionLevel.EXECUTE:
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason=f"{permission.value} ruxsat — HAR DOIM tasdiq kerak",
            )

        # e) MEDIUM risk — sozlanadigan + autonomy shartga bog'liq
        if risk == RiskLevel.MEDIUM:
            if not self._auto_approve_medium or _requires_human_loop(autonomy_level):
                reason = (
                    "MEDIUM risk — tasdiq (siyosat)"
                    if not self._auto_approve_medium
                    else "MEDIUM risk — past autonomy'da tasdiq majburiy"
                )
                return PermissionDecision(
                    allowed=False,
                    needs_approval=True,
                    reason=reason,
                )
            # Autonomy yetarli va flag yoqilgan — avtomatik
            return PermissionDecision(
                allowed=True,
                needs_approval=False,
                reason="MEDIUM risk — avtomatik (siyosat + autonomy)",
            )

        # f) WRITE + LOW → auto_approve_write bo'yicha
        if permission == PermissionLevel.WRITE:
            if self._auto_approve_write:
                return PermissionDecision(
                    allowed=True,
                    needs_approval=False,
                    reason="WRITE ruxsat — avtomatik (siyosat bo'yicha)",
                )
            return PermissionDecision(
                allowed=False,
                needs_approval=True,
                reason="WRITE ruxsat — tasdiq kerak (siyosat bo'yicha)",
            )

        # g) READ + LOW/MEDIUM → avtomatik
        return PermissionDecision(
            allowed=True,
            needs_approval=False,
            reason="READ ruxsat — avtomatik",
        )


def _requires_human_loop(autonomy_level: AutonomyLevel | None) -> bool:
    """L0/L1 — ega tsiklda, MEDIUM avtomatik o'tmasin.

    NEGA: past autonomy'da har chaqiruv eganing ko'zi ostida bo'ladi,
    MEDIUM ni bosib o'tish "menga hech narsa deme" degan siyosat bilan
    ziddiyatli — L2 va yuqoridagina MEDIUM avtomatik o'ta oladi
    (siyosat flag'i ham True bo'lsa).
    """
    if autonomy_level is None:
        return False
    return autonomy_level.rank < 2
