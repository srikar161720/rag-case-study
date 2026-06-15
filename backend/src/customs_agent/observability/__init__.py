"""Observability layer — structlog stdout-JSON event logging (Forks 52-54).

The stdout sink (this package) captures app-level events; the Langfuse
sink (agent reasoning traces) lands on ``feat/langfuse-traces``. Both
join on the same ``request_id``. See ``context/10-observability.md``.

Public surface:

- :class:`Events` — canonical event-name taxonomy.
- :func:`configure_logging` — the single ``structlog.configure`` call.
- :class:`RequestLoggingMiddleware` — request_id binding + lifecycle logs.
- :data:`log` — module-level bound logger for ad-hoc use.
"""

from customs_agent.observability.events import Events
from customs_agent.observability.logging import (
    RequestLoggingMiddleware,
    configure_logging,
    log,
)

__all__ = [
    "Events",
    "RequestLoggingMiddleware",
    "configure_logging",
    "log",
]
