"""Ruxsat siyosati — qaysi amal avtomatik, qaysi biri tasdiq talab qiladi (Z1.12).

Fail-closed dizayn: shubha bo'lsa — rad etiladi.

Qoidalar (V-31, V-32, A-05):
    1. READ — har doim avtomatik
    2. WRITE — sozlanadigan (default: avtomatik, UNTRUSTED → tasdiq)
    3. EXECUTE — HAR DOIM tasdiq
    4. ADMIN — HAR DOIM tasdiq
    5. UNTRUSTED kontekstdan kelgan WRITE/EXECUTE/ADMIN → HAR DOIM tasdiq

Bog'liq qarorlar:
    V-31 — ruxsat darajalari
    V-32 — yuqori xavfli amallar ro'yxati
    A-05 — trust level chegaralari
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import structlog

from zet.domain.enums import PermissionLevel, TrustLevel

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
    """

    def __init__(
        self,
        *,
        auto_approve_write: bool = True,
        high_risk_tools: frozenset[str] | None = None,
    ) -> None:
        """
        Args:
            auto_approve_write: WRITE ruxsatli amallar avtomatik o'tsinmi
            high_risk_tools: qo'shimcha yuqori xavfli toollar
        """
        self._auto_approve_write = auto_approve_write
        self._high_risk_tools = high_risk_tools if high_risk_tools is not None else HIGH_RISK_TOOLS

    def check(
        self,
        permission: PermissionLevel,
        trust: TrustLevel,
        tool_name: str | None = None,
    ) -> PermissionDecision:
        """Ruxsat tekshiruvi.

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
