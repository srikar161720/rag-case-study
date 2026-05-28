"""Unit tests for :mod:`customs_agent.api._rate_limit`.

Two surfaces under test:

1. :func:`composite_key` — pure function over a Request. The bucket
   shape is the foundation of "one tenant can't starve another", so
   we exercise the authenticated, anonymous, and missing-client paths
   independently.
2. :func:`custom_rate_limit_handler` — the 429 JSONResponse shape.
   Called directly with a constructed :class:`RateLimitExceeded` so
   the test catches slowapi 0.1.9 signature drift before it surfaces
   as a 500 in integration tests.

The :class:`Limiter` instance itself is exercised end-to-end on the
integration branches (chunk 3b); no unit coverage of slowapi internals
is needed here.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from slowapi.errors import RateLimitExceeded

from customs_agent.api._rate_limit import (
    composite_key,
    custom_rate_limit_handler,
)

# ─────────────────────────────────────────────────────────────────────────────
# composite_key
# ─────────────────────────────────────────────────────────────────────────────


def _make_request(*, api_key: str | None, host: str | None) -> Request:
    """Build a minimal :class:`Request` stub with just the attributes
    ``composite_key`` reads.

    starlette's Request requires a ``scope`` dict; we mock the read
    surface (``headers.get`` + ``client.host``) using ``SimpleNamespace``
    so we don't have to construct a full ASGI scope.
    """
    headers_dict = {"X-API-Key": api_key} if api_key else {}
    return SimpleNamespace(  # type: ignore[return-value]
        headers=SimpleNamespace(get=headers_dict.get),
        client=SimpleNamespace(host=host) if host else None,
    )


@pytest.mark.unit
def test_composite_key_with_key_and_ip() -> None:
    """Authenticated traffic: ``"{key[:8]}:{ip}"``."""
    req = _make_request(api_key="abcdefghij1234567890", host="10.0.0.1")
    assert composite_key(req) == "abcdefgh:10.0.0.1"


@pytest.mark.unit
def test_composite_key_truncates_to_8_chars() -> None:
    """Slicing caps storage and log-noise; 8 chars is enough isolation
    across the project's ~3-key population."""
    req = _make_request(api_key="x" * 100, host="1.2.3.4")
    bucket = composite_key(req)
    assert bucket == "xxxxxxxx:1.2.3.4"
    # The prefix is exactly 8 chars; the suffix is the IP.
    assert len(bucket.split(":")[0]) == 8


@pytest.mark.unit
def test_composite_key_anonymous_falls_back_to_ip() -> None:
    """No ``X-API-Key`` → ``"anon:{ip}"``."""
    req = _make_request(api_key=None, host="192.168.1.50")
    assert composite_key(req) == "anon:192.168.1.50"


@pytest.mark.unit
def test_composite_key_empty_key_treated_as_anonymous() -> None:
    """Empty string is falsy → routes through the anonymous branch."""
    req = _make_request(api_key="", host="172.16.0.1")
    assert composite_key(req) == "anon:172.16.0.1"


@pytest.mark.unit
def test_composite_key_missing_client_uses_unknown() -> None:
    """``request.client`` can be ``None`` under unusual Starlette
    transport configurations; we degrade to ``unknown`` rather than
    crashing."""
    req = _make_request(api_key="abcdefgh", host=None)
    assert composite_key(req) == "abcdefgh:unknown"


# ─────────────────────────────────────────────────────────────────────────────
# custom_rate_limit_handler
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_custom_rate_limit_handler_returns_429_with_retry_after() -> None:
    """Direct invocation of the handler: 429 status, ``Retry-After``
    header, JSON body matching the unified error contract.

    Catches slowapi 0.1.9 handler-signature regressions before they
    surface as 500s under TestClient (the Plan agent flagged this as
    landmine #1).
    """
    request = MagicMock(spec=Request)
    exc = RateLimitExceeded(MagicMock(error_message="20 per 1 minute"))

    response = await custom_rate_limit_handler(request, exc)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"  # default when exc has no retry_after

    body = json.loads(response.body)
    assert body["error"] == "rate_limited"
    assert body["retry_after"] == 60
    assert "Too many requests" in body["message"]
    assert "60 seconds" in body["message"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_custom_rate_limit_handler_honors_explicit_retry_after() -> None:
    """When the exception carries an explicit ``retry_after`` attribute,
    the handler propagates it into both the header and body."""
    request = MagicMock(spec=Request)
    exc = RateLimitExceeded(MagicMock(error_message="..."))
    exc.retry_after = 15  # type: ignore[attr-defined]

    response = await custom_rate_limit_handler(request, exc)

    assert response.headers["Retry-After"] == "15"
    body = json.loads(response.body)
    assert body["retry_after"] == 15
    assert "15 seconds" in body["message"]
