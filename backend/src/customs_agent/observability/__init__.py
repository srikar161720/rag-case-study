"""Observability layer — structlog stdout-JSON event logging (Forks 52-54).

The stdout sink (this package) captures app-level events; the Langfuse
sink (agent reasoning traces) lands on ``feat/langfuse-traces``. Both
join on the same ``request_id``. See ``context/10-observability.md``.

Import from the submodules directly:

- ``from customs_agent.observability.events import Events`` — canonical
  event-name taxonomy (pure stdlib; safe to import from any leaf module).
- ``from customs_agent.observability.logging import configure_logging,
  RequestLoggingMiddleware, log`` — the structlog boot config + the
  request-id middleware (pulls in ``config.settings`` + the scrubber).

This package ``__init__`` intentionally stays import-free so that pulling
in :class:`Events` from data/tools/agent leaf modules doesn't transitively
load the settings + logging stack.
"""
