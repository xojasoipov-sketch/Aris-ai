"""RateLimitMiddleware testlari (GAP_ANALYSIS SR-03).

`RateLimiter` moduli ilgari qurilgan-u ASGI stack'ga ulanmagan edi.
Endi middleware sifatida ishlaydi, so'rov limitini oshsa 429 qaytaradi.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from zet.api.middleware import RateLimitMiddleware
from zet.security.ratelimit import RateLimiter, RateLimitTier


def _make_app(limit: int) -> tuple[FastAPI, RateLimiter]:
    app = FastAPI()
    limiter = RateLimiter(default_limits={RateLimitTier.OWNER: limit})
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app, limiter


def test_under_limit_allows() -> None:
    app, _ = _make_app(limit=5)
    client = TestClient(app)

    for _ in range(5):
        response = client.get("/ping")
        assert response.status_code == 200


def test_over_limit_returns_429() -> None:
    app, _ = _make_app(limit=2)
    client = TestClient(app)

    client.get("/ping")
    client.get("/ping")
    response = client.get("/ping")

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["detail"].startswith("Rate limit")


def test_health_bypasses_rate_limit() -> None:
    """health path public — cheklovga tushmaydi."""
    app, _ = _make_app(limit=1)
    client = TestClient(app)

    client.get("/api/v1/health")
    client.get("/api/v1/health")
    r = client.get("/api/v1/health")
    assert r.status_code == 200


def test_response_headers_include_ratelimit_info() -> None:
    app, _ = _make_app(limit=10)
    client = TestClient(app)

    r = client.get("/ping")
    assert r.headers.get("X-RateLimit-Limit") == "10"
    assert r.headers.get("X-RateLimit-Remaining") == "9"


@pytest.mark.no_auto_auth
def test_middleware_in_real_app_stack() -> None:
    """RateLimitMiddleware haqiqiy ZET app'ga to'g'ri ulangan (health tokensiz o'tadi)."""
    from zet.api.app import create_app

    app = create_app()
    client = TestClient(app)

    response = client.get("/api/v1/health")
    assert response.status_code == 200
