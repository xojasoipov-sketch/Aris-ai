"""Bulut embedding provayderlari testlari (Z39.2).

Railway'da Ollama yo'q — semantik qidiruv produksiyada jim o'chiq
turgan edi. Bu fayl bulut provayderlarini va eng nozik joyni —
**model belgisi**ni tekshiradi: `bge-m3` ham, `mistral-embed` ham
1024 o'lchamli, ya'ni o'lcham tekshiruvi ularni ajratmaydi.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zet.api.deps import _resolve_embedding_provider
from zet.config import Env, Settings
from zet.memory.embeddings import (
    GeminiEmbeddingProvider,
    MistralEmbeddingProvider,
    NullEmbeddingProvider,
    OllamaEmbeddingProvider,
)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
)
MISTRAL_URL = "https://api.mistral.ai/v1/embeddings"


class TestGemini:
    """Google Generative Language API."""

    @respx.mock
    async def test_returns_vector(self) -> None:
        respx.post(GEMINI_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.1, 0.2, 0.3]}})
        )
        provider = GeminiEmbeddingProvider(api_key="k")
        assert await provider.embed("salom") == [0.1, 0.2, 0.3]

    @respx.mock
    async def test_http_error_fails_open(self) -> None:
        """Kvota tugasa ham qidiruv yiqilmaydi — kalit-so'zga tushadi."""
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(429))
        assert await GeminiEmbeddingProvider(api_key="k").embed("salom") is None

    @respx.mock
    async def test_timeout_fails_open(self) -> None:
        respx.post(GEMINI_URL).mock(side_effect=httpx.TimeoutException("t"))
        assert await GeminiEmbeddingProvider(api_key="k").embed("salom") is None

    @respx.mock
    async def test_malformed_response_fails_open(self) -> None:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json={"kutilmagan": 1}))
        assert await GeminiEmbeddingProvider(api_key="k").embed("salom") is None

    async def test_blank_text_skips_network(self) -> None:
        """Bo'sh matn uchun API chaqirilmaydi (kvota tejaladi)."""
        assert await GeminiEmbeddingProvider(api_key="k").embed("   ") is None

    def test_model_id_names_the_vector_space(self) -> None:
        assert GeminiEmbeddingProvider(api_key="k").model_id == "gemini:gemini-embedding-001"

    @respx.mock
    async def test_key_travels_in_header_not_url(self) -> None:
        """Kalit URL'da bo'lmasligi SHART.

        Jonli Railway log'ida kalit ochiq ko'ringan edi: httpx xato
        matniga to'liq URL'ni qo'shadi, `?key=...` esa shu URL ichida
        edi. Header'dagi kalit xato matniga tushmaydi.
        """
        route = respx.post(GEMINI_URL).mock(
            return_value=httpx.Response(200, json={"embedding": {"values": [0.1]}})
        )
        await GeminiEmbeddingProvider(api_key="MAXFIY-KALIT").embed("salom")

        request = route.calls.last.request
        assert "MAXFIY-KALIT" not in str(request.url)
        assert request.headers["x-goog-api-key"] == "MAXFIY-KALIT"

    @respx.mock
    async def test_key_absent_from_logged_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Xato log'ida ham kalit chiqmasin."""
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(404))
        await GeminiEmbeddingProvider(api_key="MAXFIY-KALIT").embed("salom")

        assert "MAXFIY-KALIT" not in caplog.text


class TestMistral:
    """Mistral API."""

    @respx.mock
    async def test_returns_vector(self) -> None:
        respx.post(MISTRAL_URL).mock(
            return_value=httpx.Response(200, json={"data": [{"embedding": [1.0, 2.0]}]})
        )
        assert await MistralEmbeddingProvider(api_key="k").embed("salom") == [1.0, 2.0]

    @respx.mock
    async def test_empty_data_fails_open(self) -> None:
        respx.post(MISTRAL_URL).mock(return_value=httpx.Response(200, json={"data": []}))
        assert await MistralEmbeddingProvider(api_key="k").embed("salom") is None

    @respx.mock
    async def test_http_error_fails_open(self) -> None:
        respx.post(MISTRAL_URL).mock(return_value=httpx.Response(500))
        assert await MistralEmbeddingProvider(api_key="k").embed("salom") is None

    def test_model_id_names_the_vector_space(self) -> None:
        assert MistralEmbeddingProvider(api_key="k").model_id == "mistral:mistral-embed"


