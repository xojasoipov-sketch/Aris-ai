"""Deterministik soxta provayder — testlar va offline ishlab chiqish uchun.

Tarmoqqa chiqmaydi, pul sarflamaydi. Butun Core pipeline shu bilan sinaladi.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from zet.domain.enums import ModelTier
from zet.llm.base import (
    ChatMessage,
    LLMResponse,
    ToolSpec,
    ToolUse,
    Usage,
)


class FakeProvider:
    """Oldindan belgilangan javoblarni navbat bilan qaytaradi.

    `scripted` bo'sh bo'lsa, oxirgi foydalanuvchi xabarini takrorlaydi —
    bu "modelning aqli" muhim bo'lmagan testlarda qulay.
    """

    def __init__(
        self,
        name: str = "fake",
        tier: ModelTier = ModelTier.T0_LOCAL,
        *,
        scripted: Sequence[LLMResponse | Exception] = (),
        configured: bool = True,
        input_tokens: int = 100,
        output_tokens: int = 20,
    ) -> None:
        self.name = name
        self.tier = tier
        self._scripted: deque[LLMResponse | Exception] = deque(scripted)
        self._configured = configured
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls: list[dict[str, object]] = []

    @property
    def is_configured(self) -> bool:
        return self._configured

    def push(self, item: LLMResponse | Exception) -> None:
        """Navbatga yana bitta javob yoki xato qo'shish."""
        self._scripted.append(item)

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
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "messages": list(messages),
                "system": system,
                "tools": [t.name for t in tools],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout_s": timeout_s,
            }
        )

        if self._scripted:
            item = self._scripted.popleft()
            if isinstance(item, Exception):
                raise item
            return item

        last_user = next(
            (m.content for m in reversed(list(messages)) if m.role == "user"),
            "",
        )
        return LLMResponse(
            text=f"[fake:{model}] {last_user}",
            provider=self.name,
            model=model,
            tier=self.tier,
            usage=Usage(self._input_tokens, self._output_tokens),
            latency_ms=1,
        )

    async def aclose(self) -> None:
        return None


def fake_response(
    text: str = "ok",
    *,
    provider: str = "fake",
    model: str = "fake-model",
    tier: ModelTier = ModelTier.T0_LOCAL,
    input_tokens: int = 100,
    output_tokens: int = 20,
    tool_uses: tuple[ToolUse, ...] = (),
) -> LLMResponse:
    """Testlarda javob yasash uchun qisqartma."""
    return LLMResponse(
        text=text,
        provider=provider,
        model=model,
        tier=tier,
        usage=Usage(input_tokens, output_tokens),
        latency_ms=1,
        tool_uses=tool_uses,
    )
