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


class RiskLevel(StrEnum):
    """Xavf darajasi (Capability + Mission uchun).

    NEGA: MissionEngine PLANNING bosqichida bir necha capability'ni bir
    reja ostida birlashtiradi. Har bir capability'ning o'z xavf darajasi
    bor; kompozitsiyaning MAX'i tasdiq (approval) darvozasini boshqaradi
    — HIGH/CRITICAL bo'lsa WAITING_APPROVAL'ga o'tadi.

    Ilgari xavf har tool darajasida edi; bu bir "biznes ochish" rejasini
    o'nlab alohida tasdiqqa bo'lardi. Endi mission darajasida bitta darvoza.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _RISK_RANK[self]

    def __lt__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, RiskLevel):
            return self.rank >= other.rank
        return NotImplemented

    @property
    def requires_approval(self) -> bool:
        """MEDIUM+ mission darajasida ega tasdig'ini talab qiladi (AUTONOMY_AUDIT §2.2)."""
        return self >= RiskLevel.MEDIUM


_RISK_RANK: Final[dict[RiskLevel, int]] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class VerificationStrategy(StrEnum):
    """Verifier natijani qanday isbotlashi (Master Spec PART 6).

    NEGA: har bir capability o'z chiqishini isbotlashning turli usuliga
    ega — sayt qurish HTTP_CHECK, moliya HUMAN_REVIEW, deploy HTTP_CHECK
    + LOG_INSPECTION. Verifier shu enum bo'yicha dispatch qiladi.

    Ilgari verifier universal edi — barcha vazifalarga bir xil
    tekshiruv qo'llardi va soxta "muvaffaqiyatli" natijalar berardi.
    """

    NONE = "none"
    HTTP_CHECK = "http_check"
    LINK_CHECK = "link_check"
    VISUAL_DIFF = "visual_diff"
    API_ECHO = "api_echo"
    FILE_EXISTS = "file_exists"
    TEST_SUITE = "test_suite"
    HUMAN_REVIEW = "human_review"
    LOG_INSPECTION = "log_inspection"
    METRIC_THRESHOLD = "metric_threshold"


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
    RECOVERING = "recovering"
    """FAIL→DIAGNOSE→FIX→RETRY→VERIFY siklidagi vaqtinchalik holat (Master
    Spec PART 6, AUTONOMY_AUDIT §2.5).

    NEGA alohida holat: verify_run ok=False qaytsa, ilgari darhol FAILED
    ga o'tardi — ega hech qanday tuzatish urinishini ko'rmasdi. Endi
    Orchestrator RecoveryEngine bilan qadamlarni tuzatishga urinadi va
    shu davrda RunRecord.status halol RECOVERING deb ko'rsatiladi.

    Terminal EMAS — u DONE/FAILED/CANCELLED ga (yoki qayta EXECUTING/
    VERIFYING ga) o'tadi."""
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
        {
            RunStatus.EXECUTING,
            RunStatus.RECOVERING,
            RunStatus.DONE,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.RECOVERING: frozenset(
        {
            RunStatus.EXECUTING,
            RunStatus.VERIFYING,
            RunStatus.DONE,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
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


class AgentStatus(StrEnum):
    """Agent holati (V-11). DRAFT dan boshlab ARCHIVED gacha."""

    DRAFT = "draft"
    """Yangi yaratilgan, hali sinovdan o'tmagan."""

    TESTING = "testing"
    """Eval to'plami bilan sinovda."""

    ACTIVE = "active"
    """Faol — vazifalarni bajarishi mumkin."""

    PAUSED = "paused"
    """Vaqtincha to'xtatilgan (ega tomonidan)."""

    DISABLED = "disabled"
    """O'chirilgan (xato yoki siyosat buzilishi sababli)."""

    ARCHIVED = "archived"
    """Arxivlangan — qayta tiklab bo'lmaydi."""

    @property
    def is_active(self) -> bool:
        return self is AgentStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_AGENT_STATUSES

    def can_transition_to(self, target: AgentStatus) -> bool:
        return target in AGENT_TRANSITIONS[self]


_TERMINAL_AGENT_STATUSES: Final[frozenset[AgentStatus]] = frozenset({AgentStatus.ARCHIVED})

AGENT_TRANSITIONS: Final[dict[AgentStatus, frozenset[AgentStatus]]] = {
    AgentStatus.DRAFT: frozenset({AgentStatus.TESTING, AgentStatus.ARCHIVED}),
    AgentStatus.TESTING: frozenset(
        {AgentStatus.ACTIVE, AgentStatus.DRAFT, AgentStatus.DISABLED, AgentStatus.ARCHIVED}
    ),
    AgentStatus.ACTIVE: frozenset({AgentStatus.PAUSED, AgentStatus.DISABLED, AgentStatus.ARCHIVED}),
    AgentStatus.PAUSED: frozenset({AgentStatus.ACTIVE, AgentStatus.DISABLED, AgentStatus.ARCHIVED}),
    AgentStatus.DISABLED: frozenset({AgentStatus.DRAFT, AgentStatus.ARCHIVED}),
    AgentStatus.ARCHIVED: frozenset(),
}


class MissionStatus(StrEnum):
    """Mission holati (Bo'lim 2, §2.2).

    NEGA alohida enum: Mission strategiya qatlami (nima qilishni
    tanlash), Run esa bajarish qatlami. Ilgari faqat `RunStatus` bor
    edi va u ikki roldan biriga to'g'ri kelmasdi — masalan "kontekst
    izlash" bosqichi Run holat mashinasiga sig'masdi. Endi Mission
    o'zining fazalari orqali yuradi va har fazada bir yoki bir nechta
    Run tug'diradi.
    """

    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    DISCOVERING = "discovering"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_MISSION_STATUSES

    def can_transition_to(self, target: MissionStatus) -> bool:
        return target in MISSION_TRANSITIONS[self]


_TERMINAL_MISSION_STATUSES: Final[frozenset[MissionStatus]] = frozenset(
    {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}
)

MISSION_TRANSITIONS: Final[dict[MissionStatus, frozenset[MissionStatus]]] = {
    MissionStatus.RECEIVED: frozenset(
        {MissionStatus.UNDERSTANDING, MissionStatus.CANCELLED, MissionStatus.FAILED}
    ),
    MissionStatus.UNDERSTANDING: frozenset(
        {MissionStatus.DISCOVERING, MissionStatus.FAILED, MissionStatus.CANCELLED}
    ),
    MissionStatus.DISCOVERING: frozenset(
        {MissionStatus.PLANNING, MissionStatus.FAILED, MissionStatus.CANCELLED}
    ),
    MissionStatus.PLANNING: frozenset(
        {
            MissionStatus.WAITING_APPROVAL,
            MissionStatus.EXECUTING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.WAITING_APPROVAL: frozenset(
        {MissionStatus.EXECUTING, MissionStatus.CANCELLED, MissionStatus.FAILED}
    ),
    MissionStatus.EXECUTING: frozenset(
        {
            MissionStatus.VERIFYING,
            MissionStatus.WAITING_APPROVAL,
            MissionStatus.RECOVERING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.VERIFYING: frozenset(
        {
            MissionStatus.COMPLETED,
            MissionStatus.RECOVERING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.RECOVERING: frozenset(
        {
            MissionStatus.EXECUTING,
            MissionStatus.PLANNING,
            MissionStatus.FAILED,
            MissionStatus.CANCELLED,
        }
    ),
    MissionStatus.COMPLETED: frozenset(),
    MissionStatus.FAILED: frozenset(),
    MissionStatus.CANCELLED: frozenset(),
}


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
