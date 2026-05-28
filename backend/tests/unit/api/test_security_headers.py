"""Unit tests for :class:`customs_agent.api._security_headers.SecurityHeadersMiddleware`.

Tested via a minimal :class:`fastapi.FastAPI` app + :class:`TestClient`
rather than direct ``dispatch()`` invocation — the middleware's contract
is "every response carries these headers", so end-to-end is the right
grain even at the unit-test layer. The app has zero business logic; the
test is fast (<50 ms) and stays in ``tests/unit/`` because it doesn't
exercise any real backend infrastructure.

Coverage:
- All four headers present with their canonical values on a 200 response
- All four headers present on a 4xx error response (the headers must
  survive HTTPException paths since the middleware is outermost)
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from customs_agent.api._security_headers import SecurityHeadersMiddleware

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "strict-transport-security": "max-age=63072000; includeSubDomains",
}


def _build_app() -> FastAPI:
    """Construct a throwaway app with the middleware wired and two
    routes: one success, one that raises a typed HTTPException.
    """
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    def boom() -> None:
        raise HTTPException(status_code=418, detail="i am a teapot")

    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_build_app())


@pytest.mark.unit
def test_security_headers_present_on_200(client: TestClient) -> None:
    """200 OK response carries all 4 defensive headers."""
    response = client.get("/ok")
    assert response.status_code == 200
    for header, expected_value in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected_value, (
            f"missing or wrong value for {header!r}: "
            f"got {response.headers.get(header)!r}, expected {expected_value!r}"
        )


@pytest.mark.unit
def test_security_headers_present_on_error_response(client: TestClient) -> None:
    """4xx error responses ALSO carry the headers — the middleware is
    outermost, so it stamps every response including HTTPException
    paths."""
    response = client.get("/boom")
    assert response.status_code == 418
    for header, expected_value in EXPECTED_HEADERS.items():
        assert response.headers.get(header) == expected_value, (
            f"missing or wrong value for {header!r} on error response: "
            f"got {response.headers.get(header)!r}"
        )
