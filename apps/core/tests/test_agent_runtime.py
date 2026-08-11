"""Bo'lim 3 — Agent Runtime testlari.

Tekshiriladi:
    - context assembly
    - tool loop (LLM → tool → natija → LLM)
    - A-07 tormozlar (max_steps, max_tool_calls, timeout)
    - allowlist enforcement
    - error handling
    - Research Agent integratsiya testi
"""

from __future__ import annotations

import pytest

from zet.agents.builtin.research import RESEARCH_AGENT_SPEC
from zet.agents.runtime import AgentRuntime
from zet.domain.agent import AgentSpec
from zet.domain.enums import ModelTier, PermissionLevel
from zet.llm.base import ToolUse, Usage
from zet.llm.fake import FakeProvider, LLMResponse, fake_response
from zet.tools.builtin.web_search import WebSearchTool
from zet.tools.registry import ToolRegistry


def _make_runtime(
    scripted: list[LLMResponse | Exception] | None = None,
    tools: list | None = None,
) -> AgentRuntime:
    """Test uchun runtime yaratish."""
    provider = FakeProvider(scripted=scripted or [])
    registry = ToolRegistry()
    if tools:
        for tool in tools:
            registry.register(tool)
    return AgentRuntime(provider=provider, tool_registry=registry)


def _simple_spec(
    name: str = "test_agent",
    tools: list[str] | None = None,
    max_steps: int = 5,
    max_tool_calls: int = 10,
    timeout_s: int = 120,
) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="Test agent",
        system_prompt="Sen test agentisan.",
        tool_allowlist=tools or [],
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
        timeout_s=timeout_s,
    )


class TestBasicRuntime:
    @pytest.mark.asyncio()
    async def test_simple_response(self) -> None:
        """LLM javob beradi, tool yo'q — to'g'ridan-to'g'ri qaytaradi."""
        runtime = _make_runtime(scripted=[fake_response("Hisobot tayyor")])
        spec = _simple_spec()

        result = await runtime.run(spec, "Nimadur qidirib ber")

        assert result.success
        assert result.output == "Hisobot tayyor"
        assert result.tool_calls_count == 0
        assert result.steps_count == 1

    @pytest.mark.asyncio()
    async def test_no_scripted_uses_echo(self) -> None:
        """Scripted javob yo'q — echo qaytaradi."""
        runtime = _make_runtime()
        spec = _simple_spec()

        result = await runtime.run(spec, "Salom")

        assert result.success
        assert "Salom" in result.output

    @pytest.mark.asyncio()
    async def test_context_assembly(self) -> None:
        """Kontekst to'g'ri yig'iladi."""
        provider = FakeProvider()
        registry = ToolRegistry()
        runtime = AgentRuntime(provider=provider, tool_registry=registry)
        spec = _simple_spec()

        await runtime.run(spec, "Test vazifa")

        assert len(provider.calls) == 1
        call = provider.calls[0]
        assert call["system"] == "Sen test agentisan."
        messages = call["messages"]
        assert any(m.content == "Test vazifa" for m in messages)  # type: ignore[union-attr]


class TestToolLoop:
    @pytest.mark.asyncio()
    async def test_tool_call_and_response(self) -> None:
        """LLM tool chaqiradi → tool bajariladi → LLM javob beradi."""
        # 1. LLM web.search chaqiradi
        tool_call_response = LLMResponse(
            text="Qidiraman...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="call_1", name="web.search", arguments={"query": "Python"}),),
        )
        # 2. LLM yakuniy javob
        final_response = fake_response("Python haqida hisobot")

        runtime = _make_runtime(
            scripted=[tool_call_response, final_response],
            tools=[WebSearchTool()],
        )
        spec = _simple_spec(tools=["web.search"])

        result = await runtime.run(spec, "Python haqida qidir")

        assert result.success
        assert result.output == "Python haqida hisobot"
        assert result.tool_calls_count == 1
        assert result.steps_count == 2

    @pytest.mark.asyncio()
    async def test_multiple_tool_calls(self) -> None:
        """Bir nechta tool chaqiruv."""
        tool_response1 = LLMResponse(
            text="Birinchi qidiruv...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="call_1", name="web.search", arguments={"query": "q1"}),),
        )
        tool_response2 = LLMResponse(
            text="Ikkinchi qidiruv...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="call_2", name="web.search", arguments={"query": "q2"}),),
        )
        final = fake_response("Yakuniy hisobot")

        runtime = _make_runtime(
            scripted=[tool_response1, tool_response2, final],
            tools=[WebSearchTool()],
        )
        spec = _simple_spec(tools=["web.search"])

        result = await runtime.run(spec, "Ikki mavzu")

        assert result.success
        assert result.tool_calls_count == 2
        assert result.steps_count == 3

    @pytest.mark.asyncio()
    async def test_tool_not_in_allowlist(self) -> None:
        """Allowlist da bo'lmagan tool chaqiruvi rad etiladi."""
        tool_call = LLMResponse(
            text="Chaqiraman...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="call_1", name="shell.exec", arguments={"command": "rm -rf /"}),),
        )
        final = fake_response("OK")

        runtime = _make_runtime(
            scripted=[tool_call, final],
            tools=[WebSearchTool()],
        )
        # Allowlist faqat web.search — shell.exec yo'q
        spec = _simple_spec(tools=["web.search"])

        result = await runtime.run(spec, "Test")
        # Tool rad etiladi lekin agent davom etadi
        assert result.success
        assert result.tool_calls_count == 1  # Chaqiruv amalga oshdi (xato bilan)


