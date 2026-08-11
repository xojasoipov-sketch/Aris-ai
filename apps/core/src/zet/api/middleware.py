"""API middleware'lari (Z1.14).

TraceMiddleware — har bir so'rovga trace_id qo'shadi.
AuthMiddleware — API token tekshiruvi (produksiya uchun).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from zet.observability.trace import bind_trace, unbind_trace


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
