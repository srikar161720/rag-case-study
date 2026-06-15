"""End-to-end coverage that ``RequestLoggingMiddleware`` rides on the real
FastAPI app's pipeline (Fork 52).

Unit-level coverage of the middleware in isolation lives at
``tests/unit/observability/test_logging.py`` (throwaway minimal app).
THIS file proves the middleware is actually wired into ``main.py``'s
stack and fires on real routes — including the error-response path where
an inner ``Depends(require_api_key)`` rejects with 401 but the request
still completes (the response flows back out through the middleware).

``capture_logs`` wraps only the request call, so the boot-time
``data.validation.complete`` event (emitted once at lifespan setup,
before the fixture yields) never pollutes the captured stream.
"""

import re

import pytest
from fastapi.testclient import TestClient
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from customs_agent.observability.events import Events

_REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{12}$")


@pytest.mark.integration
def test_lifecycle_events_fire_on_real_app(client: TestClient) -> None:
    """``GET /health`` (auth-exempt) emits paired received/completed events
    sharing one canonical request_id."""
    with capture_logs(processors=[merge_contextvars]) as logs:
        resp = client.get("/health")
    assert resp.status_code == 200

    received = [e for e in logs if e["event"] == Events.REQUEST_RECEIVED]
    completed = [e for e in logs if e["event"] == Events.REQUEST_COMPLETED]
    assert len(received) == 1
    assert len(completed) == 1
    assert received[0]["path"] == "/health"
    assert _REQUEST_ID_RE.match(received[0]["request_id"])
    assert completed[0]["request_id"] == received[0]["request_id"]
    assert completed[0]["status"] == 200


@pytest.mark.integration
def test_request_completed_logs_status_on_auth_rejection(client: TestClient) -> None:
    """A 401 from the inner ``require_api_key`` dependency still produces a
    ``request.completed`` with ``status=401`` — the middleware is outer to
    the route/exception handling, so it observes the final response."""
    with capture_logs(processors=[merge_contextvars]) as logs:
        resp = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 401

    completed = [e for e in logs if e["event"] == Events.REQUEST_COMPLETED]
    assert len(completed) == 1
    assert completed[0]["status"] == 401
    assert completed[0]["path"] == "/chat"
