"""Nomzodlarni reytinglash — relevance + https + auth soddaligi +
sog'liq + ishonch + holat (ENABLED ustunlik) birlashtirilgan ball.

Vazifa tavsifidagi misol natija shaklini takrorlaydi ("Tool Discovery
Result" — nomzod ro'yxati, har biri relevance/health/auth/pricing
bilan).
"""

from __future__ import annotations

from dataclasses import dataclass

from zet.integrations.public_apis.catalog.models import APIStatus, AuthType
from zet.integrations.public_apis.discovery.search import SearchMatch

_AUTH_SIMPLICITY_BONUS: dict[AuthType, float] = {
    AuthType.NONE: 0.15,
    AuthType.API_KEY: 0.08,
    AuthType.BEARER: 0.05,
    AuthType.BASIC: 0.03,
    AuthType.OAUTH: 0.02,
    AuthType.CUSTOM: 0.0,
    AuthType.UNKNOWN: 0.0,
}

_ENABLED_BONUS = 0.30
"""ZET'da HAQIQIY adapter bo'lgan yozuv har doim tepaga chiqishi kerak —
u ijro etiladigan, boshqalari faqat kashfiyot."""


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """Bitta nomzod — reytinglash sabablari bilan (shaffof, "qora quti" emas)."""

    entry_id: str
    name: str
    provider: str
    category: str
    relevance: float
    composite_score: float
    auth_type: AuthType
    https_supported: bool
    pricing_status: str
    status: APIStatus
    health_score: float | None
    reasons: tuple[str, ...]


def rank_candidates(matches: list[SearchMatch]) -> list[RankedCandidate]:
    """Xom qidiruv mosliklarini yakuniy reytinglangan nomzodlarga o'giradi."""
    if not matches:
        return []

    max_score = max(m.score for m in matches) or 1
    ranked: list[RankedCandidate] = []

    for m in matches:
        entry = m.entry
        relevance = m.score / max_score

        https_bonus = 0.15 if entry.https_supported else 0.0
        auth_bonus = _AUTH_SIMPLICITY_BONUS.get(entry.auth_type, 0.0)
        # Sog'liq hali o'lchanmagan bo'lsa — neytral 0.5 (na jazolaydi,
        # na mukofotlaydi; `None` != "yomon").
        health_component = (entry.health_score if entry.health_score is not None else 0.5) * 0.20
        trust_component = min(entry.trust_score, 1.0) * 0.10
        enabled_bonus = _ENABLED_BONUS if entry.status is APIStatus.ENABLED else 0.0

        composite = min(
            1.0,
            relevance * 0.30
            + https_bonus
            + auth_bonus
            + health_component
            + trust_component
            + enabled_bonus,
        )

        reasons: list[str] = []
        if entry.status is APIStatus.ENABLED:
            reasons.append("ZET'da ulangan (haqiqiy adapter bor)")
        if entry.https_supported:
            reasons.append("HTTPS")
        if entry.auth_type is AuthType.NONE:
            reasons.append("kalit talab qilmaydi")
        elif entry.auth_type is AuthType.API_KEY:
            reasons.append("apiKey talab qiladi")
        if entry.health_score is not None:
            reasons.append(f"sog'liq {entry.health_score:.0%}")

        ranked.append(
            RankedCandidate(
                entry_id=entry.id,
                name=entry.name,
                provider=entry.provider,
                category=entry.category,
                relevance=round(relevance, 3),
                composite_score=round(composite, 3),
                auth_type=entry.auth_type,
                https_supported=entry.https_supported,
                pricing_status=entry.pricing_status.value,
                status=entry.status,
                health_score=entry.health_score,
                reasons=tuple(reasons),
            )
        )

    ranked.sort(key=lambda c: c.composite_score, reverse=True)
    return ranked


__all__ = ["RankedCandidate", "rank_candidates"]
