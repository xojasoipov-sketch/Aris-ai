"""Embedding provider — matnni vektorga o'giradi (Bo'lim 2, semantik qidiruv).

Ilgari `memory_entries.embedding` ustuni mavjud edi-yu, hech qachon
to'ldirilmasdi — qidiruv faqat substring/so'z-overlap edi (gap-analysis).
`OllamaEmbeddingProvider` mahalliy Ollama orqali (ADR-0007: local-first)
HAQIQIY vektor hisoblaydi — hech qanday tashqi API kaliti kerak emas,
pulsiz, offline ishlaydi.

BULUTDA OLLAMA YO'Q. Railway konteynerida mahalliy Ollama ishlamaydi,
shu sabab semantik qidiruv produksiyada jim o'chiq turgan edi — yozish
va o'qish ishlardi, "ma'noga qarab qidirish" esa yo'q edi. Z39.2 ikkita
bulut provayderini qo'shadi:

    `GeminiEmbeddingProvider`  — `gemini-embedding-001` (3072 o'lcham)
    `MistralEmbeddingProvider` — `mistral-embed` (1024 o'lcham)

MODEL BELGISI SHART. `bge-m3` ham, `mistral-embed` ham 1024 o'lchamli —
ya'ni o'lcham tekshiruvi ularni ajrata OLMAYDI, lekin vektor fazolari
butunlay boshqa. Belgisiz taqqoslash "o'xshash" degan son chiqaradi, u
esa ma'nosiz. Shu sabab har bir provayder `model_id` beradi va u vektor
bilan birga saqlanadi (`pg_store`); boshqa model bilan yozilgan vektor
qidiruvda **hisobga olinmaydi** (kalit-so'zga tushadi), noto'g'ri
o'xshashlik ko'rsatilmaydi.

Fail-open: provayder ulanmagan/kalit yo'q/xato bo'lsa `embed()` xato
ko'tarmasdan `None` qaytaradi — chaqiruvchi kalit-so'z rejimiga qaytadi
(`memory.scoring.hybrid_score`), yozish/qidirish buzilmaydi.

Bog'liq qarorlar:
    Bo'lim 2 — pgvector + hybrid search (BM25 + vektor)
    ADR-0007 — local-first: Postgres shart emas, tashqi kalit shart emas
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import httpx
import structlog

log = structlog.get_logger(__name__)

EMBEDDING_MODEL_KEY = "m"
"""Saqlangan vektor yonidagi model belgisi kaliti (`{"v": [...], "m": "..."}`)."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Matnni vektorga o'giruvchi provayder shartnomasi."""

    @property
    def model_id(self) -> str:
        """Vektor fazosini bir xil aniqlaydigan belgi (masalan 'gemini:gemini-embedding-001')."""
        ...

    async def embed(self, text: str) -> list[float] | None:
        """Matn uchun embedding hisoblaydi. Muvaffaqiyatsiz bo'lsa — `None`."""
        ...

    async def aclose(self) -> None:
        """Ichki resurslarni yopadi (`app.py` lifespan shutdown'da chaqiradi)."""
        ...


def _as_float_vector(raw: object, *, provider: str) -> list[float] | None:
    """Javobdagi ro'yxatni float vektorga o'girish (yaroqsiz bo'lsa `None`)."""
    if not isinstance(raw, list) or not raw:
        log.warning("embeddings.empty_response", provider=provider)
        return None
    try:
        return [float(v) for v in raw]
    except (TypeError, ValueError):
        log.warning("embeddings.invalid_vector", provider=provider)
        return None


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

    @property
    def model_id(self) -> str:
        """Vektor fazosi belgisi."""
        return f"ollama:{self._model}"

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
        return _as_float_vector(embedding, provider="ollama")

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


