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
    # 2026-08-12 jonli tekshirilgan: base64 rasm bilan so'rov yuborildi,
    # to'g'ri javob qaytdi ("Bu rasmda qizil rang bor").
    #
    # NEGA KERAK: bungacha VISION zanjirida ikkita yozuv bor edi va
    # ulardan biri (`anthropic:haiku`) sozlanmagan, ikkinchisi esa bepul
    # kvotada tez-tez limitga uriladi — ya'ni rasm bilan bog'liq har
    # qanday vazifa yagona modelga bog'lanib qolgandi.
    ModelSpec(
        key="mistral:pixtral",
        provider="mistral",
        model="pixtral-12b-2409",
        tier=ModelTier.T1_FREE,
        supports_vision=True,
        free_rpd=500,
        free_rpm=20,
    ),
    # 2026-08-12 jonli tekshirilgan: javob qaytardi.
    ModelSpec(
        key="cohere:command-r",
        provider="cohere",
        model="command-r-08-2024",
        tier=ModelTier.T1_FREE,
        free_rpd=1000,
        free_rpm=20,
    ),
    # OpenRouter'ning `:free` slug'lari. Bepul modellar ro'yxati tez-tez
    # o'zgaradi — bu model yo'qolsa router keyingisiga o'tadi.
    #
    # SEKIN: 2026-08-12 o'lchovi ~33 s (boshqa bepul variantlar tezroq,
    # lekin `nemotron-3.5-lightning` javob ichida "thinking" matnini
    # qaytardi, ikkitasi esa bo'sh content berdi). Shu sabab toza javob
    # tanlandi va u zanjirning OXIRIDA turadi — faqat google/mistral/
    # cohere/ollama yiqilganda ishlaydi, ya'ni sekinlik kundalik yo'lga
    # tegmaydi.
    ModelSpec(
        key="openrouter:nemotron-ultra",
        provider="openrouter",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        tier=ModelTier.T1_FREE,
        free_rpd=50,
        free_rpm=20,
    ),
    # Kaliti bor, hisobi bo'sh (2026-08-12). Marshrutning oxirida turadi —
    # hisob to'ldirilgach o'zi ishlay boshlaydi.
    ModelSpec(
        key="cerebras:gpt-oss-120b",
        provider="cerebras",
        model="gpt-oss-120b",
        tier=ModelTier.T1_FREE,
        free_rpd=100,
        free_rpm=10,
    ),
)

# ── T2 / T3: to'lovli, qattiq chegara ostida ───────────────────────
_PAID: Final[tuple[ModelSpec, ...]] = (
    # DeepSeek va Kimi — arzon muqobillar. 2026-08-12: kalit yaroqli,
    # balans yo'q. Narxlar taxminiy (provayder saytidan, tekshirilishi shart).
    ModelSpec(
        key="deepseek:flash",
        provider="deepseek",
        model="deepseek-v4-flash",
        tier=ModelTier.T2_CHEAP,
        input_usd_per_mtok=0.14,
        output_usd_per_mtok=0.28,
    ),
    ModelSpec(
        key="kimi:k2",
        provider="kimi",
        model="kimi-k2.6",
        tier=ModelTier.T2_CHEAP,
        input_usd_per_mtok=0.60,
        output_usd_per_mtok=2.50,
    ),
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
#
# TARTIB JONLI TEKSHIRUVGA ASOSLANGAN (2026-08-12). Har bir provayderga
# haqiqiy so'rov yuborildi — "kalit bor" degani "ishlaydi" degani emas:
#
#     ishladi:  google, mistral, cohere, openrouter (:free)
#     balanssiz: cerebras, deepseek, kimi (kalit yaroqli, hisob bo'sh)
#
# Balanssizlari zanjirdan OLIB TASHLANMADI, balki OXIRIGA qo'yildi:
# hisob to'ldirilgach kod o'zgarmasdan ishlay boshlaydi. Ular har
# so'rovni sekinlashtirmaydi — circuit breaker birinchi xatodan keyin
# provayderni chetlab o'tadi.
ROUTING: Final[dict[TaskClass, tuple[str, ...]]] = {
    # Klassifikatsiya, xulosa, formatlash — lokal bemalol uddalaydi
    TaskClass.SIMPLE: (
        "ollama:qwen3-8b",
        "google:gemini-flash",
        "groq:llama-3.3-70b",
        "cohere:command-r",
        "openrouter:nemotron-ultra",
        "cerebras:gpt-oss-120b",
        "anthropic:haiku",
    ),
    # Kundalik ish oti — free tier birinchi
    TaskClass.NORMAL: (
        "google:gemini-flash",
        "groq:llama-3.3-70b",
        "mistral:small",
        "cohere:command-r",
        "ollama:qwen3-8b",
        "openrouter:nemotron-ultra",
        "cerebras:gpt-oss-120b",
        "deepseek:flash",
        "anthropic:haiku",
    ),
    # Planner va murakkab reasoning — bu yerda sifat pul turadi
    TaskClass.COMPLEX: (
        "anthropic:sonnet",
        "google:gemini-flash",
        "groq:llama-3.3-70b",
        "openrouter:nemotron-ultra",
        "deepseek:flash",
        "kimi:k2",
    ),
    TaskClass.CODING: (
        "anthropic:sonnet",
        "groq:llama-3.3-70b",
        "google:gemini-flash",
        "deepseek:flash",
        "kimi:k2",
    ),
    TaskClass.VISION: (
        "google:gemini-flash",
        "mistral:pixtral",
        "anthropic:haiku",
    ),
    # Ovoz lokal `faster-whisper` bilan (Bo'lim 4) — bu yerda zaxira yo'l
    TaskClass.SPEECH: ("google:gemini-flash",),
}


def candidates_for(task_class: TaskClass) -> tuple[ModelSpec, ...]:
    """Vazifa sinfi uchun nomzod modellar, ustuvorlik tartibida."""
    return tuple(CATALOG[key] for key in ROUTING[task_class])