class TestBrakes:
    """A-07 tormozlar testlari."""

    @pytest.mark.asyncio()
    async def test_max_steps_limit(self) -> None:
        """max_steps ga yetganda to'xtaydi."""
        # Har doim tool chaqiradigan javob
        tool_call = LLMResponse(
            text="Yana...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="call_x", name="web.search", arguments={"query": "test"}),),
        )
        runtime = _make_runtime(
            scripted=[tool_call] * 5,
            tools=[WebSearchTool()],
        )
        spec = _simple_spec(tools=["web.search"], max_steps=3)

        result = await runtime.run(spec, "Cheksiz qidirish")

        assert not result.success
        assert "qadamga yetdi" in (result.error or "")
        assert result.steps_count == 3

    @pytest.mark.asyncio()
    async def test_max_tool_calls_limit(self) -> None:
        """max_tool_calls ga yetganda to'xtaydi."""
        # Bitta qadamda 3 ta tool chaqiruv
        multi_tool = LLMResponse(
            text="Ko'p qidiruv...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(
                ToolUse(id="c1", name="web.search", arguments={"query": "q1"}),
                ToolUse(id="c2", name="web.search", arguments={"query": "q2"}),
                ToolUse(id="c3", name="web.search", arguments={"query": "q3"}),
            ),
        )
        runtime = _make_runtime(
            scripted=[multi_tool],
            tools=[WebSearchTool()],
        )
        spec = _simple_spec(tools=["web.search"], max_tool_calls=2)

        result = await runtime.run(spec, "Ko'p qidirish")

        assert not result.success
        assert "tool chaqiruviga yetdi" in (result.error or "")


class TestErrorHandling:
    @pytest.mark.asyncio()
    async def test_llm_error_caught(self) -> None:
        """LLM xatosi tutiladi."""
        runtime = _make_runtime(scripted=[RuntimeError("LLM ishlamadi")])
        spec = _simple_spec()

        result = await runtime.run(spec, "Test")

        assert not result.success
        assert "RuntimeError" in (result.error or "")

    @pytest.mark.asyncio()
    async def test_tool_not_in_registry(self) -> None:
        """Registry da bo'lmagan tool — xato qaytaradi."""
        tool_call = LLMResponse(
            text="...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="c1", name="nonexistent.tool", arguments={}),),
        )
        final = fake_response("OK")

        runtime = _make_runtime(scripted=[tool_call, final])
        spec = _simple_spec(tools=["nonexistent.tool"])

        result = await runtime.run(spec, "Test")
        assert result.success  # Agent xatolikdan o'tib davom etadi


class TestWebSearchTool:
    @pytest.mark.asyncio()
    async def test_basic_search(self) -> None:
        """Web search stub ishlaydi."""
        tool = WebSearchTool()
        result = await tool.execute({"query": "Python dasturlash"})
        assert result.success
        data = result.output
        assert data["query"] == "Python dasturlash"
        assert len(data["results"]) > 0

    @pytest.mark.asyncio()
    async def test_untrusted_output(self) -> None:
        """Web search natijasi UNTRUSTED."""
        tool = WebSearchTool()
        result = await tool.execute({"query": "test"})
        from zet.domain.enums import TrustLevel

        assert result.trust_level == TrustLevel.UNTRUSTED

    @pytest.mark.asyncio()
    async def test_max_results(self) -> None:
        """max_results parametri ishlaydi."""
        tool = WebSearchTool()
        result = await tool.execute({"query": "test", "max_results": 2})
        assert len(result.output["results"]) <= 2

    @pytest.mark.asyncio()
    async def test_read_permission(self) -> None:
        """Permission READ."""
        tool = WebSearchTool()
        assert tool.permission_level == PermissionLevel.READ

    @pytest.mark.asyncio()
    async def test_idempotent(self) -> None:
        tool = WebSearchTool()
        assert tool.idempotent


class TestResearchAgentSpec:
    def test_research_spec_valid(self) -> None:
        """Research agent spec to'g'ri yaratilgan."""
        spec = RESEARCH_AGENT_SPEC
        assert spec.name == "research"
        assert spec.permission_level == PermissionLevel.READ
        assert "web.search" in spec.tool_allowlist
        assert spec.max_steps == 5

    @pytest.mark.asyncio()
    async def test_research_agent_simple_run(self) -> None:
        """Research Agent oddiy run — tool chaqiruvsiz."""
        runtime = _make_runtime(
            scripted=[fake_response("## Hisobot: Python\n\nPython juda yaxshi til.")],
            tools=[WebSearchTool()],
        )

        result = await runtime.run(RESEARCH_AGENT_SPEC, "Python haqida qidir")

        assert result.success
        assert result.agent_name == "research"
        assert "Python" in result.output

    @pytest.mark.asyncio()
    async def test_research_agent_with_tool(self) -> None:
        """Research Agent tool bilan ishlaydi."""
        tool_call = LLMResponse(
            text="Qidiraman...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(
                ToolUse(
                    id="call_1",
                    name="web.search",
                    arguments={"query": "Python dasturlash"},
                ),
            ),
        )
        final = fake_response(
            "## Hisobot: Python\n\n### Manbalar\n1. [Python.org](https://python.org)"
        )

        runtime = _make_runtime(
            scripted=[tool_call, final],
            tools=[WebSearchTool()],
        )

        result = await runtime.run(RESEARCH_AGENT_SPEC, "Python haqida tadqiqot")

        assert result.success
        assert result.tool_calls_count == 1
        assert "Hisobot" in result.output
