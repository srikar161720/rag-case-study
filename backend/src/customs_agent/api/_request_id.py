"""Interim request-ID middleware.

Sets ``request.state.request_id = str(uuid.uuid4())`` before any
downstream handler runs so the chat endpoint can read it and stamp
:attr:`customs_agent.agent.contracts.ResponseMeta.request_id`.

This middleware will be **replaced** on ``feat/observability-base`` by
:func:`customs_agent.observability.logging.request_logging_middleware`,
which does the request_id binding AND emits structured
``request.received`` / ``request.completed`` / ``request.failed`` JSON
log events. Keeping the interim binding in its own module means that
future branch deletes one file rather than carving the binding out of
``main.py`` — cleanly localized refactor.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp a fresh ``request_id`` UUID on every incoming request.

    The ID is exposed via ``request.state.request_id`` so route handlers
    and inner middleware can read it. We don't echo it back as a
    response header on this branch — that's part of the full logging
    middleware on ``feat/observability-base`` (so clients can correlate
    against Langfuse traces).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request.state.request_id = str(uuid.uuid4())
        return await call_next(request)
