"""Anthropic Messages API provayderi (T2/T3).

OpenAI shartnomasidan uch joyda farq qiladi:
    - `system` alohida maydon, xabarlar ro'yxatida emas
    - tool natijasi `user` roli ichida `tool_result` bloki sifatida qaytadi
    - javob `content` bloklar massivi (matn + `tool_use`)
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import httpx

from zet.domain.enums import ModelTier
from zet.llm.base import (
    ChatMessage,
    LLMResponse,
    ProviderConfigError,
    ProviderUnavailableError,
    RateLimitError,
    ToolSpec,
    ToolUse,
    Usage,
)

API_VERSION = "2023-06-01"


def _to_anthropic_messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """ZET xabarlarini Anthropic formatiga o'girish."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            continue  # `system` alohida uzatiladi

        if msg.role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id or "",
                            "content": msg.content,
                        }
                    ],
                }
            )
            continue

        blocks: list[dict[str, Any]] = []
        for img in msg.images:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": img.data,
                    },
                }
            )
        if msg.content:
            blocks.append({"type": "text", "text": msg.content})
        for tu in msg.tool_uses:
            blocks.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.arguments})
        result.append({"role": msg.role, "content": blocks or [{"type": "text", "text": ""}]})
    return result


class AnthropicProvider:
    """Claude modellari uchun provayder."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        *,
        tier: ModelTier = ModelTier.T2_CHEAP,
        base_url: str = "https://api.anthropic.com/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.tier = tier
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "x-api-key": self._api_key or "",
                    "anthropic-version": API_VERSION,
                    "Content-Type": "application/json",
                },
            )
        return self._client

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
        if not self.is_configured:
            raise ProviderConfigError("anthropic: ZET_ANTHROPIC_API_KEY yo'q")

        payload: dict[str, Any] = {
            "model": model,
            "messages": _to_anthropic_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema or {"type": "object", "properties": {}},
                }
                for t in tools
            ]

        started = time.perf_counter()
        try:
            response = await self._get_client().post("/messages", json=payload, timeout=timeout_s)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("anthropic: timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"anthropic: {exc}") from exc

        self._raise_for_status(response)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            data = response.json()
            blocks = data.get("content") or []
            usage_raw = data.get("usage") or {}
        except ValueError as exc:
            raise ProviderUnavailableError("anthropic: javob formati buzuq") from exc

        text_parts: list[str] = []
        tool_uses: list[ToolUse] = []
        for block in blocks:
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                raw_input = block.get("input")
                tool_uses.append(
                    ToolUse(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=raw_input if isinstance(raw_input, dict) else {},
                    )
                )

        return LLMResponse(
            text="".join(text_parts),
            provider=self.name,
            model=model,
            tier=self.tier,
            usage=Usage(
                input_tokens=int(usage_raw.get("input_tokens", 0)),
                output_tokens=int(usage_raw.get("output_tokens", 0)),
            ),
            latency_ms=latency_ms,
            finish_reason=str(data.get("stop_reason") or "stop"),
            tool_uses=tuple(tool_uses),
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise RateLimitError(
                "anthropic: rate limit",
                retry_after_s=float(retry_after) if retry_after else None,
            )
        if response.status_code in (401, 403):
            raise ProviderConfigError(f"anthropic: kalit rad etildi ({response.status_code})")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"anthropic: {response.status_code}")
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"anthropic: {response.status_code} {response.text[:200]}"
            )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
