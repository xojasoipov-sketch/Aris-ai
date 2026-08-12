"""Model katalogi: narx, tier va free tier kvotalari.

⚠️ NARXLAR VA KVOTALAR ESKIRADI.
Ular provayder saytlarida o'zgaradi; bu fayl — yagona haqiqat manbai va uni
vaqti-vaqti bilan tekshirib turish kerak. Har bir yozuvda tekshirilgan sana bor.

Oxirgi tekshiruv: 2026-08-11. Qiymatlar **taxminiy** va faqat marshrutlash
qarorlari uchun ishlatiladi; haqiqiy hisob-kitob provayder hisobidan olinadi.

Bog'liq: ADR-0006 (4 tier), A-04 (metrika qaytish halqasi).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from zet.domain.enums import ModelTier, TaskClass
from zet.llm.base import Usage


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Bitta modelning marshrutlash uchun kerakli tavsifi."""

    key: str
    """Katalogdagi noyob kalit, masalan `groq:llama-3.3-70b`."""

    provider: str
    model: str
    tier: ModelTier
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0
    supports_tools: bool = True
    supports_vision: bool = False
    free_rpd: int | None = None
    """Free tier: kunlik so'rovlar limiti (None — cheklovsiz yoki pullik)."""
    free_rpm: int | None = None
    """Free tier: daqiqadagi so'rovlar limiti."""

    @property
    def is_free(self) -> bool:
        return self.input_usd_per_mtok == 0.0 and self.output_usd_per_mtok == 0.0

    def cost_usd(self, usage: Usage) -> float:
        """Chaqiruv narxi."""
        return (
            usage.input_tokens * self.input_usd_per_mtok
            + usage.output_tokens * self.output_usd_per_mtok
        ) / 1_000_000


# ── T0: lokal, mutlaqo bepul (egasining kompyuterida, ADR-0007) ────
# 16 GB RAM uchun 7-8B modellar tanlandi.
_T0: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        key="ollama:qwen3-8b",
        provider="ollama",
        model="qwen3:8b",
        tier=ModelTier.T0_LOCAL,
    ),
    ModelSpec(
        key="ollama:llama3.1-8b",
        provider="ollama",
        model="llama3.1:8b",
        tier=ModelTier.T0_LOCAL,
    ),
)

# ── T1: free tier (kvota chegarasida bepul) ────────────────────────
_T1: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        key="google:gemini-flash",
        provider="google",
        model="gemini-flash-latest",
        tier=ModelTier.T1_FREE,
        supports_vision=True,
        free_rpd=1500,
        free_rpm=15,
    ),
    ModelSpec(
        key="groq:llama-3.3-70b",
        provider="groq",
        model="llama-3.3-70b-versatile",
        tier=ModelTier.T1_FREE,
        free_rpd=1000,
        free_rpm=30,
    ),
    ModelSpec(
        key="mistral:small",
        provider="mistral",
        model="mistral-small-latest",
        tier=ModelTier.T1_FREE,
        free_rpd=500,
        free_rpm=20,
    ),
)

# ── T2 / T3: to'lovli, qattiq chegara ostida ───────────────────────
_PAID: Final[tuple[ModelSpec, ...]] = (
    ModelSpec(
        key="anthropic:haiku",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        tier=ModelTier.T2_CHEAP,
        input_usd_per_mtok=1.00,
        output_usd_per_mtok=5.00,
        supports_vision=True,
    ),
    ModelSpec(
        key="anthropic:sonnet",
        provider="anthropic",
        model="claude-sonnet-5",
        tier=ModelTier.T3_STRONG,
        input_usd_per_mtok=3.00,
        output_usd_per_mtok=15.00,
        supports_vision=True,
    ),
    ModelSpec(
        key="anthropic:opus",
        provider="anthropic",
        model="claude-opus-5",
        tier=ModelTier.T3_STRONG,
        input_usd_per_mtok=15.00,
        output_usd_per_mtok=75.00,
        supports_vision=True,
    ),
)

CATALOG: Final[dict[str, ModelSpec]] = {s.key: s for s in (*_T0, *_T1, *_PAID)}


# ── Marshrutlash siyosati (V-29 + ADR-0006) ────────────────────────
# Tartib = ustuvorlik. Router birinchi mos kelganini oladi:
# kalit bor + kvota bor + budjet yetadi + circuit breaker yopiq.
ROUTING: Final[dict[TaskClass, tuple[str, ...]]] = {
    # Klassifikatsiya, xulosa, formatlash — lokal bemalol uddalaydi
    TaskClass.SIMPLE: (
        "ollama:qwen3-8b",
        "google:gemini-flash",
        "groq:llama-3.3-70b",
        "anthropic:haiku",
    ),
    # Kundalik ish oti — free tier birinchi
    TaskClass.NORMAL: (
        "google:gemini-flash",
        "groq:llama-3.3-70b",
        "mistral:small",
        "ollama:qwen3-8b",
        "anthropic:haiku",
    ),
    # Planner va murakkab reasoning — bu yerda sifat pul turadi
    TaskClass.COMPLEX: (
        "anthropic:sonnet",
        "google:gemini-flash",
        "groq:llama-3.3-70b",
    ),
    TaskClass.CODING: (
        "anthropic:sonnet",
        "groq:llama-3.3-70b",
        "google:gemini-flash",
    ),
    TaskClass.VISION: (
        "google:gemini-flash",
        "anthropic:haiku",
    ),
    # Ovoz lokal `faster-whisper` bilan (Bo'lim 4) — bu yerda zaxira yo'l
    TaskClass.SPEECH: ("google:gemini-flash",),
}


def candidates_for(task_class: TaskClass) -> tuple[ModelSpec, ...]:
    """Vazifa sinfi uchun nomzod modellar, ustuvorlik tartibida."""
    return tuple(CATALOG[key] for key in ROUTING[task_class])
