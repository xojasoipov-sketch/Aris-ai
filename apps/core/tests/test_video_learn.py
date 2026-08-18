"""VideoLearnTool testlari — respx bilan Gemini API'siga chiqmasdan.

`test_vision_ocr.py` bilan bir xil naqsh (ikkala tool ham
`_extract_json()`ning eski, mustaqil nusxalarini ishlatardi — JB-16
ularni yagona `zet.tools.json_extract.extract_json_object()`ga
birlashtirdi). Bu fayl ilgari umuman yo'q edi — `video.learn` HECH
QANDAY test bilan qoplanmagan edi.
"""

from __future__ import annotations

import httpx
import respx

from zet.tools.builtin.video_learn import DEFAULT_MODEL, VideoLearnTool, is_supported_url

_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{DEFAULT_MODEL}:generateContent"
)
_URL = "https://www.youtube.com/watch?v=abc123defgh"

_VALID_KNOWLEDGE = (
    '{"title": "T", "topic": "M", "summary": "S", "key_points": ["a"], '
    '"actionable": [], "terms": [], "quotes": [], "teaching_notes": [], "gaps": []}'
)


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
    )


class TestConstruction:
    def test_properties(self) -> None:
        tool = VideoLearnTool(api_key="k")
        assert tool.name == "video.learn"
        assert tool.is_real is True
        assert tool.timeout_s == 300

    def test_without_api_key_is_not_real(self) -> None:
        assert VideoLearnTool().is_real is False


class TestUrlSupport:
    def test_youtube_watch_url_supported(self) -> None:
        assert is_supported_url(_URL) is True

    def test_non_youtube_url_unsupported(self) -> None:
        assert is_supported_url("https://vimeo.com/12345") is False


class TestMissingApiKey:
    async def test_missing_key_raises_tool_error(self) -> None:
        tool = VideoLearnTool(api_key=None)
        result = await tool.execute({"url": _URL})
        assert not result.success
        assert "ZET_GOOGLE_API_KEY" in result.error


class TestUnsupportedUrl:
    async def test_non_youtube_url_raises(self) -> None:
        tool = VideoLearnTool(api_key="k")
        result = await tool.execute({"url": "https://vimeo.com/12345"})
        assert not result.success
        assert "YouTube" in result.error


class TestSuccessfulLearn:
    @respx.mock
    async def test_returns_structured_knowledge(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=_ok_response(_VALID_KNOWLEDGE))

        tool = VideoLearnTool(api_key="k")
        result = await tool.execute({"url": _URL})

        assert result.success
        assert result.output["title"] == "T"
        assert result.output["source_url"] == _URL

    @respx.mock
    async def test_handles_markdown_wrapped_json(self) -> None:
        respx.post(_ENDPOINT).mock(
            return_value=_ok_response(f"```json\n{_VALID_KNOWLEDGE}\n```")
        )
        tool = VideoLearnTool(api_key="k")
        result = await tool.execute({"url": _URL})

        assert result.success
        assert result.output["title"] == "T"


class TestApiErrors:
    @respx.mock
    async def test_429_returns_quota_error(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=httpx.Response(429, text="rate limited"))

        tool = VideoLearnTool(api_key="k")
        result = await tool.execute({"url": _URL})

        assert not result.success
        assert result.retryable is False

    @respx.mock
    async def test_bare_json_string_response_does_not_crash(self) -> None:
        """JB-16 CASE A regression — `video_learn.py`'s eski `_extract_json()`
        top-darajadagi qiymatni `dict` deb TEKSHIRMASDI, shuning uchun
        model bitta JSON satr qaytarsa `knowledge["source_url"] = url`
        satrida `TypeError: 'str' object does not support item
        assignment` bilan yiqilardi. Endi tushunarli `ToolError`."""
        respx.post(_ENDPOINT).mock(return_value=_ok_response('"video ochilmadi"'))

        tool = VideoLearnTool(api_key="k")
        result = await tool.execute({"url": _URL})

        assert not result.success
        assert result.error is not None
        assert "TypeError" not in result.error
        assert "AttributeError" not in result.error

    @respx.mock
    async def test_unexpected_shape_returns_error(self) -> None:
        respx.post(_ENDPOINT).mock(return_value=httpx.Response(200, json={"candidates": []}))

        tool = VideoLearnTool(api_key="k")
        result = await tool.execute({"url": _URL})

        assert not result.success
        assert "javob shaklini" in result.error
