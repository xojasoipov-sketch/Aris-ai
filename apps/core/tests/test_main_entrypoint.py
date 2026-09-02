"""zet/main.py — ASGI kirish nuqtasi (gap-analysis #22).

Dockerfile'ning `CMD ["uvicorn", "zet.main:app", ...]` ishora qiladigan
modul. Ilgari bu fayl mavjud emas edi — konteyner ishga tushmasdi.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestMainEntrypoint:
    def test_app_importable(self) -> None:
        from zet.main import app

        assert isinstance(app, FastAPI)

    def test_app_responds_to_health(self) -> None:
        from zet.main import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
