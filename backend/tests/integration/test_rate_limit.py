"""Integration tests for the slowapi rate-limit machinery (Fork 47).

The whole integration suite runs with ``RATELIMIT_ENABLED=false``
(set in ``tests/conftest.py``) so the module-level ``limiter`` is
inert for tests that aren't exercising the limit. THIS file builds a
SEPARATE FastAPI app with its own ``Limiter`` instance — ``enabled=True``,
``2/minute`` ceiling — and asserts the 429 path + bucket separation
end-to-end.

The unit-level coverage of ``composite_key`` and the
``custom_rate_limit_handler`` shape lives at
``tests/unit/api/test_rate_limit.py``; this file proves the wiring
actually rejects bursts in a real Starlette + slowapi pipeline,
including the catch for the slowapi 0.1.9 handler-signature bug the
Plan agent flagged.

slowapi quirk: ``Limiter`` reads ``RATELIMIT_ENABLED`` from the
environment in its constructor and OVERRIDES the explicit
``enabled=True`` parameter (see slowapi/extension.py:234). The fixture
below toggles the env var to ``"true"`` around the Limiter construction
so the test instance actually enforces — restoring the prior value on
teardown so other integration tests (which depend on the disabled
default) stay unaffected.
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


@pytest.fixture(scope="module")
def rate_limit_client() -> Iterator[TestClient]:
    """Fresh FastAPI app with limiter enabled + tiny ``2/minute`` cap.

    Building a NEW app (rather than mutating the global ``limiter``)
    keeps the session-scoped ``client`` fixture unaffected for the
    other integration tests in this directory. The env-var toggle
    around the Limiter construction works around slowapi's
    ``RATELIMIT_ENABLED`` env override of the constructor flag.
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
        app.add_middleware(SlowAPIMiddleware)

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
def test_rate_limit_allows_under_threshold(
    rate_limit_client: TestClient,
) -> None:
    """First N requests under the limit succeed."""
    headers = {"X-API-Key": "burst-test-key-aaaa"}
    r1 = rate_limit_client.get("/probe", headers=headers)
    r2 = rate_limit_client.get("/probe", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.integration
def test_rate_limit_returns_429_after_threshold(
    rate_limit_client: TestClient,
) -> None:
    """Third request (N+1) gets 429 with the spec error shape +
    ``Retry-After`` header."""
    headers = {"X-API-Key": "exhausted-key-bbbb"}
    rate_limit_client.get("/probe", headers=headers)
    rate_limit_client.get("/probe", headers=headers)
    response = rate_limit_client.get("/probe", headers=headers)

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    body = response.json()
    assert body["error"] == "rate_limited"
    assert body["retry_after"] > 0
    assert "Too many requests" in body["message"]


@pytest.mark.integration
def test_rate_limit_buckets_separate_by_api_key(
    rate_limit_client: TestClient,
) -> None:
    """Two distinct keys (different first-8-char prefixes) hit their
    own buckets — exhausting one doesn't 429 the other."""
    # First key exhausts its bucket.
    headers_a = {"X-API-Key": "key-aaaa-1111"}
    rate_limit_client.get("/probe", headers=headers_a)
    rate_limit_client.get("/probe", headers=headers_a)
    r3a = rate_limit_client.get("/probe", headers=headers_a)
    assert r3a.status_code == 429

    # Second key still has its full budget — composite_key truncates
    # to the first 8 chars, and "key-aaaa" != "key-bbbb" so the buckets
    # are independent.
    headers_b = {"X-API-Key": "key-bbbb-2222"}
    r1b = rate_limit_client.get("/probe", headers=headers_b)
    assert r1b.status_code == 200


@pytest.mark.integration
def test_rate_limit_anonymous_bucket_independent(
    rate_limit_client: TestClient,
) -> None:
    """Anonymous requests (no ``X-API-Key`` header) route to the
    ``"anon:{ip}"`` bucket — independent of any authenticated bucket."""
    headers = {"X-API-Key": "auth-bucket-cccc"}
    rate_limit_client.get("/probe", headers=headers)
    rate_limit_client.get("/probe", headers=headers)
    r_auth = rate_limit_client.get("/probe", headers=headers)
    assert r_auth.status_code == 429

    # No header → composite_key returns "anon:{ip}", a different bucket.
    r_anon = rate_limit_client.get("/probe")
    assert r_anon.status_code == 200