class GeminiEmbeddingProvider:
    """Google Generative Language API orqali embedding (bulut, bepul kvota bor).

    Endpoint: `POST /v1beta/models/{model}:embedContent`
    Javob: `{"embedding": {"values": [...]}}`

    Default model `gemini-embedding-001` — 3072 o'lchamli, ko'p tilli
    (o'zbekcha, ruscha, inglizcha). Railway'da Ollama yo'q bo'lgani
    uchun produksiyada asosiy tanlov shu.

    `text-embedding-004` ATAYLAB ishlatilmaydi — jonli tekshiruvda u
    404 qaytardi (Google uni olib tashlagan). Model nomini o'zgartirish
    vektor fazosini ham o'zgartiradi, shuning uchun `model_id` orqali
    eski yozuvlar avtomatik ajratiladi (`pg_store`).

    KALIT HEADER ORQALI, URL'da EMAS. Ilgari u `?key=...` edi va httpx
    xato matniga to'liq URL'ni qo'shgani uchun **kalit log'ga tushib
    qolgan** (Railway'da jonli ko'rildi). `x-goog-api-key` header'i
    xato matniga kirmaydi.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-embedding-001",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def model_id(self) -> str:
        """Vektor fazosi belgisi."""
        return f"gemini:{self._model}"

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def embed(self, text: str) -> list[float] | None:
        """Matn uchun embedding. Xato bo'lsa — `None` (fail-open)."""
        if not text.strip():
            return None

        try:
            response = await self._get_client().post(
                f"{self.BASE_URL}/models/{self._model}:embedContent",
                headers={"x-goog-api-key": self._api_key},
                json={
                    "model": f"models/{self._model}",
                    "content": {"parts": [{"text": text}]},
                },
            )
            response.raise_for_status()
            data: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("embeddings.gemini_unavailable", error=str(exc))
            return None

        block = data.get("embedding") if isinstance(data, dict) else None
        values = block.get("values") if isinstance(block, dict) else None
        return _as_float_vector(values, provider="gemini")

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


class MistralEmbeddingProvider:
    """Mistral API orqali embedding (bulut, Gemini uchun zaxira).

    Endpoint: `POST /v1/embeddings`
    Javob: `{"data": [{"embedding": [...]}]}`

    `mistral-embed` 1024 o'lchamli — `bge-m3` bilan BIR XIL o'lcham,
    lekin boshqa fazo. `model_id` belgisi shu sabab majburiy.
    """

    BASE_URL = "https://api.mistral.ai/v1"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "mistral-embed",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client
        self._owns_client = client is None
        self._timeout_s = timeout_s

    @property
    def model_id(self) -> str:
        """Vektor fazosi belgisi."""
        return f"mistral:{self._model}"

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._client

    async def embed(self, text: str) -> list[float] | None:
        """Matn uchun embedding. Xato bo'lsa — `None` (fail-open)."""
        if not text.strip():
            return None

        try:
            response = await self._get_client().post(
                f"{self.BASE_URL}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self._model, "input": [text]},
            )
            response.raise_for_status()
            data: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("embeddings.mistral_unavailable", error=str(exc))
            return None

        items = data.get("data") if isinstance(data, dict) else None
        first = items[0] if isinstance(items, list) and items else None
        values = first.get("embedding") if isinstance(first, dict) else None
        return _as_float_vector(values, provider="mistral")

    async def aclose(self) -> None:
        """Ichki HTTP klientni yopadi (agar o'zi yaratgan bo'lsa)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()


class NullEmbeddingProvider:
    """Hech qachon vektor bermaydigan provayder — semantik qidiruv o'chiq.

    Halol holat: hech qanday manba sozlanmagan bo'lsa, tizim "vektor bor"
    deb ko'rsatmaydi, shunchaki kalit-so'z rejimida ishlaydi.
    """

    @property
    def model_id(self) -> str:
        """Vektor fazosi belgisi (hech qachon saqlanmaydi)."""
        return "none"

    async def embed(self, text: str) -> list[float] | None:  # noqa: ARG002
        """Har doim `None` — protokol imzosi saqlanadi."""
        return None

    async def aclose(self) -> None:
        """Yopadigan resurs yo'q."""


__all__ = [
    "EMBEDDING_MODEL_KEY",
    "EmbeddingProvider",
    "GeminiEmbeddingProvider",
    "MistralEmbeddingProvider",
    "NullEmbeddingProvider",
    "OllamaEmbeddingProvider",
]
