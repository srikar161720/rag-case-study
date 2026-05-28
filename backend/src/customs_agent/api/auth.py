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

from fastapi import Header, HTTPException, status

from customs_agent.config import settings


async def require_api_key(
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "missing_api_key",
                "message": "X-API-Key header required.",
            },
            headers={"WWW-Authenticate": 'ApiKey realm="customs-agent"'},
        )
    if not compare_digest(x_api_key, settings.backend_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "invalid_api_key",
                "message": "Invalid API key.",
            },
        )
    return x_api_key
