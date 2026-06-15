"""End-to-end coverage of :class:`SecurityHeadersMiddleware` (Fork 51).

Unit-level coverage lives at
``tests/unit/api/test_security_headers.py`` — that file uses a
throwaway minimal app to prove the middleware code works in
isolation. THIS file proves the middleware actually rides on the
real FastAPI app's response pipeline, including on error paths
(401, 422, 403) and short-circuit paths (slowapi 429) where the
inner middleware returns a response WITHOUT calling next.

The four headers tested below are the canonical set from the spec
(``context/05-api-and-backend.md`` §"Security headers"); a deviation
would silently downgrade the browser defenses, so we anchor on exact
values rather than just header presence.

The middleware-order assertion + the 429 short-circuit test together
form the canonical regression guard for the Starlette
``add_middleware`` prepend behavior: any future refactor that
accidentally re-introduces the reversed order (SEM as innermost user
middleware instead of outermost) would fail both tests.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from customs_agent.api._rate_limit import composite_key, custom_rate_limit_handler
from customs_agent.api._security_headers import SecurityHeadersMiddleware

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "strict-transport-security": "max-age=63072000; includeSubDomains",
}


@pytest.mark.integration
def test_security_headers_on_200(
    client: TestClient, valid_headers: dict[str, str]
) -> None:
    """``GET /api/starter-prompts`` 200 — all 4 headers present."""
    response = client.get("/api/starter-prompts", headers=valid_headers)
    assert response.status_code == 200
    for header, expected in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected


@pytest.mark.integration
def test_security_headers_on_401(client: TestClient) -> None:
    """``POST /chat`` without API key returns 401 — middleware still
    stamps headers because it's the outermost layer."""
    response = client.post(
        "/chat", json={"messages": [{"role": "user", "content": "hi"}]}
    )
    assert response.status_code == 401
    for header, expected in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected


@pytest.mark.integration
def test_security_headers_on_422(
    client: TestClient, valid_headers: dict[str, str]
) -> None:
    """``POST /chat`` with an oversized message body triggers Pydantic
    422 — the headers must still be stamped on the validation error
    response."""
    # Message content is capped at 2000 chars by Pydantic
    # (``Message.content = Field(max_length=2000)``). 2001 chars trips
    # the validator without touching the agent loop.
    oversized = "x" * 2001
    response = client.post(
        "/chat",
        headers=valid_headers,
        json={"messages": [{"role": "user", "content": oversized}]},
    )
    assert response.status_code == 422
    for header, expected in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected


@pytest.mark.integration
def test_security_headers_on_403(client: TestClient) -> None:
    """``POST /chat`` with a wrong key returns 403 — headers ride
    through the auth-rejection path too."""
    response = client.post(
        "/chat",
        headers={"X-API-Key": "wrong-key-value"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 403
    for header, expected in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected


# ─────────────────────────────────────────────────────────────────────────────
# Middleware-order regression guards
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_main_app_user_middleware_outermost_is_security_headers() -> None:
    """``SecurityHeadersMiddleware`` must wrap every other user middleware
    so 4xx/5xx + 429 + CORS preflight all carry the defensive headers.

    Starlette's ``add_middleware`` does ``user_middleware.insert(0, ...)``
    — the LAST call ends up at index 0 (outermost user mw) and the
    FIRST call ends up at index -1 (innermost). Asserts the order
    matches the spec's intent (which the inline comments in
    ``main.py`` explain at length). A future refactor that re-adds
    middlewares in the wrong order will fail HERE before it ever
    ships, rather than failing silently at runtime on 429 + preflight
    responses.
    """
    from customs_agent.main import app

    classes = [mw.cls.__name__ for mw in app.user_middleware]
    assert classes[0] == "SecurityHeadersMiddleware", (
        f"SEM must be outermost user middleware; got order: {classes}"
    )
    assert classes[-1] == "RequestLoggingMiddleware", (
        f"RequestLogging must be innermost user middleware; got order: {classes}"
    )
    assert "CORSMiddleware" in classes
    assert "SlowAPIMiddleware" in classes


@pytest.fixture(scope="module")
def headers_on_429_client() -> Iterator[TestClient]:
    """Mini app mirroring ``main.py``'s middleware stack + a tiny
    rate-limited probe route. Required because the session-scoped
    ``client`` runs with ``RATELIMIT_ENABLED=false`` (so we can't
    trigger 429 against it) AND ``test_rate_limit.py``'s fixture
    omits ``SecurityHeadersMiddleware`` (it was built before the
    middleware-order fix landed). This fixture is the canonical
    "real stack + rate limit + 429 hits a route" probe.

    Same ``RATELIMIT_ENABLED`` env toggle as
    ``test_rate_limit.py:rate_limit_client`` to work around the
    slowapi 0.1.9 env override of the constructor ``enabled=`` flag.
    """
    original_env = os.environ.get("RATELIMIT_ENABLED")
    os.environ["RATELIMIT_ENABLED"] = "true"

    try:
        test_limiter = Limiter(
            key_func=composite_key,
            default_limits=[],
            enabled=True,
            storage_uri="memory://",
        )

        app = FastAPI()
        app.state.limiter = test_limiter
        app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)  # type: ignore[arg-type]
        # Same add order as main.py: inner → outer. SEM last → outermost.
        app.add_middleware(SlowAPIMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/probe")
        @test_limiter.limit("2/minute")
        async def probe(request: Request) -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app) as test_client:
            yield test_client
    finally:
        if original_env is None:
            os.environ.pop("RATELIMIT_ENABLED", None)
        else:
            os.environ["RATELIMIT_ENABLED"] = original_env


@pytest.mark.integration
def test_security_headers_on_429(headers_on_429_client: TestClient) -> None:
    """slowapi's 429 short-circuits ``call_next``, returning the
    response BEFORE the route handler runs. Pre-fix, SEM was inner
    to slowapi → never saw the 429 → 429s shipped without security
    headers. Post-fix, SEM is OUTER to slowapi → SEM's
    ``await call_next`` returns the 429, then SEM stamps headers on
    the way out. This test proves the post-fix behavior."""
    headers = {"X-API-Key": "burst-test-aaaa"}
    headers_on_429_client.get("/probe", headers=headers)
    headers_on_429_client.get("/probe", headers=headers)
    response = headers_on_429_client.get("/probe", headers=headers)

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    for header, expected in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected, (
            f"missing {header!r} on 429 response — middleware order regression?"
        )


@pytest.mark.integration
def test_security_headers_on_cors_preflight(client: TestClient) -> None:
    """CORSMiddleware short-circuits on OPTIONS preflight requests,
    returning a 200 response BEFORE the route handler runs (same
    short-circuit pattern as slowapi's 429). Pre-fix, SEM was inner
    to CORS → never saw the preflight response → preflights shipped
    without security headers. Post-fix, SEM is OUTER to CORS → SEM
    stamps headers on the preflight 200 on the way out."""
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key,Content-Type",
        },
    )
    assert response.status_code == 200
    for header, expected in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected, (
            f"missing {header!r} on CORS preflight — middleware order regression?"
        )
