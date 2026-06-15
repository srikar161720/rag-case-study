"""Unit tests for ``configure_logging`` + ``RequestLoggingMiddleware``.

Split in two:

1. **Config** — the dev/prod renderer split and the shared processor
   chain (Fork 54). These mutate global structlog state, so an autouse
   fixture restores the app default after each test.
2. **Middleware** — a throwaway minimal FastAPI app carrying ONLY
   ``RequestLoggingMiddleware`` proves the request-lifecycle events fire,
   the ``request_id`` has the canonical ``req_<12 hex>`` shape, and it
   propagates both to ``request.state`` and (via contextvars) into
   downstream log events. Same "minimal app in isolation" pattern as
   ``tests/unit/api/test_security_headers.py``.

``structlog.testing.capture_logs`` bypasses the configured renderer, so
these assertions don't depend on whichever renderer is active (it also
keeps working because ``cache_logger_on_first_use=False`` — see the
``logging`` module docstring).
"""

import re
from collections.abc import Iterator

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from customs_agent.observability.events import Events
from customs_agent.observability.logging import RequestLoggingMiddleware, configure_logging
from customs_agent.observability.scrubber import scrub_secrets

_REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{12}$")


@pytest.fixture(autouse=True)
def _restore_logging_config() -> Iterator[None]:
    """Restore the app's default config after each test mutates it."""
    yield
    configure_logging()


def _build_app() -> FastAPI:
    """Minimal app with only the request-logging middleware + 2 routes."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str]:
        # Log a bare event with NO explicit request_id — if it shows up in
        # the captured event, it can only have arrived via the contextvar.
        structlog.get_logger().info("probe.inside")
        return {"request_id": request.state.request_id}

    @app.get("/boom")
    async def boom(request: Request) -> dict[str, str]:
        raise RuntimeError("kaboom")

    return app


# ─────────────────────────────────────────────────────────────────────────────
# 1. Config — renderer split + processor chain
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_development_uses_console_renderer() -> None:
    configure_logging("development")
    renderer = structlog.get_config()["processors"][-1]
    assert isinstance(renderer, structlog.dev.ConsoleRenderer)


@pytest.mark.unit
def test_production_uses_json_renderer() -> None:
    configure_logging("production")
    renderer = structlog.get_config()["processors"][-1]
    assert isinstance(renderer, structlog.processors.JSONRenderer)


@pytest.mark.unit
def test_shared_processors_include_contextvars_and_scrubber() -> None:
    """merge_contextvars (request_id) and scrub_secrets (redaction) must
    both be wired, with the scrubber present on every event."""
    configure_logging("production")
    processors = structlog.get_config()["processors"]
    assert merge_contextvars in processors
    assert scrub_secrets in processors
    assert structlog.processors.add_log_level in processors
    # 4 shared processors + 1 renderer.
    assert len(processors) == 5


@pytest.mark.unit
def test_configure_logging_is_idempotent() -> None:
    """Calling twice doesn't raise and leaves a stable chain length."""
    configure_logging("production")
    first = len(structlog.get_config()["processors"])
    configure_logging("production")
    assert len(structlog.get_config()["processors"]) == first


# ─────────────────────────────────────────────────────────────────────────────
# 2. Middleware — lifecycle events + request_id propagation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_request_received_and_completed_emitted() -> None:
    client = TestClient(_build_app())
    with capture_logs(processors=[merge_contextvars]) as logs:
        resp = client.get("/probe")
    assert resp.status_code == 200

    received = [e for e in logs if e["event"] == Events.REQUEST_RECEIVED]
    completed = [e for e in logs if e["event"] == Events.REQUEST_COMPLETED]
    assert len(received) == 1
    assert len(completed) == 1

    assert received[0]["path"] == "/probe"
    assert received[0]["method"] == "GET"
    assert "client_ip" in received[0]
    assert "content_length" in received[0]  # length-only metadata (Fork 52)

    assert completed[0]["status"] == 200
    assert isinstance(completed[0]["latency_ms"], int)
    assert completed[0]["latency_ms"] >= 0


@pytest.mark.unit
def test_request_id_has_canonical_format() -> None:
    client = TestClient(_build_app())
    with capture_logs(processors=[merge_contextvars]) as logs:
        resp = client.get("/probe")

    received = next(e for e in logs if e["event"] == Events.REQUEST_RECEIVED)
    assert _REQUEST_ID_RE.match(received["request_id"])
    # Same id surfaced to the route via request.state.
    assert resp.json()["request_id"] == received["request_id"]


@pytest.mark.unit
def test_request_id_propagates_to_downstream_event_via_contextvars() -> None:
    """The bare ``probe.inside`` event (no explicit request_id kwarg)
    carries the request_id — proof the contextvar bound in the middleware
    reaches the route handler."""
    client = TestClient(_build_app())
    with capture_logs(processors=[merge_contextvars]) as logs:
        client.get("/probe")

    inside = next(e for e in logs if e["event"] == "probe.inside")
    received = next(e for e in logs if e["event"] == Events.REQUEST_RECEIVED)
    assert inside["request_id"] == received["request_id"]


@pytest.mark.unit
def test_each_request_gets_a_distinct_request_id() -> None:
    client = TestClient(_build_app())
    with capture_logs(processors=[merge_contextvars]) as logs:
        client.get("/probe")
        client.get("/probe")
    ids = [e["request_id"] for e in logs if e["event"] == Events.REQUEST_RECEIVED]
    assert len(ids) == 2
    assert ids[0] != ids[1]


@pytest.mark.unit
def test_request_failed_emitted_on_unhandled_exception() -> None:
    # raise_server_exceptions=False so the 500 is returned (the middleware
    # still logs request.failed before re-raising into ServerErrorMiddleware).
    client = TestClient(_build_app(), raise_server_exceptions=False)
    with capture_logs(processors=[merge_contextvars]) as logs:
        resp = client.get("/boom")
    assert resp.status_code == 500

    failed = [e for e in logs if e["event"] == Events.REQUEST_FAILED]
    assert len(failed) == 1
    assert failed[0]["error_class"] == "RuntimeError"
    assert failed[0]["error_message"] == "kaboom"
    assert failed[0]["path"] == "/boom"
    # No request.completed on the failure path.
    assert not [e for e in logs if e["event"] == Events.REQUEST_COMPLETED]
