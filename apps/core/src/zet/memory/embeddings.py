"""Embedding provider — matnni vektorga o'giradi (Bo'lim 2, semantik qidiruv).

Ilgari `memory_entries.embedding` ustuni mavjud edi-yu, hech qachon
to'ldirilmasdi — qidiruv faqat substring/so'z-overlap edi (gap-analysis).
`OllamaEmbeddingProvider` mahalliy Ollama orqali (ADR-0007: local-first)
HAQIQIY vektor hisoblaydi — hech qanday tashqi API kaliti kerak emas,
pulsiz, offline ishlaydi.

Fail-open: Ollama ulanmagan/model yo'q/xato bo'lsa `embed()` xato
ko'tarmasdan `None` qaytaradi — chaqiruvchi kalit-so'z rejimiga qaytadi
(`memory.scoring.hybrid_score`), yozish/qidirish buzilmaydi.

Bog'liq qarorlar:
    Bo'lim 2 — pgvector + hybrid search (BM25 + vektor)
    ADR-0007 — local-first: Postgres shart emas, tashqi kalit shart emas
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx
import structlog

log = structlog.get_logger(__name__)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Matnni vektorga o'giruvchi provayder shartnomasi."""

    async def embed(self, text: str) -> list[float] | None:
        """Matn uchun embedding hisoblaydi. Muvaffaqiyatsiz bo'lsa — `None`."""
        ...


class OllamaEmbeddingProvider:
    """Mahalliy Ollama orqali embedding — tashqi kalit talab qilmaydi.

    Default model `bge-m3` (`Settings.ollama_embed_model`) — ko'p tilli
    (o'zbekcha, ruscha, inglizcha), 16 GB RAM'da ishlaydi.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def embed(self, text: str) -> list[float] | None:
        """Matn uchun embedding hisoblaydi.

        Ollama ulanmagan, model yuklanmagan yoki javob kutilmagan bo'lsa —
        `None` (xato ko'tarilmaydi, chaqiruvchi kalit-so'z rejimiga qaytadi).
        """
        if not text.strip():
            return None

        try:
            response = await self._get_client().post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("embeddings.ollama_unavailable", error=str(exc))
            return None

        embedding = data.get("embedding") if isinstance(data, dict) else None
        if not isinstance(embedding, list) or not embedding:
            log.warning("embeddings.ollama_empty_response")
            return None

        try:
            return [float(v) for v in embedding]
        except (TypeError, ValueError):
            log.warning("embeddings.ollama_invalid_vector")
            return None

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


__all__ = ["EmbeddingProvider", "OllamaEmbeddingProvider"]
