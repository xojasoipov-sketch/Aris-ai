"""API middleware'lari (Z1.14).

TraceMiddleware — har bir so'rovga trace_id qo'shadi.
TokenAuthMiddleware — `Authorization: Bearer <token>` tekshiruvi.

`TokenAuthMiddleware` ilgari faqat shu docstringda va'da qilingan edi
("AuthMiddleware — API token tekshiruvi") — hech qachon yozilmagan.
Natijada `Settings.api_token` prod'da MAJBURIY bo'lsa ham (config
validatsiyasi), uni hech kim TEKSHIRMASDI: Railway'dagi backend butunlay
ochiq turgan. Z39.1 shu teshikni yopadi.

NEGA MIDDLEWARE, `Depends()` EMAS — himoya **default** bo'lishi kerak.
Har bir route'ga qo'lda `Depends(require_token)` yozilsa, ertaga
qo'shiladigan yangi route uni unutadi va jimgina ochiq qoladi.
Middleware'da esa aksincha: yangi route avtomatik yopiq, ochiq bo'lishi
uchun uni ATAYLAB `PUBLIC_PATHS`ga yozish kerak.
"""

from __future__ import annotations

import secrets

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from zet.config import Settings
from zet.observability.trace import bind_trace, unbind_trace

log = structlog.get_logger(__name__)

PUBLIC_PATHS: frozenset[str] = frozenset({"/api/v1/health"})
"""HAR QANDAY muhitda tokensiz ochiq yo'llar.

`/api/v1/health` — Railway healthcheck uni tokensiz chaqiradi; yopilsa
deploy hech qachon "healthy" bo'lmaydi. U faqat `{"status": "ok"}`
qaytaradi, hech qanday ma'lumot oshkor qilmaydi.

`/api/v1/status` bu ro'yxatda YO'Q — u tizim ichki holatini beradi.
"""

DEV_PUBLIC_PATHS: frozenset[str] = frozenset({"/docs", "/redoc", "/openapi.json"})
"""Faqat prod BO'LMAGAN muhitda ochiq yo'llar.

Prod'da `/openapi.json` ham yopiq: u butun API sirtini (barcha route,
parametr, sxema) beradi — hujum yuzasining tayyor xaritasi.
"""

BEARER_PREFIX = "Bearer "
"""`Authorization` header prefiksi."""


class TraceMiddleware(BaseHTTPMiddleware):
    """Har bir so'rovga trace_id qo'shadi.

    So'rov headerida `X-Trace-ID` bo'lsa — ishlatiladi.
    Yo'q bo'lsa — yangi generatsiya qilinadi.
    Javob headeriga `X-Trace-ID` qo'shiladi.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """So'rovni qayta ishlash."""
        incoming_trace = request.headers.get("X-Trace-ID")
        trace_id = bind_trace(incoming_trace)

        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            unbind_trace()


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """`Authorization: Bearer <token>` tekshiruvi (R-04: faqat ega).

    Token `Settings.api_token` bilan **doimiy vaqtli** taqqoslanadi
    (`secrets.compare_digest`) — oddiy `==` javob vaqti orqali tokenni
    belgi-belgi topishga imkon berardi.

    Token sozlanmagan bo'lsa:
        - prod'da — bunga yo'l qo'yilmaydi (config validatsiyasi ushlaydi),
          lekin baribir HAMMA so'rov rad etiladi (ikkilamchi himoya)
        - dev/test'da — tekshiruv o'tkazib yuboriladi (lokal ish buzilmasin)
    """

    def __init__(self, app: object, *, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        token = settings.api_token
        self._expected: str | None = token.get_secret_value() if token else None
        self._public = PUBLIC_PATHS if settings.is_prod else PUBLIC_PATHS | DEV_PUBLIC_PATHS

        if self._expected is None and settings.is_prod:  # pragma: no cover — config ushlaydi
            log.error("auth.no_token_in_prod")
        elif self._expected is None:
            log.warning("auth.disabled_no_token", env=settings.env.value)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Tokenni tekshirish; yaroqsiz bo'lsa 401."""
        if self._is_public(request):
            return await call_next(request)

        if self._expected is None:
            if self._settings.is_prod:  # pragma: no cover — config ushlaydi
                return _unauthorized("Server tokeni sozlanmagan")
            return await call_next(request)

        if not self._token_matches(request.headers.get("Authorization")):
            log.warning(
                "auth.rejected",
                path=request.url.path,
                method=request.method,
                client=request.client.host if request.client else "?",
            )
            return _unauthorized("Yaroqsiz yoki yo'q token")

        return await call_next(request)

    def _is_public(self, request: Request) -> bool:
        """Yo'l tokensiz ochiqmi.

        CORS preflight (`OPTIONS`) ham o'tkaziladi — brauzer unga
        `Authorization` header qo'shmaydi (spetsifikatsiya bo'yicha).
        """
        if request.method == "OPTIONS":
            return True
        path = request.url.path
        return path in self._public or path.rstrip("/") in self._public

    def _token_matches(self, header: str | None) -> bool:
        """`Authorization` headerini tekshirish (doimiy vaqtda)."""
        if self._expected is None:  # pragma: no cover — chaqirilishidan oldin tekshirilgan
            return False
        if not header or not header.startswith(BEARER_PREFIX):
            return False
        provided = header[len(BEARER_PREFIX) :].strip()
        return secrets.compare_digest(provided, self._expected)


def _unauthorized(detail: str) -> JSONResponse:
    """401 javobi — `WWW-Authenticate` bilan (RFC 7235)."""
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = [
    "BEARER_PREFIX",
    "DEV_PUBLIC_PATHS",
    "PUBLIC_PATHS",
    "TokenAuthMiddleware",
    "TraceMiddleware",
]
