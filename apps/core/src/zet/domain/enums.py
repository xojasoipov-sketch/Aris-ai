"""ZET domenining asosiy sanoqli tiplari.

Bu yerda faqat **umumiy** enum'lar — ular DB modellari va domen kontraktlari
tomonidan birgalikda ishlatiladi, shuning uchun ikkalasidan ham oldin turadi.

Bog'liq qarorlar:
    A-01 — Run/Step davomli holat mashinasi (chiziqli pipeline emas)
    A-05 — untrusted input chegarasi (`TrustLevel`)
    ADR-0006 — model tier'lari (`ModelTier`)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class PermissionLevel(StrEnum):
    """Ruxsat darajasi (V-31). Tartiblangan: READ < WRITE < EXECUTE < ADMIN."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _PERMISSION_RANK[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, PermissionLevel):
            return self.rank >= other.rank
        return NotImplemented


_PERMISSION_RANK: Final[dict[PermissionLevel, int]] = {
    PermissionLevel.READ: 0,
    PermissionLevel.WRITE: 1,
    PermissionLevel.EXECUTE: 2,
    PermissionLevel.ADMIN: 3,
}


class TrustLevel(StrEnum):
    """Ma'lumot manbasiga ishonch darajasi (A-05).

    `UNTRUSTED` kontent planner promptiga to'g'ridan-to'g'ri kirmaydi va undan
    kelib chiqqan qadam avtomatik ravishda WRITE/EXECUTE/ADMIN tool chaqira olmaydi.
    """

    OWNER = "owner"
    """Egasining o'zi yozgan/aytgan matn."""

    SYSTEM = "system"
    """ZET'ning o'z komponentlari ishlab chiqargan ma'lumot."""

    UNTRUSTED = "untrusted"
    """Tashqi dunyo: web sahifa, hujjat, OCR, forward qilingan xabar, kamera matni."""


class TaskClass(StrEnum):
    """Vazifa sinfi — Model Router shu asosda tier tanlaydi (V-29, ADR-0006)."""

    SIMPLE = "simple"
    NORMAL = "normal"
    COMPLEX = "complex"
    CODING = "coding"
    VISION = "vision"
    SPEECH = "speech"


class ModelTier(StrEnum):
    """Model tier'i (ADR-0006). Marshrut tartibi: T0 -> T1 -> T2 -> T3."""

    T0_LOCAL = "t0_local"
    T1_FREE = "t1_free"
    T2_CHEAP = "t2_cheap"
    T3_STRONG = "t3_strong"

    @property
    def rank(self) -> int:
        return _TIER_RANK[self]


_TIER_RANK: Final[dict[ModelTier, int]] = {
    ModelTier.T0_LOCAL: 0,
    ModelTier.T1_FREE: 1,
    ModelTier.T2_CHEAP: 2,
    ModelTier.T3_STRONG: 3,
}


class RunStatus(StrEnum):
    """Run holati (A-01). O'tishlar `RUN_TRANSITIONS` bilan cheklangan."""

    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_RUN_STATUSES

    def can_transition_to(self, target: RunStatus) -> bool:
        return target in RUN_TRANSITIONS[self]


_TERMINAL_RUN_STATUSES: Final[frozenset[RunStatus]] = frozenset(
    {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
)

RUN_TRANSITIONS: Final[dict[RunStatus, frozenset[RunStatus]]] = {
    RunStatus.PENDING: frozenset({RunStatus.PLANNING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.PLANNING: frozenset(
        {
            RunStatus.EXECUTING,
            RunStatus.AWAITING_APPROVAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.AWAITING_APPROVAL: frozenset(
        {RunStatus.EXECUTING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.EXECUTING: frozenset(
        {
            RunStatus.AWAITING_APPROVAL,
            RunStatus.VERIFYING,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.VERIFYING: frozenset(
        {RunStatus.EXECUTING, RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.DONE: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class StepStatus(StrEnum):
    """Reja qadamining holati."""

    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in {StepStatus.DONE, StepStatus.FAILED, StepStatus.SKIPPED}


class ApprovalStatus(StrEnum):
    """Tasdiq so'rovining holati (V-32)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MessageRole(StrEnum):
    """Suhbat xabarining roli."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class RunTrigger(StrEnum):
    """Run'ni nima boshlagani (V-26).

    `MANUAL` dan boshqasi — avtonom; ular alohida budjet ulushiga ega (ADR-0006 §4).
    """

    MANUAL = "manual"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"
    EVENT = "event"
    AGENT = "agent"

    @property
    def is_autonomous(self) -> bool:
        return self is not RunTrigger.MANUAL
