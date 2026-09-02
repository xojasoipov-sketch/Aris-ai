"""AgentRuntime — tool natijasidagi rasmni ImageBlock sifatida forward qilish.

gap-analysis #11: ilgari kamera/rasm tool natijasi bo'lsa ham, keyingi LLM
chaqiruviga rasm hech qachon qo'shilmasdi (faqat matn sifatida stringify
qilinardi). Endi `camera.snapshot`ga o'xshash `has_image`li natijalar
avtomatik `ChatMessage(images=(...))` sifatida qo'shiladi.
"""

from __future__ import annotations

from zet.agents.runtime import AgentRuntime
from zet.devices.camera import StubCamera
from zet.domain.agent import AgentSpec
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel
from zet.llm.base import LLMResponse, ToolUse, Usage
from zet.llm.fake import FakeProvider, fake_response
from zet.tools.builtin.camera import CameraSnapshotTool
from zet.tools.registry import ToolRegistry


def _vision_spec() -> AgentSpec:
    return AgentSpec(
        name="vision_test",
        description="Test vision agent",
        system_prompt="Sen vision agentisan.",
        tool_allowlist=["camera.snapshot"],
        permission_level=PermissionLevel.READ,
        trust_level=TrustLevel.SYSTEM,
        max_steps=5,
        max_tool_calls=10,
        timeout_s=60,
    )


class TestImageForwarding:
    async def test_camera_snapshot_forwarded_as_image(self) -> None:
        tool_call = LLMResponse(
            text="Kamerani tekshiraman...",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="c1", name="camera.snapshot", arguments={"camera_id": "front"}),),
        )
        final = fake_response("Eshik oldida hech kim yo'q")

        provider = FakeProvider(scripted=[tool_call, final])
        registry = ToolRegistry()
        registry.register(CameraSnapshotTool(provider=StubCamera()))
        runtime = AgentRuntime(provider=provider, tool_registry=registry)

        result = await runtime.run(_vision_spec(), "Kamerada nima bor?")

        assert result.success
        assert result.output == "Eshik oldida hech kim yo'q"

        # Ikkinchi LLM chaqiruvi (final javobdan oldin) rasm bilan xabar olgan bo'lishi kerak
        second_call_messages = provider.calls[1]["messages"]
        image_messages = [m for m in second_call_messages if m.images]
        assert len(image_messages) == 1
        assert image_messages[0].role == "user"
        assert image_messages[0].images[0].media_type == "image/jpeg"

    async def test_tool_result_text_omits_raw_base64(self) -> None:
        """Tool-role xabarida katta base64 satri takrorlanmaydi."""
        tool_call = LLMResponse(
            text="",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="c1", name="camera.snapshot", arguments={"camera_id": "front"}),),
        )
        final = fake_response("ok")

        provider = FakeProvider(scripted=[tool_call, final])
        registry = ToolRegistry()
        registry.register(CameraSnapshotTool(provider=StubCamera()))
        runtime = AgentRuntime(provider=provider, tool_registry=registry)

        await runtime.run(_vision_spec(), "test")

        second_call_messages = provider.calls[1]["messages"]
        tool_messages = [m for m in second_call_messages if m.role == "tool"]
        assert len(tool_messages) == 1
        assert "image_b64" not in tool_messages[0].content
        assert "Rasm olindi" in tool_messages[0].content

    async def test_non_image_tool_does_not_add_image_message(self) -> None:
        """time.now kabi rasm bermaydigan tool — qo'shimcha rasm xabari yo'q."""
        from zet.tools.builtin.time_now import TimeNowTool

        tool_call = LLMResponse(
            text="",
            provider="fake",
            model="fake",
            tier=ModelTier.T0_LOCAL,
            usage=Usage(100, 20),
            latency_ms=1,
            tool_uses=(ToolUse(id="c1", name="time.now", arguments={}),),
        )
        final = fake_response("ok")

        provider = FakeProvider(scripted=[tool_call, final])
        registry = ToolRegistry()
        registry.register(TimeNowTool())
        spec = AgentSpec(
            name="t",
            description="t",
            system_prompt="t",
            tool_allowlist=["time.now"],
            max_steps=5,
            max_tool_calls=10,
            timeout_s=60,
        )
        runtime = AgentRuntime(provider=provider, tool_registry=registry)

        await runtime.run(spec, "test")

        second_call_messages = provider.calls[1]["messages"]
        assert not any(m.images for m in second_call_messages)
