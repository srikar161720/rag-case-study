"""SlowAPI rate-limit wiring (Fork 47).

Composite bucket key ``(X-API-Key[:8], client_ip)`` for authenticated
traffic; ``anon:{ip}`` when no key was supplied. This is the right
shape for "one user behind a NAT shouldn't trip another user's bucket"
while still rate-limiting per-IP for anonymous probes.

Per-route limits are opt-in via ``@limiter.limit(...)`` decorator —
``default_limits=[]`` makes the limiter inert until a route declares
its own ceiling. ``/health`` and ``/ready`` stay un-decorated → never
rate-limited.

Storage is ``memory://`` (single-process, single-machine — matches the
Fly shared-cpu-1x deployment). Multi-machine production would swap to
``redis://`` so buckets shared across replicas; the swap is a one-line
env-var change (see ``context/07-infrastructure.md``).

The custom 429 handler ships a structured JSON body matching the
unified error-shape contract (``error``, ``message``, ``retry_after``)
plus the standard ``Retry-After`` header so polite clients back off
automatically.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from customs_agent.config import settings


def composite_key(request: Request) -> str:
    """Bucket key combining the API-key prefix and the client IP.

    Returns ``"{api_key[:8]}:{ip}"`` when ``X-API-Key`` is present (the
    common case — the FastAPI server-side proxy always injects it),
    and ``"anon:{ip}"`` when absent (rare: only ``/health``/``/ready``
    are unauthenticated, and those bypass rate limiting altogether).

    Slicing the key to 8 chars caps storage + log noise without
    weakening isolation: 32-byte base64 keys collide only at vanishingly
    small probability across our key population (~3 keys).
    """
    api_key = request.headers.get("X-API-Key", "")
    ip = request.client.host if request.client else "unknown"
    return f"{api_key[:8]}:{ip}" if api_key else f"anon:{ip}"


limiter = Limiter(
    key_func=composite_key,
    default_limits=[],  # opt-in per route via @limiter.limit decorator
    enabled=settings.ratelimit_enabled,
    storage_uri="memory://",
)


async def custom_rate_limit_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Exception handler for :class:`slowapi.errors.RateLimitExceeded`.

    Wired into the FastAPI app via
    ``app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)``.
    The slowapi default handler returns plain text; we override to
    match the project's structured JSON error shape and to set the
    ``Retry-After`` HTTP header so HTTP-compliant clients honor it
    automatically.
    """
    retry_after = int(getattr(exc, "retry_after", 60))
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        content={
            "error": "rate_limited",
            "message": f"Too many requests. Retry in {retry_after} seconds.",
            "retry_after": retry_after,
        },
    )
