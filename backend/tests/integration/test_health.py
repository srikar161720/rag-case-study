"""Integration tests for ``GET /health`` (Fork 40).

``/health`` is the cheap liveness probe Fly hits every 30 seconds. It
must:

- Return 200 with ``{"status": "ok"}``.
- Carry the four defensive security headers (the middleware stack is
  outermost, so they stamp every response — including the trivial
  ones).
- Stay unauthenticated — Fly's health-check engine can't easily inject
  a custom header, so the endpoint must NOT require ``X-API-Key``.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_health_returns_ok(client: TestClient) -> None:
    """200 + ``{"status": "ok"}`` body."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_health_is_unauthenticated(client: TestClient) -> None:
    """No ``X-API-Key`` header required — Fly's health-checker can't
    inject one, so the endpoint must stay public."""
    response = client.get("/health")
    # 200 with NO X-API-Key header sent — the absence of the header
    # would normally trip the require_api_key Depends but /health is
    # deliberately undecorated.
    assert response.status_code == 200


@pytest.mark.integration
def test_health_carries_security_headers(client: TestClient) -> None:
    """The 4 defensive headers ride on every response, including the
    cheap liveness probe."""
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert (
        response.headers["strict-transport-security"]
        == "max-age=63072000; includeSubDomains"
    )
