"""ASGI kirish nuqtasi — `uvicorn zet.main:app` (Dockerfile, produksiya).

Ilgari bu fayl mavjud emas edi — Dockerfile `zet.main:app`ga ishora
qilardi, lekin hech qanday `main.py` yo'q edi (gap-analysis #22: "the
Dockerfile's CMD reference zet.main:app, but no zet/main.py exists").
"""

from __future__ import annotations

from zet.api.app import create_app

app = create_app()

__all__ = ["app"]
