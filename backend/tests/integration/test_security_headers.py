"""End-to-end coverage of :class:`SecurityHeadersMiddleware` (Fork 51).

Unit-level coverage lives at
``tests/unit/api/test_security_headers.py`` — that file uses a
throwaway minimal app to prove the middleware code works in
isolation. THIS file proves the middleware actually rides on the
real FastAPI app's response pipeline, including on error paths
(401, 422). The 429 case lands in ``test_rate_limit.py`` (where rate
limiting is actually enabled).

The four headers tested below are the canonical set from the spec
(``context/05-api-and-backend.md`` §"Security headers"); a deviation
would silently downgrade the browser defenses, so we anchor on exact
values rather than just header presence.
"""

import pytest
from fastapi.testclient import TestClient

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
