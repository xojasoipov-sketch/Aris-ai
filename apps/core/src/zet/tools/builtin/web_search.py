"""Web Search tool — tashqi qidiruv (Bo'lim 3, 7).

`api_key` berilsa — Brave Search API (bepul qatlam: 2000 so'rov/oy, $10/oy
byudjetga mos) orqali haqiqiy qidiradi. `api_key` berilmasa (default) —
stub rejim: tarmoqqa chiqmaydi, barqaror soxta natijalar.

Ilgari bu klass HAR DOIM stub edi (gap-analysis #12: "web.search 100% mock").

Xavfsizlik:
    - output trust_level = UNTRUSTED (A-05) — internetdan kelgan matn
    - permission = READ
    - idempotent = True
"""

from __future__ import annotations

from typing import Any

import httpx

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool, ToolError

_API_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchTool(Tool):
    """Web qidiruv tool — `api_key` bo'lsa Brave Search, bo'lmasa stub."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    @property
    def is_real(self) -> bool:
        """Haqiqiy API ishlatilyaptimi (kalit bor)."""
        return bool(self._api_key)

    @property
    def name(self) -> str:
        return "web.search"

    @property
    def description(self) -> str:
        return "Internetdan qidirish — natijalar UNTRUSTED sifatida qaytadi"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Qidiruv so'rovi",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maksimal natijalar soni",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def output_trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED

    @property
    def idempotent(self) -> bool:
        return True

    @property
    def timeout_s(self) -> int:
        return 30

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"X-Subscription-Token": self._api_key or "", "Accept": "application/json"}
            )
        return self._client

    async def aclose(self) -> None:
        """HTTP klientni yopish (agar biz yaratgan bo'lsak)."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _execute(self, params: dict[str, Any]) -> Any:
        query = params["query"]
        max_results = min(int(params.get("max_results", 5)), 20)

        if self.is_real:
            return await self._real_search(query, max_results)
        return self._stub_search(query, max_results)

    async def _real_search(self, query: str, max_results: int) -> dict[str, Any]:
        try:
            response = await self._get_client().get(
                _API_URL,
                params={"q": query, "count": max_results},
                timeout=self.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ToolError(f"Qidiruv API timeout: {query}") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Qidiruv API xatosi: {exc}") from exc

        if response.status_code == 401:
            raise ToolError("Qidiruv API kaliti noto'g'ri (401)")
        if response.status_code == 429:
            raise ToolError("Qidiruv API kvotasi tugadi (429)")
        if response.status_code >= 400:
            raise ToolError(f"Qidiruv API xato ({response.status_code}): {response.text[:300]}")

        data = response.json()
        raw_results = (data.get("web") or {}).get("results") or []
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
                "source": "web.search (brave)",
            }
            for item in raw_results[:max_results]
        ]
        return {"query": query, "results": results, "total": len(results)}

    def _stub_search(self, query: str, max_results: int) -> dict[str, Any]:
        results = [
            {
                "title": f"Natija {i + 1}: {query}",
                "url": f"https://example.com/search?q={query.replace(' ', '+')}&p={i}",
                "snippet": f"{query} haqida ma'lumot — natija {i + 1}.",
                "source": "web.search (stub)",
            }
            for i in range(min(max_results, 3))  # Stub faqat 3 tagacha
        ]
        return {"query": query, "results": results, "total": len(results)}
