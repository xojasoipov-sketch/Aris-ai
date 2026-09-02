"""`z api search`/`refresh`/`health`/`stats` CLI testlari (JB-18, Bo'lim 17).

`test_cli_approvals.py` bilan bir xil naqsh: haqiqiy tarmoqqa
chiqilmaydi, `httpx.Client` monkeypatch qilinadi — CLI to'g'ri
URL/metod yuborayotgani va javobni to'g'ri chop etayotgani tekshiriladi.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from typer.testing import CliRunner

from zet.cli import app

runner = CliRunner()


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    calls: ClassVar[list[dict[str, Any]]] = []
    response: ClassVar[_FakeResponse] = _FakeResponse(200, {"ok": True})

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def request(
        self, method: str, url: str, *, headers: dict[str, str], json: dict[str, Any] | None = None
    ) -> _FakeResponse:
        _FakeClient.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return _FakeClient.response


@pytest.fixture(autouse=True)
def patch_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.calls.clear()
    _FakeClient.response = _FakeResponse(200, {"ok": True})
    monkeypatch.setattr(httpx, "Client", _FakeClient)


class TestApiSearch:
    def test_sends_get_with_query_and_limit(self) -> None:
        _FakeClient.response = _FakeResponse(
            200, {"query": "geo", "total_candidates": 0, "candidates": []}
        )
        result = runner.invoke(app, ["api", "search", "geo", "--limit", "5"])
        assert result.exit_code == 0

        call = _FakeClient.calls[0]
        assert call["method"] == "GET"
        assert "/api/v1/public-apis/search?" in call["url"]
        assert "q=geo" in call["url"]
        assert "limit=5" in call["url"]

    def test_prints_no_results_message(self) -> None:
        _FakeClient.response = _FakeResponse(
            200, {"query": "xyz", "total_candidates": 0, "candidates": []}
        )
        result = runner.invoke(app, ["api", "search", "xyz"])
        assert result.exit_code == 0
        assert "topilmadi" in result.output.lower()

    def test_prints_table_with_candidates(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "query": "geo",
                "total_candidates": 1,
                "candidates": [
                    {
                        "entry_id": "abc123",
                        "name": "Geocodio",
                        "provider": "geocod.io",
                        "category": "Geocoding",
                        "auth_type": "apiKey",
                        "status": "discovered",
                        "composite_score": 0.42,
                        "reasons": ["HTTPS"],
                    }
                ],
            },
        )
        result = runner.invoke(app, ["api", "search", "geo"])
        assert result.exit_code == 0
        assert "Geocodio" in result.output

    def test_http_error_exits_nonzero(self) -> None:
        _FakeClient.response = _FakeResponse(422, {"detail": "invalid query"})
        result = runner.invoke(app, ["api", "search", "x"])
        assert result.exit_code == 1

    def test_query_with_special_characters_is_url_encoded(self) -> None:
        _FakeClient.response = _FakeResponse(
            200, {"query": "a b&c", "total_candidates": 0, "candidates": []}
        )
        result = runner.invoke(app, ["api", "search", "a b&c"])
        assert result.exit_code == 0
        call = _FakeClient.calls[0]
        assert "a+b%26c" in call["url"] or "a%20b%26c" in call["url"]


class TestApiRefresh:
    def test_sends_post_request(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "ok": True,
                "total_entries": 1584,
                "added": 1584,
                "changed": 0,
                "removed": 0,
                "categories": 50,
            },
        )
        result = runner.invoke(app, ["api", "refresh"])
        assert result.exit_code == 0

        call = _FakeClient.calls[-1]
        assert call["method"] == "POST"
        assert call["url"].endswith("/api/v1/public-apis/refresh")
        assert "Sinxronlandi" in result.output
        assert "1584" in result.output

    def test_sync_failure_exits_nonzero_with_error(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "ok": False,
                "total_entries": 0,
                "added": 0,
                "changed": 0,
                "removed": 0,
                "categories": 0,
                "error": "manba javob bermadi",
            },
        )
        result = runner.invoke(app, ["api", "refresh"])
        assert result.exit_code == 1
        assert "manba javob bermadi" in result.output

    def test_http_error_exits_nonzero(self) -> None:
        _FakeClient.response = _FakeResponse(500, {"detail": "server error"})
        result = runner.invoke(app, ["api", "refresh"])
        assert result.exit_code == 1


class TestApiHealth:
    def test_empty_health_prints_honest_message(self) -> None:
        _FakeClient.response = _FakeResponse(200, [])
        result = runner.invoke(app, ["api", "health"])
        assert result.exit_code == 0
        assert "chaqirilmagan" in result.output.lower()

    def test_prints_table_with_stats(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            [
                {
                    "provider": "ipwho.is",
                    "total_calls": 10,
                    "successes": 9,
                    "failures": 1,
                    "timeouts": 0,
                    "rate_limited": 0,
                    "avg_latency_ms": 123.4,
                    "success_rate": 0.9,
                }
            ],
        )
        result = runner.invoke(app, ["api", "health"])
        assert result.exit_code == 0
        assert "ipwho.is" in result.output

    def test_none_success_rate_does_not_crash(self) -> None:
        """`total_calls==0` bo'lsa `success_rate=None` — CLI buni
        formatlashda yiqilmasligi kerak (Bo'lim 13: None ≠ 0)."""
        _FakeClient.response = _FakeResponse(
            200,
            [
                {
                    "provider": "untested",
                    "total_calls": 0,
                    "successes": 0,
                    "failures": 0,
                    "timeouts": 0,
                    "rate_limited": 0,
                    "avg_latency_ms": 0.0,
                    "success_rate": None,
                }
            ],
        )
        result = runner.invoke(app, ["api", "health"])
        assert result.exit_code == 0


class TestApiStats:
    def test_prints_counts(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "total_entries": 1584,
                "categories": 50,
                "enabled": 0,
                "last_sync_at": "2026-08-19T10:00:00+00:00",
                "last_sync_source": "https://example.com",
                "last_sync_ok": True,
            },
        )
        result = runner.invoke(app, ["api", "stats"])
        assert result.exit_code == 0
        assert "1584" in result.output
        assert "50" in result.output

    def test_never_synced_shows_honest_placeholder(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "total_entries": 0,
                "categories": 0,
                "enabled": 0,
                "last_sync_at": None,
                "last_sync_source": None,
                "last_sync_ok": None,
            },
        )
        result = runner.invoke(app, ["api", "stats"])
        assert result.exit_code == 0
        assert "hali sinxronlanmagan" in result.output


class TestApiUnreachable:
    def test_connection_error_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _ExplodingClient(_FakeClient):
            def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
                raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx, "Client", _ExplodingClient)
        result = runner.invoke(app, ["api", "search", "x"])
        assert result.exit_code == 2
