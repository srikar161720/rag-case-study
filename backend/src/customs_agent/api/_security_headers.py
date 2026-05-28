"""Defensive HTTP response headers (Fork 51).

Browser-honored headers that close minor attack vectors at zero
runtime cost. Server-to-server callers ignore them; modern browsers
honor them on every response — including 4xx and 5xx error responses
— which is why this middleware is wired as the OUTERMOST layer in
``main.py``.

- ``X-Content-Type-Options: nosniff`` — disables MIME-sniffing.
- ``X-Frame-Options: DENY`` — blocks clickjacking via ``<iframe>``.
- ``Referrer-Policy: no-referrer`` — stops URL parameter leak to
  cross-origin third parties.
- ``Strict-Transport-Security: max-age=63072000; includeSubDomains``
  — 2-year HSTS, defends against protocol downgrade.

No CSP — backend serves JSON / SSE only, never HTML. If we ever
served HTML directly from Fly (we don't; the frontend lives on
Vercel), CSP would become relevant.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp four defensive headers onto every outgoing response."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
        return response
