"""CORS middleware with rejected-preflight logging (Forks 38, 52).

Starlette's :class:`CORSMiddleware` silently rejects a disallowed-origin
preflight — it returns ``400`` WITHOUT the ``Access-Control-Allow-Origin``
header and offers no hook to observe it. For the security event taxonomy
we need a ``cors.preflight_rejected`` signal, so this thin subclass
overrides :meth:`preflight_response` (the method ``CORSMiddleware`` uses
to build the OPTIONS preflight reply): it defers to the parent for the
actual response, and when the parent returns a non-200 (origin / method /
header failed the allowlist) it emits the event before returning.

Allowed-origin preflights are untouched — they still return ``200`` with
the CORS headers, exactly as the stock middleware does.

This overrides an internal Starlette method, so it's mildly
version-sensitive; ``tests/integration/test_cors.py`` is the canary if a
Starlette upgrade changes the preflight contract.
"""

import structlog
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from customs_agent.observability.events import Events

log = structlog.get_logger()


class LoggingCORSMiddleware(CORSMiddleware):
    """:class:`CORSMiddleware` that logs rejected preflight requests."""

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        if response.status_code != 200:
            log.warning(
                Events.CORS_PREFLIGHT_REJECTED,
                origin=request_headers.get("origin"),
                method=request_headers.get("access-control-request-method"),
            )
        return response
