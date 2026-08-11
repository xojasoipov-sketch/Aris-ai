"""Web Search tool — tashqi qidiruv (Bo'lim 3).

Bo'lim 3 uchun stub (mock) implementatsiya.
Haqiqiy API integratsiya Bo'lim 7 da.

Xavfsizlik:
    - output trust_level = UNTRUSTED (A-05)
    - permission = READ
    - idempotent = True
"""

from __future__ import annotations

from typing import Any

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.base import Tool


class WebSearchTool(Tool):
    """Web qidiruv tool — stub (Bo'lim 7 da haqiqiy API bilan almashtiriladi)."""

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

    async def _execute(self, params: dict[str, Any]) -> Any:
        """Stub qidiruv — Bo'lim 7 da haqiqiy API bilan almashtiriladi."""
        query = params["query"]
        max_results = params.get("max_results", 5)

        # Stub natijalar
        return {
            "query": query,
            "results": [
                {
                    "title": f"Natija {i + 1}: {query}",
                    "url": f"https://example.com/search?q={query.replace(' ', '+')}&p={i}",
                    "snippet": f"{query} haqida ma'lumot — natija {i + 1}.",
                    "source": "web.search (stub)",
                }
                for i in range(min(max_results, 3))  # Stub faqat 3 tagacha
            ],
            "total": min(max_results, 3),
        }
