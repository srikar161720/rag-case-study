"""Integration tests for the ``Depends(require_api_key)`` boundary
on the public endpoints (Fork 48).

Exercises the three branches at the HTTP layer:

- ``/chat`` without an ``X-API-Key`` header → 401 ``missing_api_key``.
- ``/chat`` with a wrong ``X-API-Key`` value → 403 ``invalid_api_key``.
- ``/chat`` with the correct key → reaches the handler (the handler
  itself touches ``run_agent`` which we don't want to invoke here —
  the body asserts via the 422 Pydantic rejection on a deliberately
  empty payload, which is enough to prove the auth gate passed).
- ``/health`` and ``/ready`` stay exempt (no ``X-API-Key`` required).

The unit-level coverage of ``require_api_key`` lives at
``tests/unit/api/test_auth.py``; this file proves the dependency is
actually wired on each protected route and that the exempt routes
stay public.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_chat_without_key_returns_401(client: TestClient) -> None:
    """``POST /chat`` with no header → 401 ``missing_api_key``."""
    response = client.post(
        "/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "missing_api_key"


@pytest.mark.integration
def test_chat_with_invalid_key_returns_403(client: TestClient) -> None:
    """``POST /chat`` with wrong key value → 403 ``invalid_api_key``."""
    response = client.post(
        "/chat",
        headers={"X-API-Key": "wrong-key"},
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "invalid_api_key"


@pytest.mark.integration
def test_chat_with_valid_key_passes_auth_gate(
    client: TestClient, valid_headers: dict[str, str]
) -> None:
    """With the right key, the auth dependency lets the request through —
    we prove this by sending an INVALID body and getting 422 (Pydantic
    rejection at the handler boundary) rather than the 401/403 the auth
    layer would have produced.

    This avoids invoking ``run_agent`` in this test file — chat round-
    trips with a stubbed Anthropic client are in ``test_chat.py``.
    """
    response = client.post(
        "/chat",
        headers=valid_headers,
        json={"messages": []},  # min_length=1 violated
    )
    assert response.status_code == 422  # Pydantic ValidationError, NOT 401/403


@pytest.mark.integration
def test_health_is_exempt_from_auth(client: TestClient) -> None:
    """``/health`` returns 200 with no ``X-API-Key`` header — Fly's
    health-checker can't easily inject one."""
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.integration
def test_ready_is_exempt_from_auth(client: TestClient) -> None:
    """``/ready`` returns 200 (or 503) with no ``X-API-Key`` header —
    public exposure of the manifest is intentional and safe."""
    response = client.get("/ready")
    # Status may be 200 (happy path) or 503 (degraded); either confirms
    # the request reached the handler rather than getting bounced by
    # the auth layer with 401.
    assert response.status_code in (200, 503)
