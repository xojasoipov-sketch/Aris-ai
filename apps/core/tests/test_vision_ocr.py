"""VisionOcrTool testlari — respx bilan Gemini API'siga chiqmasdan.

NEGA. Tool haqiqiy Gemini kaliti bo'lmasa ham `ToolRegistry`da turishi
va Planner'ga ko'rinishi kerak (`video.learn` bilan bir xil naqsh),
lekin chaqirilganda tushunarli xato bermog'i shart. Mock javob orqali
esa muvaffaqiyat, xatolar va nol vaqtga uchramaydigan chekka holatlar
qamrab olinadi.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
import respx

from zet.tools.base import ToolError, ToolQuotaError
from zet.tools.builtin import build_default_registry
from zet.tools.builtin.vision_ocr import DEFAULT_MODEL, VisionOcrTool

_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent"
)
_TINY_IMAGE = base64.b64encode(b"\xff\xd8\xff\xe0not-really-jpeg\xff\xd9").decode()


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


class TestConstruction:
    def test_properties(self) -> None:
        tool = VisionOcrTool(api_key="k")
        assert tool.name == "vision.ocr"
        assert tool.is_real is True
        assert tool.timeout_s == 45
        assert tool.idempotent is True

    def test_without_api_key_is_not_real(self) -> None:
        assert VisionOcrTool().is_real is False


class TestMissingApiKey:
    async def test_missing_key_raises_tool_error(self) -> None:
        tool = VisionOcrTool(api_key=None)
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success
        assert result.error is not None
        assert "gemini_api_key sozlanmagan" in result.error


class TestInvalidInput:
    async def test_neither_input_raises(self) -> None:
        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({})
        assert not result.success
        assert "shart" in result.error

    async def test_both_inputs_raises(self) -> None:
        tool = VisionOcrTool(api_key="k")
        result = await tool.execute(
            {"image_url": "https://x/y.jpg", "image_bytes_base64": _TINY_IMAGE}
        )
        assert not result.success
        assert "birga berilmaydi" in result.error

    async def test_invalid_base64_raises(self) -> None:
        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": "not@@@base64!!!"})
        assert not result.success
        assert "base64" in result.error


class TestSuccessfulOcr:
    @respx.mock
    async def test_ocr_returns_text_language_confidence(self) -> None:
        respx.post(_ENDPOINT).mock(
            return_value=_ok_response(
                '{"text": "Salom dunyo", "language": "uz", "confidence": 0.91}'
            )
        )

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert result.success
        assert result.output["text"] == "Salom dunyo"
        assert result.output["language"] == "uz"
        assert result.output["confidence"] == pytest.approx(0.91)
        # `x-goog-api-key` header yuborilgan.
        request = respx.calls.last.request
        assert request.headers.get("x-goog-api-key") == "k"

    @respx.mock
    async def test_ocr_from_image_url_uses_file_data(self) -> None:
        """URL berilganda payload'da `file_data.file_uri` ishlatiladi."""
        respx.post(_ENDPOINT).mock(
            return_value=_ok_response('{"text": "hello", "language": "en", "confidence": 0.99}')
        )

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_url": "https://example.com/a.jpg"})

        assert result.success
        # Payload tuzilishini tekshiramiz.
        payload = respx.calls.last.request.content
        assert b"file_data" in payload
        assert b"https://example.com/a.jpg" in payload

    @respx.mock
    async def test_ocr_from_bytes_uses_inline_data(self) -> None:
        respx.post(_ENDPOINT).mock(
            return_value=_ok_response('{"text": "abc", "language": "en", "confidence": 0.7}')
        )

        tool = VisionOcrTool(api_key="k")
        await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        payload = respx.calls.last.request.content
        assert b"inline_data" in payload

    @respx.mock
    async def test_ocr_handles_markdown_wrapped_json(self) -> None:
        """Model ba'zan JSON'ni ```json blokiga o'raydi — o'qib chiqamiz."""
        respx.post(_ENDPOINT).mock(
            return_value=_ok_response(
                '```json\n{"text": "wrapped", "language": "uz", "confidence": null}\n```'
            )
        )
        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert result.success
        assert result.output["text"] == "wrapped"
        assert result.output["confidence"] is None


class TestApiErrors:
    @respx.mock
    async def test_http_500_returns_tool_error(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=httpx.Response(500, text="server oops"))

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success
        assert "HTTP 500" in result.error

    @respx.mock
    async def test_429_returns_quota_error(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=httpx.Response(429, text="rate limited"))

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success
        # ToolQuotaError → retryable=False.
        assert result.retryable is False
        assert "kvotasi" in result.error

    @respx.mock
    async def test_network_error_returns_tool_error(self) -> None:
        respx.post(_ENDPOINT).mock(side_effect=httpx.ConnectError("no dns"))

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success
        assert "tarmoq" in result.error

    @respx.mock
    async def test_unexpected_shape_returns_error(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json={"candidates": []}))

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success
        assert "javob shaklini" in result.error

    @respx.mock
    async def test_non_json_response_bubbles_error(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=_ok_response("just some plain text without JSON"))

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success

    @respx.mock
    async def test_bare_json_string_response_does_not_crash(self) -> None:
        """JB-16 CASE A regression: model top-darajada dict EMAS, bitta
        JSON satr qaytarsa (masalan "rasmda matn topilmadi" — sintaktik
        jihatdan TO'G'RI JSON, lekin obyekt emas), tool ichki
        `AttributeError: 'str' object has no attribute 'get'` bilan
        yiqilmasligi, balki tushunarli `ToolError` bilan halol
        muvaffaqiyatsizlikka uchrashi kerak."""
        respx.post(_ENDPOINT).mock(return_value=_ok_response('"rasmda matn topilmadi"'))

        tool = VisionOcrTool(api_key="k")
        result = await tool.execute({"image_bytes_base64": _TINY_IMAGE})

        assert not result.success
        assert result.error is not None
        assert "AttributeError" not in result.error
        assert "dict emas" in result.error or "topilmadi" in result.error


class TestRegistry:
    def test_registered_in_default_registry(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path, gemini_api_key="k")
        assert "vision.ocr" in registry.tool_names()
        tool = registry.get("vision.ocr")
        assert isinstance(tool, VisionOcrTool)
        assert tool.is_real is True

    def test_registered_even_without_key(self, tmp_path: Path) -> None:
        """Kalit yo'q bo'lsa ham tool ro'yxatda — Planner ko'radi."""
        registry = build_default_registry(notes_dir=tmp_path)
        assert "vision.ocr" in registry.tool_names()
        assert registry.get("vision.ocr").is_real is False


class TestPermissionsCatalog:
    def test_vision_ocr_in_eval_permissions(self) -> None:
        from zet.agents.eval import TOOL_PERMISSIONS
        from zet.domain.enums import PermissionLevel

        assert TOOL_PERMISSIONS["vision.ocr"] == PermissionLevel.READ

    def test_vision_agent_allowlist_includes_ocr(self) -> None:
        from zet.agents.builtin.vision import VISION_AGENT_SPEC

        assert "vision.ocr" in VISION_AGENT_SPEC.tool_allowlist


# `ToolError`/`ToolQuotaError` importlar linter uchun ishlatilganini
# ko'rsatamiz — `_build_image_part` metodining darajali xato turlari
# yuqori qatlamda `ToolResult.retryable`ga aylanadi (yuqoridagi test).
_ = (ToolError, ToolQuotaError)
