"""Static-API-key authentication (Fork 48).

Single dependency :func:`require_api_key` injected via FastAPI's
:func:`Depends` on every protected route. The ``X-API-Key`` request
header is compared against :data:`customs_agent.config.settings.backend_api_key`
in constant time via :func:`secrets.compare_digest` — never with ``==``,
which would leak key length / prefix information through timing
side-channels.

Error shapes match the unified JSON contract in
``context/05-api-and-backend.md`` §"Unified Error Response Shapes":

- 401 ``missing_api_key`` when the header is absent
- 403 ``invalid_api_key`` when the header value doesn't match

Exempt endpoints (``/health``, ``/ready``) simply omit the
:func:`Depends(require_api_key)` declaration — there's no per-middleware
exemption logic to drift out of sync (Fork 40).
"""

from secrets import compare_digest

import structlog
from fastapi import Header, HTTPException, Request, status

from customs_agent.config import settings
from customs_agent.observability.events import Events

log = structlog.get_logger()


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency that validates the ``X-API-Key`` header.

    Returns the validated key string on success so downstream code can
    log a prefix (the first 8 chars are also the rate-limit bucket key,
    see :mod:`customs_agent.api._rate_limit`).

    Raises
    ------
    HTTPException
        401 if the header is missing; 403 if the value doesn't match.
    """
    if not x_api_key:
        log.warning(
            Events.AUTH_MISSING_KEY,
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_api_key",
                "message": "X-API-Key header required.",
            },
            headers={"WWW-Authenticate": 'ApiKey realm="customs-agent"'},
        )
    # Encode both args to UTF-8 bytes before ``compare_digest``.
    # ``secrets.compare_digest`` accepts ASCII-only ``str`` OR bytes-likes —
    # a non-ASCII ``str`` raises ``TypeError`` and would 500 the request
    # instead of returning the documented 403. Bytes comparison preserves
    # constant-time semantics and handles any header byte sequence.
    if not compare_digest(
        x_api_key.encode("utf-8"), settings.backend_api_key.encode("utf-8")
    ):
        log.warning(
            Events.AUTH_INVALID_KEY,
            api_key_prefix=x_api_key[:8],
            client_ip=request.client.host if request.client else None,
            path=request.url.path,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "invalid_api_key",
                "message": "Invalid API key.",
            },
        )
    return x_api_key
