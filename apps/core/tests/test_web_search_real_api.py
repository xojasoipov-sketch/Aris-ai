"""WebSearchTool — haqiqiy API rejimi (respx bilan, gap-analysis #12).

Stub rejim testlari `tests/test_agent_runtime.py`da — bu fayl faqat
`api_key`li (real, Brave Search) rejimni tekshiradi.
"""

from __future__ import annotations

import httpx
import respx

from zet.tools.builtin.web_search import WebSearchTool

_API_KEY = "brave-fake-key"
_API_URL = "https://api.search.brave.com/res/v1/web/search"


class TestWebSearchToolReal:
    def test_is_real_with_key(self) -> None:
        assert WebSearchTool(api_key=_API_KEY).is_real is True

    def test_is_stub_without_key(self) -> None:
        assert WebSearchTool().is_real is False

    @respx.mock
    async def test_real_search_success(self) -> None:
        respx.get(_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {
                                "title": "Python — rasmiy sayt",
                                "url": "https://python.org",
                                "description": "Python dasturlash tili",
                            },
                        ]
                    }
                },
            )
        )
        tool = WebSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "Python"})
        assert result.success, result.error
        assert result.output["total"] == 1
        assert result.output["results"][0]["source"] == "web.search (brave)"
        assert result.output["results"][0]["url"] == "https://python.org"

    @respx.mock
    async def test_real_search_respects_max_results(self) -> None:
        respx.get(_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "web": {
                        "results": [
                            {"title": f"R{i}", "url": f"https://x.com/{i}", "description": "x"}
                            for i in range(10)
                        ]
                    }
                },
            )
        )
        tool = WebSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "test", "max_results": 3})
        assert len(result.output["results"]) == 3

    @respx.mock
    async def test_real_search_empty_results(self) -> None:
        respx.get(_API_URL).mock(return_value=httpx.Response(200, json={"web": {"results": []}}))
        tool = WebSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "nonexistent-xyz"})
        assert result.success
        assert result.output["total"] == 0

    @respx.mock
    async def test_401_returns_error(self) -> None:
        respx.get(_API_URL).mock(return_value=httpx.Response(401))
        tool = WebSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "x"})
        assert not result.success
        assert "401" in result.error

    @respx.mock
    async def test_429_quota_returns_error(self) -> None:
        respx.get(_API_URL).mock(return_value=httpx.Response(429))
        tool = WebSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "x"})
        assert not result.success
        assert "kvota" in result.error.lower()

    @respx.mock
    async def test_timeout_returns_error(self) -> None:
        respx.get(_API_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))
        tool = WebSearchTool(api_key=_API_KEY)
        result = await tool.execute({"query": "x"})
        assert not result.success

    async def test_aclose_own_client(self) -> None:
        tool = WebSearchTool(api_key=_API_KEY)
        tool._get_client()
        await tool.aclose()

    async def test_aclose_external_client_not_closed(self) -> None:
        client = httpx.AsyncClient()
        tool = WebSearchTool(api_key=_API_KEY, client=client)
        await tool.aclose()
        assert client.is_closed is False
        await client.aclose()
