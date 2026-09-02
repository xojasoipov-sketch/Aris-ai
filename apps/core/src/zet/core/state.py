"""AI Core holati — Sleep/Active interfeysi (Bo'lim 12, gap-analysis #20).

Ilgari ZET'ning o'zi uchun global "uxlayapti / ishlayapti" konsepsiyasi
umuman yo'q edi (faqat KillSwitch bor — bu favqulodda to'xtatish, boshqa
narsa). `CoreState` boshqa narsa: bu ega tomonidan boshqariladigan, oddiy
pauza — kunlik avtonom jadval (V-35) va boshqa proaktiv ishlar SLEEPING
paytida to'xtaydi, lekin eganing o'zi CLI/Telegram/API orqali to'g'ridan-to'g'ri
buyruq bersa, baribir javob beriladi (KillSwitch'dan farqli — bu qat'iy
to'xtatish emas).

Bog'liq qarorlar:
    V-35 — kunlik avtonom jadval (SLEEPING paytida ishlamaydi)
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

import structlog

log = structlog.get_logger(__name__)


class CoreMode(StrEnum):
    """AI Core'ning joriy rejimi."""

    ACTIVE = "active"
    """Oddiy ish rejimi — barcha proaktiv ishlar (jadval, monitoring) ishlaydi."""

    SLEEPING = "sleeping"
    """Passiv rejim — proaktiv/avtonom ishlar to'xtaydi.

    Eganing to'g'ridan-to'g'ri buyruqlariga (CLI/Telegram/API `/run`) baribir
    javob beriladi — bu KillSwitch emas, faqat avtonomiya pauzasi.
    """


class CoreState:
    """AI Core rejimi — global holat (KillSwitch bilan bir xil naqsh).

    In-memory — boshqa singleton'lar kabi (KillSwitchState, AgentRegistry).
    """

    def __init__(self) -> None:
        self._mode: CoreMode = CoreMode.ACTIVE
        self._reason: str | None = None
        self._changed_at: datetime | None = None
        self._changed_by: str | None = None

    @property
    def mode(self) -> CoreMode:
        """Joriy rejim."""
        return self._mode

    @property
    def is_sleeping(self) -> bool:
        """SLEEPING rejimidami — proaktiv ishlar shu bayroqni tekshiradi."""
        return self._mode is CoreMode.SLEEPING

    @property
    def reason(self) -> str | None:
        """Oxirgi o'zgarish sababi."""
        return self._reason

    @property
    def changed_at(self) -> datetime | None:
        """Oxirgi o'zgarish vaqti."""
        return self._changed_at

    @property
    def changed_by(self) -> str | None:
        """Kim o'zgartirgan."""
        return self._changed_by

    def sleep(
        self,
        *,
        reason: str = "Ega tomonidan",
        by: str = "owner",
        now: datetime | None = None,
    ) -> None:
        """SLEEPING rejimiga o'tkazish — proaktiv ishlar to'xtaydi."""
        self._mode = CoreMode.SLEEPING
        self._reason = reason
        self._changed_at = now or datetime.now(tz=UTC)
        self._changed_by = by
        log.info("core.sleep", reason=reason, by=by)

    def wake(
        self,
        *,
        reason: str = "Ega tomonidan",
        by: str = "owner",
        now: datetime | None = None,
    ) -> None:
        """ACTIVE rejimiga qaytarish."""
        self._mode = CoreMode.ACTIVE
        self._reason = reason
        self._changed_at = now or datetime.now(tz=UTC)
        self._changed_by = by
        log.info("core.wake", reason=reason, by=by)

    def to_dict(self) -> dict[str, str | None]:
        """API/CLI javoblari uchun lug'atga o'girish."""
        return {
            "mode": self._mode.value,
            "reason": self._reason,
            "changed_at": self._changed_at.isoformat() if self._changed_at else None,
            "changed_by": self._changed_by,
        }


__all__ = ["CoreMode", "CoreState"]
