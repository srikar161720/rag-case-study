"""Canonical stdout-JSON event taxonomy (Fork 52).

Single source of truth for every structured-log event name the backend
emits. Every ``log.info`` / ``log.warning`` / ``log.error`` call across
the codebase references a constant here instead of a string literal, so
the taxonomy can't silently drift and a grep for ``Events.`` surfaces
every emission site.

Naming convention: dot-separated ``<domain>.<verb>`` (see
``context/10-observability.md`` §"Event Taxonomy"). Adding a new event
is a deliberate change — add the constant here first, then emit it.

Some constants name events whose *emission* lands on a later branch
(``agent.trace_created`` / ``langfuse.flush_failed`` →
``feat/langfuse-traces``; ``output_safety.redaction`` →
``feat/security-hardening``). They live here now so the taxonomy is
complete and downstream code has a stable name to import.
"""

from typing import Final


class Events:
    """Namespace of canonical event-name string constants.

    Grouped by domain. Values are the exact strings emitted to stdout —
    ``fly logs | jq 'select(.event == "...")'`` filters key off them, so
    they are part of the observability contract and must stay stable.
    """

    # ── HTTP request lifecycle (RequestLoggingMiddleware, Fork 52) ──────────
    REQUEST_RECEIVED: Final = "request.received"
    REQUEST_COMPLETED: Final = "request.completed"
    REQUEST_FAILED: Final = "request.failed"

    # ── Authentication (api/auth.py, Fork 48) ───────────────────────────────
    AUTH_MISSING_KEY: Final = "auth.missing_key"
    AUTH_INVALID_KEY: Final = "auth.invalid_key"

    # ── Rate limiting (api/_rate_limit.py, Fork 47) ─────────────────────────
    RATELIMIT_HIT: Final = "ratelimit.hit"

    # ── CORS (api/_cors.py, Fork 38) ────────────────────────────────────────
    CORS_PREFLIGHT_REJECTED: Final = "cors.preflight_rejected"

    # ── Agent loop (agent/loop.py, Forks 23, 25) ────────────────────────────
    AGENT_RUN_STARTED: Final = "agent.run.started"
    AGENT_RUN_COMPLETED: Final = "agent.run.completed"
    AGENT_REFUSAL: Final = "agent.refusal"
    # Renamed from the originally-shipped ``agent.iteration_limit_hit`` to
    # match the canonical taxonomy table (context/10-observability.md).
    AGENT_ITERATION_LIMIT: Final = "agent.iteration_limit"
    AGENT_DUPLICATE_TOOL_CALL: Final = "agent.duplicate_tool_call"
    AGENT_INPUT_TOKEN_BUDGET_HIT: Final = "agent.input_token_budget_hit"
    AGENT_TOOL_ERROR: Final = "agent.tool_error"
    AGENT_UNEXPECTED_STOP_REASON: Final = "agent.unexpected_stop_reason"
    AGENT_UNKNOWN_REFUSAL_CATEGORY: Final = "agent.unknown_refusal_category"

    # ── Output validation (agent/validator.py, Fork 28) ─────────────────────
    AGENT_HALLUCINATED_CITATION: Final = "agent.hallucinated_citation"

    # ── SQL safety (tools/, Fork 50) ────────────────────────────────────────
    SQL_SAFETY_INVALID_COLUMN_NAME: Final = "sql_safety.invalid_column_name"
    SQL_SAFETY_UNSAFE_SQL_BLOCKED: Final = "sql_safety.unsafe_sql_blocked"

    # ── Boot-time data validation (data/validation.py, Fork 18) ─────────────
    DATA_VALIDATION_COMPLETE: Final = "data.validation.complete"

    # ── Deferred — emission lands on a later branch (see module docstring) ──
    OUTPUT_SAFETY_REDACTION: Final = "output_safety.redaction"
    AGENT_TRACE_CREATED: Final = "agent.trace_created"
    LANGFUSE_FLUSH_FAILED: Final = "langfuse.flush_failed"
