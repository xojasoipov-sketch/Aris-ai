"""API token himoyasi testlari (Z39.1).

Ilgari `Settings.api_token` prod'da MAJBURIY edi, lekin uni hech kim
TEKSHIRMASDI — Railway'dagi backend butunlay ochiq turgan. Bu fayl
teshik qayta ochilmasligini kafolatlaydi.

Barcha testlar `no_auto_auth` markeri bilan — conftest'dagi avtomatik
header qo'shish o'chiriladi, header'ni har test o'zi boshqaradi.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from zet.api.middleware import PUBLIC_PATHS, TokenAuthMiddleware
from zet.config import Env, Settings

pytestmark = pytest.mark.no_auto_auth

TOKEN = "sirli-token-12345"


def _client(*, token: str | None = TOKEN, env: Env = Env.DEV) -> TestClient:
    """Token middleware'i o'rnatilgan minimal ilova."""
    from fastapi import FastAPI

    settings = Settings(
        env=env,
        api_token=token,  # type: ignore[arg-type]
        anthropic_api_key="k",  # type: ignore[arg-type]
    )
    app = FastAPI()
    app.add_middleware(TokenAuthMiddleware, settings=settings)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/status")
    def status() -> dict[str, str]:
        return {"secret": "ichki holat"}

    @app.post("/api/v1/run")
    def run() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


class TestTokenRequired:
    """Himoyalangan yo'llar tokensiz ochilmaydi."""

    def test_no_header_rejected(self) -> None:
        assert _client().get("/api/v1/status").status_code == 401

    def test_wrong_token_rejected(self) -> None:
        r = _client().get("/api/v1/status", headers={"Authorization": "Bearer boshqa"})
        assert r.status_code == 401

    def test_correct_token_accepted(self) -> None:
        r = _client().get("/api/v1/status", headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200
        assert r.json()["secret"] == "ichki holat"

    def test_post_also_protected(self) -> None:
        """Faqat GET emas — yozuv amallari ham."""
        assert _client().post("/api/v1/run").status_code == 401

    def test_missing_bearer_prefix_rejected(self) -> None:
        """Yalang'och token (prefikssiz) qabul qilinmaydi."""
        r = _client().get("/api/v1/status", headers={"Authorization": TOKEN})
        assert r.status_code == 401

    def test_www_authenticate_header_present(self) -> None:
        """401 javobi RFC 7235 bo'yicha `WWW-Authenticate` beradi."""
        r = _client().get("/api/v1/status")
        assert r.headers["WWW-Authenticate"] == "Bearer"

    def test_empty_bearer_rejected(self) -> None:
        r = _client().get("/api/v1/status", headers={"Authorization": "Bearer "})
        assert r.status_code == 401


class TestPublicPaths:
    """`/health` tokensiz ochiq — Railway healthcheck shunga tayanadi."""

    def test_health_open_without_token(self) -> None:
        r = _client().get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_is_the_only_always_public_path(self) -> None:
        """Ochiq yo'llar ro'yxati tasodifan o'smasin."""
        assert frozenset({"/api/v1/health"}) == PUBLIC_PATHS

    def test_status_is_not_public(self) -> None:
        """`/status` ichki holatni beradi — u ochiq bo'lmasligi kerak."""
        assert "/api/v1/status" not in PUBLIC_PATHS


class TestOpenApiExposure:
    """Prod'da API sxemasi ham yopiq — hujum yuzasining xaritasi berilmaydi."""

    def test_openapi_open_in_dev(self) -> None:
        assert _client(env=Env.DEV).get("/openapi.json").status_code == 200

    def test_openapi_closed_in_prod(self) -> None:
        assert _client(env=Env.PROD).get("/openapi.json").status_code == 401


class TestNoTokenConfigured:
    """Token sozlanmagan holat — dev'da ochiq, prod'da hammasi rad etiladi."""

    def test_dev_without_token_allows(self) -> None:
        """Lokal ishlash buzilmaydi."""
        assert _client(token=None, env=Env.DEV).get("/api/v1/status").status_code == 200

    def test_prod_without_token_denies_everything(self) -> None:
        """Ikkilamchi himoya: config validatsiyasi o'tib ketsa ham yopiq qoladi.

        `Settings`ni to'g'ridan-to'g'ri qurish prod validatsiyasini
        chetlab o'tadi, shuning uchun middleware'ni yolg'iz sinaymiz.
        """
        from fastapi import FastAPI

        settings = Settings(env=Env.DEV, api_token=None, anthropic_api_key="k")  # type: ignore[arg-type]
        object.__setattr__(settings, "env", Env.PROD)

        app = FastAPI()
        app.add_middleware(TokenAuthMiddleware, settings=settings)

        @app.get("/api/v1/status")
        def status() -> dict[str, str]:
            return {"secret": "x"}

        assert TestClient(app).get("/api/v1/status").status_code == 401
