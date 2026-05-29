"""Integration tests for ``CORSMiddleware`` configuration (Fork 38).

The test ``ALLOWED_ORIGINS`` env var (set in ``tests/conftest.py``)
is ``http://localhost:3000`` — exactly one exact-match origin, no
regex entries. The CORS middleware should:

- Accept preflight ``OPTIONS`` requests from the allowed origin and
  return ``Access-Control-Allow-Origin`` matching it.
- Reject (omit the CORS allow-origin header on) requests from any
  origin not in the allowlist. starlette's CORSMiddleware doesn't
  return an error status for disallowed origins — it just omits the
  ``Access-Control-Allow-Origin`` header so the browser blocks the
  request client-side.
- Cache preflight via ``Access-Control-Max-Age: 3600`` so browsers
  don't re-preflight on every cross-origin call.

CORS is a defense-in-depth control here — primary protection is the
API-key auth — but mis-wiring it would surface as "the demo works
locally but the deployed frontend can't talk to the backend", which
is exactly the silent failure mode the spec wants caught early.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_cors_preflight_from_allowed_origin_succeeds(
    client: TestClient,
) -> None:
    """Browser preflight from ``http://localhost:3000`` returns 200
    with the allow-origin header echoed back."""
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key,Content-Type",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin")
        == "http://localhost:3000"
    )


@pytest.mark.integration
def test_cors_preflight_from_disallowed_origin_omits_allow_header(
    client: TestClient,
) -> None:
    """Disallowed origin gets a response WITHOUT the
    ``Access-Control-Allow-Origin`` header — starlette's silent
    rejection mode. Browser sees the missing header and blocks the
    request client-side."""
    response = client.options(
        "/chat",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key,Content-Type",
        },
    )
    # starlette's CORSMiddleware returns the request through anyway —
    # the absence of the allow-origin header is the actual signal to
    # the browser.
    assert "access-control-allow-origin" not in {
        k.lower() for k in response.headers
    }


@pytest.mark.integration
def test_cors_preflight_advertises_allowed_methods(
    client: TestClient,
) -> None:
    """Preflight response advertises GET/POST/OPTIONS as allowed."""
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    allow_methods = response.headers.get("access-control-allow-methods", "")
    for method in ("GET", "POST", "OPTIONS"):
        assert method in allow_methods


@pytest.mark.integration
def test_cors_preflight_caches_for_one_hour(client: TestClient) -> None:
    """``max_age=3600`` echoes back as ``Access-Control-Max-Age: 3600``
    so the browser doesn't re-preflight on every cross-origin call."""
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-max-age") == "3600"
