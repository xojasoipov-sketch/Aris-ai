"""Emergency Stop (KillSwitch) — Z1.12.

Global bayroq — yoqilganda:
    1. Barcha faol run'lar bir zumda CANCELLED
    2. Yangi run boshlanmaydi
    3. Protsess qayta ishga tushsa ham kuchda qoladi (DB da saqlanadi)

Faqat eganing aniq buyrug'i bilan qaytariladi (`z resume`).

Bog'liq qarorlar:
    V-33 — favqulodda to'xtatish
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

log = structlog.get_logger(__name__)


class KillSwitchEngagedError(Exception):
    """Kill switch yoqilgan — hech qanday amal bajarilmaydi."""


class KillSwitchState:
    """Kill switch holati — in-memory (DB bilan sinxronlash Orchestrator vazifasi).

    Thread-safe emas — async context'da ishlatiladi.
    """

    def __init__(self) -> None:
        self._engaged: bool = False
        self._reason: str | None = None
        self._engaged_at: datetime | None = None
        self._engaged_by: str | None = None

    @property
    def is_engaged(self) -> bool:
        """Kill switch yoqilganmi."""
        return self._engaged

    @property
    def reason(self) -> str | None:
        """Yoqilish sababi."""
        return self._reason

    @property
    def engaged_at(self) -> datetime | None:
        """Yoqilgan vaqt."""
        return self._engaged_at

    @property
    def engaged_by(self) -> str | None:
        """Kim yoqqan."""
        return self._engaged_by

    def engage(
        self,
        *,
        reason: str = "Emergency stop",
        by: str = "owner",
        now: datetime | None = None,
    ) -> None:
        """Kill switch'ni yoqadi.

        Idempotent — allaqachon yoqilgan bo'lsa hech narsa qilmaydi.
        """
        if self._engaged:
            log.warning("killswitch.already_engaged")
            return

        self._engaged = True
        self._reason = reason
        self._engaged_at = now or datetime.now(tz=UTC)
        self._engaged_by = by

        log.critical(
            "killswitch.engaged",
            reason=reason,
            by=by,
        )

    def disengage(self, *, by: str = "owner") -> None:
        """Kill switch'ni o'chiradi.

        Faqat eganing aniq buyrug'i bilan.

        Raises:
            ValueError: allaqachon o'chirilgan
        """
        if not self._engaged:
            raise ValueError("Kill switch allaqachon o'chirilgan")

        log.critical(
            "killswitch.disengaged",
            was_engaged_at=str(self._engaged_at),
            was_reason=self._reason,
            by=by,
        )

        self._engaged = False
        self._reason = None
        self._engaged_at = None
        self._engaged_by = None

    def check(self) -> None:
        """Kill switch holatini tekshiradi.

        Raises:
            KillSwitchEngagedError: yoqilgan bo'lsa
        """
        if self._engaged:
            raise KillSwitchEngagedError(
                f"Emergency stop yoqilgan: {self._reason or "sabab ko'rsatilmagan"}"
            )

    def to_dict(self) -> dict[str, object]:
        """Holat — API va CLI uchun."""
        return {
            "engaged": self._engaged,
            "reason": self._reason,
            "engaged_at": str(self._engaged_at) if self._engaged_at else None,
            "engaged_by": self._engaged_by,
        }
