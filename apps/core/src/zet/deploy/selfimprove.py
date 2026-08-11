"""Self-Improvement Loop — tizim o'z-o'zini takomillashtirish (Bo'lim 12, V-36).

Tizim ishlash davomida quyidagilarni tahlil qiladi:
    - Agent/tool xatoliklari (nima tez-tez xato beradi?)
    - Workflow bottleneck lari (qayerda sekinlashmoqda?)
    - Xarajatlar (qaysi agentlar qimmat?)
    - Ishlash samaradorligi (qaysi agent ko'p ishlatiladi?)
    - Takrorlanuvchi vazifalar (avtomatlashtirilishi mumkin?)
    - Yetishmayotgan imkoniyatlar (qanday tool/agent kerak?)

MUHIM: Faqat TAVSIYA qiladi, AVTOMATIK O'ZGARTIRISH QILMAYDI.
Har bir tavsiya eganing tasdig'idan keyin amalga oshiriladi.

Bog'liq qarorlar:
    V-36 — self-improvement loop
    Bo'lim 12 — Production + Scale
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class ImprovementType(StrEnum):
    """Takomillashtirish turi."""

    NEW_AGENT = "new_agent"
    """Yangi agent tavsiya qilish."""

    NEW_TOOL = "new_tool"
    """Yangi tool tavsiya qilish."""

    NEW_WORKFLOW = "new_workflow"
    """Yangi workflow tavsiya qilish."""

    BETTER_MODEL = "better_model"
    """Yaxshiroq model tavsiya qilish."""

    BETTER_PROCESS = "better_process"
    """Jarayonni yaxshilash."""

    COST_OPTIMIZATION = "cost_optimization"
    """Xarajatlarni kamaytirish."""

    BUG_FIX = "bug_fix"
    """Xatoni tuzatish."""


class ImprovementPriority(StrEnum):
    """Ustuvorlik."""

    LOW = "low"
    """Past — qulay vaqtda."""

    MEDIUM = "medium"
    """O'rta — yaqin vaqtda."""

    HIGH = "high"
    """Yuqori — tezda."""

    CRITICAL = "critical"
    """Muhim — darhol."""


class ImprovementSuggestion(BaseModel, frozen=True):
    """Takomillashtirish tavsiyasi.

    MUHIM: Faqat tavsiya. Avtomatik amalga oshirilmaydi.
    Ega tasdiqlashi kerak.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal ID."""

    improvement_type: ImprovementType
    """Takomillashtirish turi."""

    title: str = Field(min_length=1, max_length=200)
    """Qisqa sarlavha."""

    description: str = ""
    """Batafsil tavsif."""

    priority: ImprovementPriority = ImprovementPriority.MEDIUM
    """Ustuvorlik."""

    estimated_impact: str = ""
    """Kutilayotgan ta'sir (masalan: '30% tezroq', '$2/oy tejash')."""

    source: str = ""
    """Manba (masalan: 'agent_errors_analysis', 'cost_report')."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    approved: bool = False
    """Ega tasdiqladi."""

    implemented: bool = False
    """Amalga oshirildi."""


class SelfImproveEngine:
    """Tizim takomillashtirish mexanizmi.

    Tavsiyalarni to'playdi va egaga taqdim etadi.
    AVTOMATIK HECH NARSA O'ZGARTIRMAYDI.
    """

    def __init__(self) -> None:
        self._suggestions: list[ImprovementSuggestion] = []

    def suggest(
        self,
        *,
        improvement_type: ImprovementType,
        title: str,
        description: str = "",
        priority: ImprovementPriority = ImprovementPriority.MEDIUM,
        estimated_impact: str = "",
        source: str = "",
    ) -> ImprovementSuggestion:
        """Yangi tavsiya qo'shish.

        Args:
            improvement_type: Turi
            title: Sarlavha
            description: Batafsil tavsif
            priority: Ustuvorlik
            estimated_impact: Kutilayotgan ta'sir
            source: Manba

        Returns:
            Yaratilgan tavsiya
        """
        suggestion = ImprovementSuggestion(
            improvement_type=improvement_type,
            title=title,
            description=description,
            priority=priority,
            estimated_impact=estimated_impact,
            source=source,
        )
        self._suggestions.append(suggestion)

        log.info(
            "selfimprove.suggestion",
            type=improvement_type.value,
            title=title,
            priority=priority.value,
        )
        return suggestion

    def approve(self, suggestion_id: str) -> bool:
        """Tavsiyani tasdiqlash.

        Args:
            suggestion_id: Tavsiya ID

        Returns:
            True agar topilsa va tasdiqlansa
        """
        for i, s in enumerate(self._suggestions):
            if s.id == suggestion_id:
                self._suggestions[i] = ImprovementSuggestion(
                    id=s.id,
                    improvement_type=s.improvement_type,
                    title=s.title,
                    description=s.description,
                    priority=s.priority,
                    estimated_impact=s.estimated_impact,
                    source=s.source,
                    created_at=s.created_at,
                    approved=True,
                    implemented=s.implemented,
                )
                return True
        return False

    def mark_implemented(self, suggestion_id: str) -> bool:
        """Tavsiyani amalga oshirilgan deb belgilash.

        Args:
            suggestion_id: Tavsiya ID

        Returns:
            True agar topilsa va belgilansa
        """
        for i, s in enumerate(self._suggestions):
            if s.id == suggestion_id:
                self._suggestions[i] = ImprovementSuggestion(
                    id=s.id,
                    improvement_type=s.improvement_type,
                    title=s.title,
                    description=s.description,
                    priority=s.priority,
                    estimated_impact=s.estimated_impact,
                    source=s.source,
                    created_at=s.created_at,
                    approved=s.approved,
                    implemented=True,
                )
                return True
        return False

    def pending(self) -> list[ImprovementSuggestion]:
        """Kutilayotgan tavsiyalar (tasdiqlanmagan)."""
        return [s for s in self._suggestions if not s.approved and not s.implemented]

    def approved_list(self) -> list[ImprovementSuggestion]:
        """Tasdiqlangan, lekin amalga oshirilmagan tavsiyalar."""
        return [s for s in self._suggestions if s.approved and not s.implemented]

    def all_suggestions(self) -> list[ImprovementSuggestion]:
        """Barcha tavsiyalar."""
        return list(self._suggestions)

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        items = self._suggestions
        return {
            "total": len(items),
            "pending": sum(1 for s in items if not s.approved and not s.implemented),
            "approved": sum(1 for s in items if s.approved and not s.implemented),
            "implemented": sum(1 for s in items if s.implemented),
        }
