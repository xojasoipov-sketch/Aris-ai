"""LLM provayder abstraksiyasi.

Barcha provayderlar (lokal Ollama, free tier'lar, to'lovli API'lar) shu bitta
interfeys ostida ishlaydi — `ADR-0006` ning 4 tier'li marshrutlashi shunga tayanadi
va `R-06` (vendor lock) shu bilan yopiladi.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from zet.domain.enums import ModelTier

Role = Literal["system", "user", "assistant", "tool"]


# ── Xatolar ────────────────────────────────────────────────────────


class LLMError(Exception):
    """Barcha LLM xatolarining bazasi."""


class ProviderUnavailableError(LLMError):
    """Provayder javob bermadi (5xx, tarmoq, timeout) — boshqasiga o'tish mumkin."""


class RateLimitError(LLMError):
    """429 — provayder vaqtincha rad etdi."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderConfigError(LLMError):
    """Kalit yo'q yoki noto'g'ri sozlangan — qayta urinish foydasiz."""


class QuotaExhaustedError(LLMError):
    """Free tier kvotasi tugadi (ADR-0006 §3)."""


class BudgetExceededError(LLMError):
    """USD budjet chegarasi oshdi (ADR-0006 §4, fail-closed)."""


class NoProviderAvailableError(LLMError):
    """Barcha nomzodlar rad etildi yoki ishlamadi."""


# ── Ma'lumot tiplari ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Usage:
    """Token iste'moli."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Modelga taqdim etiladigan tool ta'rifi (JSON Schema bilan)."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolUse:
    """Model chaqirmoqchi bo'lgan tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Suhbat xabari."""

    role: Role
    content: str = ""
    tool_call_id: str | None = None
    tool_uses: tuple[ToolUse, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Provayder javobi — marshrutlash va hisob uchun barcha metama'lumot bilan."""

    text: str
    provider: str
    model: str
    tier: ModelTier
    usage: Usage
    latency_ms: int
    finish_reason: str = "stop"
    tool_uses: tuple[ToolUse, ...] = field(default_factory=tuple)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_uses)


# ── Interfeys ──────────────────────────────────────────────────────


@runtime_checkable
class LLMProvider(Protocol):
    """Provayder shartnomasi.

    Implementatsiyalar tarmoq xatolarini `ProviderUnavailableError` va
    `RateLimitError` ga aylantirishi shart — Model Router shu ikkisiga qarab
    keyingi nomzodga o'tadi.
    """

    name: str
    tier: ModelTier

    @property
    def is_configured(self) -> bool:
        """Kalit/manzil mavjudmi (kalitsiz provayder umuman sinalmaydi)."""
        ...

    async def complete(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 2048,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
    ) -> LLMResponse: ...

    async def aclose(self) -> None: ...
