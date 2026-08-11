"""Konfiguratsiyadan provayder to'plamini yig'ish.

Kaliti yo'q provayder ham yaratiladi — u `is_configured=False` bo'ladi va
Model Router uni o'tkazib yuboradi. Bu "kalit qo'shdim, ishlab ketdi" tajribasini
beradi: kod o'zgarmaydi, faqat `.env`.
"""

from __future__ import annotations

from pydantic import SecretStr

from zet.config import Settings
from zet.domain.enums import ModelTier
from zet.llm.anthropic import AnthropicProvider
from zet.llm.base import LLMProvider
from zet.llm.openai_compat import OpenAICompatProvider

# Free tier'larning OpenAI-mos endpointlari
GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"


def _secret(value: SecretStr | None) -> str | None:
    return value.get_secret_value() if value is not None else None


def build_providers(settings: Settings) -> dict[str, LLMProvider]:
    """Katalogdagi har bir provayder nomi uchun implementatsiya."""
    return {
        # T0 — lokal, kalit talab qilmaydi (ADR-0007)
        "ollama": OpenAICompatProvider(
            name="ollama",
            tier=ModelTier.T0_LOCAL,
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            requires_key=False,
        ),
        # T1 — free tier
        "google": OpenAICompatProvider(
            name="google",
            tier=ModelTier.T1_FREE,
            base_url=GOOGLE_BASE_URL,
            api_key=_secret(settings.google_api_key),
        ),
        "groq": OpenAICompatProvider(
            name="groq",
            tier=ModelTier.T1_FREE,
            base_url=GROQ_BASE_URL,
            api_key=_secret(settings.groq_api_key),
        ),
        "mistral": OpenAICompatProvider(
            name="mistral",
            tier=ModelTier.T1_FREE,
            base_url=MISTRAL_BASE_URL,
            api_key=_secret(settings.mistral_api_key),
        ),
        # T2 / T3 — to'lovli
        "anthropic": AnthropicProvider(_secret(settings.anthropic_api_key)),
    }


async def close_providers(providers: dict[str, LLMProvider]) -> None:
    for provider in providers.values():
        await provider.aclose()
