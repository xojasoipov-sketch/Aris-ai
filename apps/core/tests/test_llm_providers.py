"""Z1.5 — HTTP provayderlar testlari (respx bilan, tarmoqqa chiqmasdan)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from zet.config import Settings
from zet.domain.enums import ModelTier
from zet.llm.anthropic import AnthropicProvider
from zet.llm.base import (
    ChatMessage,
    ProviderConfigError,
    ProviderUnavailableError,
    RateLimitError,
    ToolSpec,
    ToolUse,
)
from zet.llm.factory import build_providers
from zet.llm.openai_compat import OpenAICompatProvider

BASE = "https://api.example.com/v1"
MESSAGES = [ChatMessage(role="user", content="Salom")]
TOOLS = [
    ToolSpec(
        name="time.now",
        description="Hozirgi vaqt",
        input_schema={"type": "object", "properties": {}},
    )
]


def openai_payload(
    content: str | None = "Javob",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 34},
    }


def make_openai(**kw: Any) -> OpenAICompatProvider:
    kw.setdefault("name", "testprov")
    kw.setdefault("tier", ModelTier.T1_FREE)
    kw.setdefault("base_url", BASE)
    kw.setdefault("api_key", "kalit")
    return OpenAICompatProvider(**kw)


class TestOpenAICompat:
    @respx.mock
    async def test_successful_completion(self) -> None:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=openai_payload())
        )
        result = await make_openai().complete(model="m1", messages=MESSAGES, system="Sen ZETsan")

        assert result.text == "Javob"
        assert result.usage.input_tokens == 120
        assert result.usage.output_tokens == 34
        assert result.provider == "testprov"
        assert route.called

        body = json.loads(route.calls[0].request.read())
        assert body["messages"][0] == {"role": "system", "content": "Sen ZETsan"}
        assert body["messages"][1]["role"] == "user"

    @respx.mock
    async def test_tool_calls_parsed(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json=openai_payload(
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "time.now",
                                "arguments": '{"tz": "Asia/Tashkent"}',
                            },
                        }
                    ],
                ),
            )
        )
        result = await make_openai().complete(model="m1", messages=MESSAGES, tools=TOOLS)

        assert result.wants_tools
        assert result.tool_uses[0] == ToolUse(
            id="call_1", name="time.now", arguments={"tz": "Asia/Tashkent"}
        )
        assert result.text == ""

    @respx.mock
    async def test_broken_tool_arguments_do_not_crash(self) -> None:
        """Model buzuq JSON qaytarsa ham provayder yiqilmasligi kerak."""
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json=openai_payload(
                    content=None,
                    tool_calls=[
                        {
                            "id": "c1",
                            "function": {"name": "t", "arguments": "{buzuq json"},
                        }
                    ],
                ),
            )
        )
        result = await make_openai().complete(model="m1", messages=MESSAGES, tools=TOOLS)
        assert result.tool_uses[0].arguments["__raw"] == "{buzuq json"

    @respx.mock
    async def test_rate_limit_raises(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(429, headers={"retry-after": "12"}, json={})
        )
        with pytest.raises(RateLimitError) as exc:
            await make_openai().complete(model="m1", messages=MESSAGES)
        assert exc.value.retry_after_s == 12.0

    @respx.mock
    async def test_server_error_is_unavailable(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(503, json={}))
        with pytest.raises(ProviderUnavailableError):
            await make_openai().complete(model="m1", messages=MESSAGES)

    @respx.mock
    async def test_bad_key_is_config_error(self) -> None:
        """401 — qayta urinish foydasiz, boshqa provayderga o'tish kerak."""
        respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401, json={}))
        with pytest.raises(ProviderConfigError):
            await make_openai().complete(model="m1", messages=MESSAGES)

    @respx.mock
    async def test_timeout_is_unavailable(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ConnectTimeout("timeout"))
        with pytest.raises(ProviderUnavailableError, match="timeout"):
            await make_openai().complete(model="m1", messages=MESSAGES)

    @respx.mock
    async def test_malformed_response(self) -> None:
        respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json={"kutilmagan": "format"})
        )
        with pytest.raises(ProviderUnavailableError, match="format"):
            await make_openai().complete(model="m1", messages=MESSAGES)

    async def test_unconfigured_raises_without_network(self) -> None:
        with pytest.raises(ProviderConfigError):
            await make_openai(api_key=None).complete(model="m1", messages=MESSAGES)

    def test_local_provider_needs_no_key(self) -> None:
        """Ollama kalitsiz ishlaydi (ADR-0007)."""
        provider = make_openai(api_key=None, requires_key=False)
        assert provider.is_configured is True

    @respx.mock
    async def test_tool_result_message_shape(self) -> None:
        route = respx.post(f"{BASE}/chat/completions").mock(
            return_value=httpx.Response(200, json=openai_payload())
        )
        await make_openai().complete(
            model="m1",
            messages=[
                ChatMessage(role="user", content="soat necha?"),
                ChatMessage(
                    role="assistant",
                    tool_uses=(ToolUse(id="c1", name="time.now", arguments={}),),
                ),
                ChatMessage(role="tool", content="12:00", tool_call_id="c1"),
            ],
        )
        body = json.loads(route.calls[0].request.read())
        tool_msg = body["messages"][-1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "c1"

        assistant_msg = body["messages"][-2]
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "time.now"


class TestAnthropic:
    @respx.mock
    async def test_successful_completion(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Salom!"}],
                    "usage": {"input_tokens": 200, "output_tokens": 50},
                    "stop_reason": "end_turn",
                },
            )
        )
        result = await AnthropicProvider("kalit").complete(
            model="claude-haiku-4-5", messages=MESSAGES, system="Sen ZETsan"
        )

        assert result.text == "Salom!"
        assert result.usage.input_tokens == 200
        assert result.finish_reason == "end_turn"

        body = json.loads(route.calls[0].request.read())
        assert body["system"] == "Sen ZETsan"

    @respx.mock
    async def test_tool_use_parsed(self) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "Tekshiraman."},
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "time.now",
                            "input": {"tz": "UTC"},
                        },
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "stop_reason": "tool_use",
                },
            )
        )
        result = await AnthropicProvider("kalit").complete(
            model="m", messages=MESSAGES, tools=TOOLS
        )
        assert result.text == "Tekshiraman."
        assert result.tool_uses[0].name == "time.now"

    @respx.mock
    async def test_tool_result_becomes_user_block(self) -> None:
        """Anthropic'da tool natijasi `user` roli ichida keladi."""
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200, json={"content": [], "usage": {}, "stop_reason": "end_turn"}
            )
        )
        await AnthropicProvider("kalit").complete(
            model="m",
            messages=[ChatMessage(role="tool", content="12:00", tool_call_id="tu_1")],
        )
        body = json.loads(route.calls[0].request.read())
        block = body["messages"][0]["content"][0]
        assert body["messages"][0]["role"] == "user"
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "tu_1"
        assert block["content"] == "12:00"

    @respx.mock
    async def test_rate_limit(self) -> None:
        respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(429, json={})
        )
        with pytest.raises(RateLimitError):
            await AnthropicProvider("kalit").complete(model="m", messages=MESSAGES)

    async def test_unconfigured(self) -> None:
        provider = AnthropicProvider(None)
        assert provider.is_configured is False
        with pytest.raises(ProviderConfigError):
            await provider.complete(model="m", messages=MESSAGES)

    @respx.mock
    async def test_system_message_not_duplicated(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200, json={"content": [], "usage": {}, "stop_reason": "end_turn"}
            )
        )
        await AnthropicProvider("kalit").complete(
            model="m",
            messages=[
                ChatMessage(role="system", content="e'tiborsiz qoldirilishi kerak"),
                ChatMessage(role="user", content="salom"),
            ],
            system="haqiqiy system",
        )
        body = json.loads(route.calls[0].request.read())
        assert body["system"] == "haqiqiy system"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["content"][0]["text"] == "salom"


class TestFactory:
    def test_builds_every_catalog_provider(self) -> None:
        from zet.llm.catalog import CATALOG

        providers = build_providers(Settings(_env_file=None))  # type: ignore[call-arg]
        for spec in CATALOG.values():
            assert spec.provider in providers, f"{spec.provider} yaratilmagan"

    def test_ollama_configured_without_keys(self) -> None:
        providers = build_providers(Settings(_env_file=None))  # type: ignore[call-arg]
        assert providers["ollama"].is_configured is True
        assert providers["google"].is_configured is False

    def test_key_enables_provider(self) -> None:
        settings = Settings(_env_file=None, google_api_key="g", mistral_api_key="m")  # type: ignore[call-arg]
        providers = build_providers(settings)
        assert providers["google"].is_configured is True
        assert providers["mistral"].is_configured is True
        assert providers["groq"].is_configured is False
