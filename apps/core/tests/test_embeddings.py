"""memory/embeddings.py testlari — OllamaEmbeddingProvider (respx bilan).

Ollama ulanmagan/xato bo'lganda ham `embed()` xato ko'tarmasligini
(fail-open) tekshirish — bu shartnomaning eng muhim qismi.
"""

from __future__ import annotations

import httpx
import respx

from zet.memory.embeddings import OllamaEmbeddingProvider

_BASE_URL = "http://localhost:11434"


class TestEmbed:
    @respx.mock
    async def test_successful_embedding(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        result = await provider.embed("Python haqida")

        assert result == [0.1, 0.2, 0.3]
        await provider.aclose()

    @respx.mock
    async def test_sends_correct_payload(self) -> None:
        route = respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": [1.0]})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        await provider.embed("test matni")

        request = route.calls[0].request
        import json

        body = json.loads(request.content)
        assert body == {"model": "bge-m3", "prompt": "test matni"}
        await provider.aclose()

    async def test_empty_text_returns_none_without_request(self) -> None:
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        assert await provider.embed("   ") is None
        await provider.aclose()

    @respx.mock
    async def test_connection_error_returns_none(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        result = await provider.embed("matn")

        assert result is None
        await provider.aclose()

    @respx.mock
    async def test_http_error_status_returns_none(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(404, json={"error": "model not found"})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="ghost-model")
        result = await provider.embed("matn")

        assert result is None

    @respx.mock
    async def test_malformed_json_returns_none(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        assert await provider.embed("matn") is None

    @respx.mock
    async def test_missing_embedding_field_returns_none(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, json={"unexpected": "shape"})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        assert await provider.embed("matn") is None

    @respx.mock
    async def test_empty_embedding_list_returns_none(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": []})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        assert await provider.embed("matn") is None

    @respx.mock
    async def test_non_numeric_vector_returns_none(self) -> None:
        respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": ["a", "b"]})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        assert await provider.embed("matn") is None

    @respx.mock
    async def test_reuses_client_across_calls(self) -> None:
        route = respx.post(f"{_BASE_URL}/api/embeddings").mock(
            return_value=httpx.Response(200, json={"embedding": [0.5]})
        )
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3")
        await provider.embed("birinchi")
        await provider.embed("ikkinchi")

        assert route.call_count == 2
        await provider.aclose()

    async def test_does_not_close_externally_provided_client(self) -> None:
        client = httpx.AsyncClient()
        provider = OllamaEmbeddingProvider(base_url=_BASE_URL, model="bge-m3", client=client)
        await provider.aclose()
        assert not client.is_closed
        await client.aclose()
