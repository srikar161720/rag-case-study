"""structlog boot configuration + request-logging middleware (Forks 52, 54).

Two responsibilities:

1. :func:`configure_logging` — the single ``structlog.configure`` call.
   Production (``ENVIRONMENT=production``, set in ``fly.toml``) renders
   one-line JSON for ``fly logs | jq``; local dev renders pretty colored
   console output. Called once at ``main.py`` import so every
   ``structlog.get_logger()`` caller — including the boot-time
   ``data.validation.complete`` event — picks up the full processor chain
   automatically (resolves CLAUDE.md Gotcha #11).

2. :class:`RequestLoggingMiddleware` — binds a fresh ``request_id`` to
   both ``request.state`` (so endpoints read it the same way they did
   under the interim ``RequestIdMiddleware`` it replaces) and to a
   structlog contextvar (so every downstream event — auth, rate-limit,
   agent — is automatically stamped with it via ``merge_contextvars``).
   Emits ``request.received`` / ``request.completed`` / ``request.failed``.

``cache_logger_on_first_use`` is deliberately left ``False`` (the
structlog default), diverging from the ``context/10-observability.md``
snippet which sets it ``True``: with the config running at import time,
caching a bound logger on first use would make
``structlog.testing.capture_logs`` (used by 5 existing unit tests) unable
to intercept that logger, since the cached logger bypasses the temporary
processor swap. The micro-optimization caching buys is irrelevant at
demo request volumes.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.typing import Processor

from customs_agent.config import settings
from customs_agent.observability.events import Events
from customs_agent.observability.scrubber import scrub_secrets

log = structlog.get_logger()


def configure_logging(environment: str | None = None) -> None:
    """Configure structlog once. JSON in production, colored console in dev.

    Parameters
    ----------
    environment
        ``"production"`` selects :class:`structlog.processors.JSONRenderer`;
        anything else (default ``"development"``) selects
        :class:`structlog.dev.ConsoleRenderer`. Defaults to
        ``settings.environment`` when ``None`` — tests pass an explicit
        value to exercise both renderers without monkeypatching settings.
    """
    env = environment if environment is not None else settings.environment

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # request_id flows in here
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        scrub_secrets,  # Fork 53 — redact secret-shape strings last
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if env == "production"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,  # see module docstring
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Stamp + log a ``request_id`` on every request (Fork 52).

    Replaces the interim ``api/_request_id.py``. Kept as a named
    ``BaseHTTPMiddleware`` subclass (rather than an ``app.middleware("http")``
    function) for symmetry with the other ``api/`` middlewares and so the
    middleware-order canary in
    ``tests/integration/test_security_headers.py`` can assert on the class
    name. Must be added FIRST in ``main.py`` so it ends up innermost —
    ``request.state.request_id`` is then set before any route or
    ``Depends`` runs (Starlette prepends; see CLAUDE.md Gotcha #14).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        api_key = request.headers.get("X-API-Key", "")
        log.info(
            Events.REQUEST_RECEIVED,
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            client_ip=request.client.host if request.client else None,
            # api_key_prefix: first 8 chars only — never the full key (Fork 48).
            api_key_prefix=api_key[:8] if api_key else None,
            # content_length: length-only body metadata — never body content.
            # Read from the header so the request stream is never consumed
            # (Fork 52). The precise per-message char count lands separately
            # on agent.run.started (agent/loop.py).
            content_length=request.headers.get("content-length"),
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log.error(
                Events.REQUEST_FAILED,
                request_id=request_id,
                path=request.url.path,
                error_class=type(exc).__name__,
                error_message=str(exc),
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            raise
        else:
            log.info(
                Events.REQUEST_COMPLETED,
                request_id=request_id,
                path=request.url.path,
                status=response.status_code,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            return response
        finally:
            structlog.contextvars.clear_contextvars()