class TestModelIdDistinctness:
    """Bir xil o'lchamli, boshqa fazoli modellar ajratilishi SHART."""

    def test_ollama_and_mistral_have_different_ids(self) -> None:
        """Ikkalasi ham 1024 o'lchamli — faqat belgi ularni ajratadi."""
        ollama = OllamaEmbeddingProvider(base_url="http://x", model="bge-m3")
        mistral = MistralEmbeddingProvider(api_key="k")
        assert ollama.model_id != mistral.model_id

    def test_every_provider_exposes_a_model_id(self) -> None:
        providers = [
            OllamaEmbeddingProvider(base_url="http://x", model="bge-m3"),
            GeminiEmbeddingProvider(api_key="k"),
            MistralEmbeddingProvider(api_key="k"),
            NullEmbeddingProvider(),
        ]
        ids = [p.model_id for p in providers]
        assert all(ids)
        assert len(set(ids)) == len(ids)


class TestNullProvider:
    """Hech narsa sozlanmaganda — halol o'chiq holat."""

    async def test_always_none(self) -> None:
        assert await NullEmbeddingProvider().embed("salom") is None

    async def test_aclose_is_safe(self) -> None:
        await NullEmbeddingProvider().aclose()


def _settings(**kwargs: object) -> Settings:
    """Test uchun Settings — bulut kalitlari ANIQ bo'shatiladi.

    `Settings` `.env` faylini ham o'qiydi. Kalitlarni aniq `None`
    qilmasak, testlar ishlab chiquvchining haqiqiy `ZET_GOOGLE_API_KEY`iga
    bog'lanib qolardi va boshqa mashinada boshqacha natija berardi.
    """
    base: dict[str, object] = {
        "anthropic_api_key": "k",
        "google_api_key": None,
        "mistral_api_key": None,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


class TestProviderSelection:
    """`auto` qoidasi: bulutda Ollama yo'q, dev'da bor."""

    def test_dev_prefers_local_ollama(self) -> None:
        settings = _settings(env=Env.DEV, google_api_key="g")
        assert isinstance(_resolve_embedding_provider(settings), OllamaEmbeddingProvider)

    def test_prod_prefers_gemini(self) -> None:
        settings = _settings(env=Env.PROD, api_token="t", google_api_key="g")
        assert isinstance(_resolve_embedding_provider(settings), GeminiEmbeddingProvider)

    def test_prod_falls_back_to_mistral(self) -> None:
        settings = _settings(env=Env.PROD, api_token="t", mistral_api_key="m")
        assert isinstance(_resolve_embedding_provider(settings), MistralEmbeddingProvider)

    def test_prod_without_cloud_key_disables_search_honestly(self) -> None:
        """Kalit yo'q — 'ishlayapti' deb ko'rsatilmaydi."""
        settings = _settings(env=Env.PROD, api_token="t")
        assert isinstance(_resolve_embedding_provider(settings), NullEmbeddingProvider)

    def test_explicit_choice_overrides_auto(self) -> None:
        settings = _settings(env=Env.DEV, embedding_provider="gemini", google_api_key="g")
        assert isinstance(_resolve_embedding_provider(settings), GeminiEmbeddingProvider)

    def test_explicit_choice_without_key_does_not_silently_switch(self) -> None:
        """Kaliti yo'q provayder so'ralsa — boshqasiga jimgina o'tilmaydi.

        Jim almashish vektor fazosini bildirmasdan o'zgartirardi.
        """
        settings = _settings(env=Env.DEV, embedding_provider="gemini")
        assert isinstance(_resolve_embedding_provider(settings), NullEmbeddingProvider)

    def test_explicit_none_disables(self) -> None:
        settings = _settings(env=Env.DEV, embedding_provider="none", google_api_key="g")
        assert isinstance(_resolve_embedding_provider(settings), NullEmbeddingProvider)


@pytest.mark.parametrize(
    "provider_env",
    ["auto", "ollama", "gemini", "mistral", "none"],
)
def test_every_configured_value_resolves(provider_env: str) -> None:
    """Sozlamaning har bir qiymati ishlaydigan provayder beradi (xato ko'tarmaydi)."""
    settings = _settings(embedding_provider=provider_env)
    assert _resolve_embedding_provider(settings) is not None
