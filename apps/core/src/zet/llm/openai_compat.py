"""OpenAI-mos provayder — bitta klass, beshta xizmat.

Ollama, Groq, Google (Gemini OpenAI-mos endpoint), Mistral va OpenAI ning o'zi
bir xil `/chat/completions` shartnomasini gapiradi. Shuning uchun ular uchun
alohida klass yozish takrorlash bo'lardi — farq faqat `base_url` va kalitda.

Anthropic bundan chetda: uning tool-calling formati boshqacha (`llm/anthropic.py`).
"""

from __future__ import annotations

import json
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


def _to_openai_message(msg: ChatMessage) -> dict[str, Any]:
    if msg.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": msg.tool_call_id or "",
            "content": msg.content,
        }
    payload: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_uses:
        payload["tool_calls"] = [
            {
                "id": tu.id,
                "type": "function",
                "function": {"name": tu.name, "arguments": json.dumps(tu.arguments)},
            }
            for tu in msg.tool_uses
        ]
    return payload


def _to_openai_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.input_schema or {"type": "object", "properties": {}},
        },
    }


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> tuple[ToolUse, ...]:
    if not raw:
        return ()
    uses: list[ToolUse] = []
    for call in raw:
        fn = call.get("function", {})
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            # Model buzuq JSON qaytardi — xom holda uzatamiz, Executor hal qiladi
            args = {"__raw": raw_args}
        uses.append(
            ToolUse(
                id=str(call.get("id", "")),
                name=str(fn.get("name", "")),
                arguments=args if isinstance(args, dict) else {"__value": args},
            )
        )
    return tuple(uses)


class OpenAICompatProvider:
    """`/chat/completions` shartnomasini gapiradigan har qanday xizmat."""

    def __init__(
        self,
        name: str,
        tier: ModelTier,
        base_url: str,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        requires_key: bool = True,
    ) -> None:
        self.name = name
        self.tier = tier
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._requires_key = requires_key
        self._client = client
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        if self._requires_key:
            return bool(self._api_key)
        return bool(self._base_url)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(base_url=self._base_url, headers=headers)
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
            raise ProviderConfigError(f"{self.name}: kalit yoki manzil yo'q")

        payload: dict[str, Any] = {
            "model": model,
            "messages": (
                ([{"role": "system", "content": system}] if system else [])
                + [_to_openai_message(m) for m in messages]
            ),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [_to_openai_tool(t) for t in tools]

        started = time.perf_counter()
        try:
            response = await self._get_client().post(
                "/chat/completions", json=payload, timeout=timeout_s
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"{self.name}: timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self.name}: {exc}") from exc

        self._raise_for_status(response)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
            usage_raw = data.get("usage") or {}
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderUnavailableError(f"{self.name}: javob formati buzuq") from exc

        return LLMResponse(
            text=message.get("content") or "",
            provider=self.name,
            model=model,
            tier=self.tier,
            usage=Usage(
                input_tokens=int(usage_raw.get("prompt_tokens", 0)),
                output_tokens=int(usage_raw.get("completion_tokens", 0)),
            ),
            latency_ms=latency_ms,
            finish_reason=str(choice.get("finish_reason") or "stop"),
            tool_uses=_parse_tool_calls(message.get("tool_calls")),
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            raise RateLimitError(
                f"{self.name}: rate limit",
                retry_after_s=float(retry_after) if retry_after else None,
            )
        if response.status_code in (401, 403):
            raise ProviderConfigError(f"{self.name}: kalit rad etildi ({response.status_code})")
        if response.status_code >= 500:
            raise ProviderUnavailableError(f"{self.name}: {response.status_code}")
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"{self.name}: {response.status_code} {response.text[:200]}"
            )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
