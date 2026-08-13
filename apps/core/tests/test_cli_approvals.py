"""`z approve`/`z reject`/`z approvals` CLI testlari (GAP_ANALYSIS BROKEN #1).

Ilgari `z run` `AWAITING_APPROVAL`ga tushgan bo'lsa, API buni ko'ra
olmasdi (alohida jarayon, alohida `RunStore`). Endi CLI HTTP orqali
API'ga so'rov yuboradi — bitta manba.

Bu testlarda haqiqiy tarmoqqa chiqilmaydi: `httpx.Client.request`
monkeypatch qilinadi, natijada CLI to'g'ri URL/Header'ni yuborayotgani
va javobni to'g'ri chop etayotgani tekshiriladi.
"""

from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from typer.testing import CliRunner

from zet.cli import app

runner = CliRunner()


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Minimal `httpx.Client` almashtiruvchi."""

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


class TestZApprove:
    def test_sends_approve_request(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "run_id": "abc-run",
                "status": "done",
                "result_summary": "Muvaffaqiyatli",
            },
        )
        result = runner.invoke(app, ["approve", "approve-id-42"])
        assert result.exit_code == 0

        assert len(_FakeClient.calls) == 1
        call = _FakeClient.calls[0]
        assert call["method"] == "POST"
        assert call["url"].endswith("/api/v1/approvals/approve-id-42/approve")

    def test_prints_run_status(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {"run_id": "r1", "status": "done", "result_summary": "Bajarildi"},
        )
        result = runner.invoke(app, ["approve", "aid"])
        assert "Tasdiqlandi" in result.output
        assert "r1" in result.output or "done" in result.output

    def test_api_error_reports_and_exits_nonzero(self) -> None:
        _FakeClient.response = _FakeResponse(404, {"detail": "Tasdiq topilmadi"})
        result = runner.invoke(app, ["approve", "missing-id"])
        assert result.exit_code == 1
        assert "topilmadi" in result.output.lower() or "404" in result.output

    def test_sends_token_header_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_API_TOKEN", "test-cli-token")
        from zet.config import get_settings

        get_settings.cache_clear()
        try:
            runner.invoke(app, ["approve", "aid"])
        finally:
            get_settings.cache_clear()
        assert _FakeClient.calls
        headers = _FakeClient.calls[0]["headers"]
        assert headers.get("Authorization") == "Bearer test-cli-token"


class TestZReject:
    def test_sends_reject_request_with_note(self) -> None:
        _FakeClient.response = _FakeResponse(200, {"run_id": "abc"})
        result = runner.invoke(app, ["reject", "aid", "--note", "Xato"])
        assert result.exit_code == 0

        call = _FakeClient.calls[0]
        assert call["url"].endswith("/aid/reject")
        assert call["json"] == {"note": "Xato"}


class TestZApprovalsList:
    def test_prints_empty_when_no_pending(self) -> None:
        _FakeClient.response = _FakeResponse(200, {"pending": []})
        result = runner.invoke(app, ["approvals"])
        assert result.exit_code == 0
        assert "yo'q" in result.output.lower()

    def test_shows_table_when_pending(self) -> None:
        _FakeClient.response = _FakeResponse(
            200,
            {
                "pending": [
                    {
                        "id": "12345678-aaaa",
                        "run_id": "87654321-bbbb",
                        "tool_name": "shell.exec",
                        "estimated_cost_usd": 0.01,
                        "requested_by": "ceo",
                    }
                ]
            },
        )
        result = runner.invoke(app, ["approvals"])
        assert result.exit_code == 0
        assert "shell.exec" in result.output or "12345678" in result.output


class TestApiUnreachable:
    """API server ishlamayotgan bo'lsa aniq xato va exit code 2."""

    def test_connection_error_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _ExplodingClient(_FakeClient):
            def request(self, *args: Any, **kwargs: Any) -> _FakeResponse:
                raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx, "Client", _ExplodingClient)
        result = runner.invoke(app, ["approve", "aid"])
        assert result.exit_code == 2
        assert "ulanib" in result.output.lower() or "connect" in result.output.lower()
