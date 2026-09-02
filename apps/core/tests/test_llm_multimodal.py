"""Multimodal (rasm) qo'llab-quvvatlash testlari — gap-analysis #11.

Ilgari `ChatMessage.content: str` faqat matn edi — rasm yuborib bo'lmasdi.
Bu fayl: ImageBlock → Anthropic/OpenAI-mos payload, va ModelRouter'ning
vision-filtrlashini tekshiradi.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.domain.enums import ModelTier, TaskClass
from zet.llm.anthropic import AnthropicProvider
from zet.llm.base import ChatMessage, ImageBlock, NoProviderAvailableError
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.openai_compat import OpenAICompatProvider
from zet.llm.router import ModelRouter

_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBD"  # haqiqiy JPEG bo'lishi shart emas — faqat blok mazmuni
)


def _fixed_now() -> datetime:
    return datetime(2026, 8, 12, 12, 0, 0, tzinfo=UTC)


class TestImageBlock:
    def test_default_media_type(self) -> None:
        img = ImageBlock(data=_TINY_JPEG_B64)
        assert img.media_type == "image/jpeg"

    def test_custom_media_type(self) -> None:
        img = ImageBlock(data=_TINY_JPEG_B64, media_type="image/png")
        assert img.media_type == "image/png"

    def test_chat_message_default_no_images(self) -> None:
        msg = ChatMessage(role="user", content="matn")
        assert msg.images == ()

    def test_chat_message_with_images(self) -> None:
        img = ImageBlock(data=_TINY_JPEG_B64)
        msg = ChatMessage(role="user", content="Bu nima?", images=(img,))
        assert len(msg.images) == 1
        assert msg.images[0].data == _TINY_JPEG_B64


class TestAnthropicImagePayload:
    @respx.mock
    async def test_image_block_sent(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Bu mushuk"}],
                    "usage": {"input_tokens": 100, "output_tokens": 10},
                    "stop_reason": "end_turn",
                },
            )
        )
        img = ImageBlock(data=_TINY_JPEG_B64, media_type="image/jpeg")
        messages = [ChatMessage(role="user", content="Bu nima?", images=(img,))]

        await AnthropicProvider("kalit").complete(model="claude-haiku-4-5", messages=messages)

        body = json.loads(route.calls[0].request.read())
        blocks = body["messages"][0]["content"]
        assert blocks[0]["type"] == "image"
        assert blocks[0]["source"]["type"] == "base64"
        assert blocks[0]["source"]["media_type"] == "image/jpeg"
        assert blocks[0]["source"]["data"] == _TINY_JPEG_B64
        assert blocks[1]["type"] == "text"
        assert blocks[1]["text"] == "Bu nima?"

    @respx.mock
    async def test_image_without_text(self) -> None:
        route = respx.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )
        )
        img = ImageBlock(data=_TINY_JPEG_B64)
        messages = [ChatMessage(role="user", content="", images=(img,))]

        await AnthropicProvider("kalit").complete(model="m", messages=messages)

        body = json.loads(route.calls[0].request.read())
        blocks = body["messages"][0]["content"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "image"


class TestOpenAICompatImagePayload:
    @respx.mock
    async def test_image_url_sent(self) -> None:
        base = "https://api.example.com/v1"
        route = respx.post(f"{base}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Bu it"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        )
        img = ImageBlock(data=_TINY_JPEG_B64, media_type="image/png")
        messages = [ChatMessage(role="user", content="Bu nima?", images=(img,))]

        provider = OpenAICompatProvider(
            name="google", tier=ModelTier.T1_FREE, base_url=base, api_key="k"
        )
        await provider.complete(model="m", messages=messages)

        body = json.loads(route.calls[0].request.read())
        content = body["messages"][0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert content[1]["type"] == "text"

    @respx.mock
    async def test_no_images_content_stays_plain_string(self) -> None:
        """Rasm yo'q bo'lsa — content oddiy string (eski xatti-harakat buzilmaydi)."""
        base = "https://api.example.com/v1"
        route = respx.post(f"{base}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        )
        provider = OpenAICompatProvider(
            name="google", tier=ModelTier.T1_FREE, base_url=base, api_key="k"
        )
        await provider.complete(model="m", messages=[ChatMessage(role="user", content="salom")])

        body = json.loads(route.calls[0].request.read())
        assert body["messages"][0]["content"] == "salom"


class TestRouterVisionFiltering:
    def _router(self, session: AsyncSession, providers: dict) -> ModelRouter:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        return ModelRouter(
            providers=providers, session=session, settings=settings, now_fn=_fixed_now
        )

    async def test_skips_non_vision_provider(self, session: AsyncSession) -> None:
        """ollama:qwen3-8b (SIMPLE'ning birinchi nomzodi) vision qo'llamaydi.

        Rasm bilan chaqirilsa, ollama skip bo'ladi; boshqa provider yo'qligi
        uchun NoProviderAvailableError kutiladi — bu vision filtri haqiqatan
        ishlayotganini isbotlaydi (aks holda ollama javob berardi).
        """
        provider = FakeProvider(name="ollama", scripted=[fake_response(text="tavsif")])
        router = self._router(session, {"ollama": provider})
        img = ImageBlock(data=_TINY_JPEG_B64)
        messages = [ChatMessage(role="user", content="Rasmda nima bor?", images=(img,))]

        try:
            await router.complete(task_class=TaskClass.SIMPLE, messages=messages)
            raise AssertionError("NoProviderAvailableError kutilgan edi")
        except NoProviderAvailableError as exc:
            assert "vision" in str(exc).lower()

    async def test_vision_capable_provider_used(self, session: AsyncSession) -> None:
        """Vision qo'llovchi provider (anthropic:haiku SIMPLE ro'yxatida yo'q,
        shu sababli VISION task_class ishlatiladi)."""
        provider = FakeProvider(name="google", scripted=[fake_response(text="Bu mushuk rasmi")])
        router = self._router(session, {"google": provider})
        img = ImageBlock(data=_TINY_JPEG_B64)
        messages = [ChatMessage(role="user", content="Bu nima?", images=(img,))]

        result = await router.complete(task_class=TaskClass.VISION, messages=messages)
        assert result.response.text == "Bu mushuk rasmi"

    async def test_no_images_does_not_filter(self, session: AsyncSession) -> None:
        """Rasm bo'lmasa — vision tekshiruvi ishlamaydi, oddiy marshrutlash."""
        provider = FakeProvider(name="ollama", scripted=[fake_response(text="javob")])
        router = self._router(session, {"ollama": provider})
        messages = [ChatMessage(role="user", content="oddiy savol")]

        result = await router.complete(task_class=TaskClass.SIMPLE, messages=messages)
        assert result.response.text == "javob"
