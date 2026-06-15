"""Shared utilities every tool depends on (Forks 22, 28, 50).

Three responsibilities:

1. **WHERE-clause builder** (:func:`build_where_clause`) — turns an
   ``EntryFilters`` instance into a parameterized SQL fragment with
   ``?`` placeholders. All user-controlled values flow as bound
   parameters, never as string interpolation. The first line of SQL
   injection defense per Fork 50.

2. **SELECT-only execution guardrail** (:func:`safe_execute`) — refuses
   to run any statement that doesn't start with ``SELECT`` or ``WITH``
   (the two SQL keywords that can yield a read-only result set on
   DuckDB). Defense-in-depth alongside the parameterization above; if a
   future tool author accidentally interpolates a value, the worst they
   can do is craft a SELECT.

3. **`ToolResult` envelope** (:class:`ToolResult`, :class:`ToolMeta`,
   :class:`Citation`) — every tool returns one of these so the agent
   loop and the sidecar builder (Fork 28) can uniformly extract data,
   build the show-work panel (Fork 31), and emit Langfuse spans
   (Fork 52) without per-tool special casing.

Citations are KB references the tool's *logic* relies on — they're the
chunks the agent should be able to cite for "why does this tool work
this way". They are NOT a record of which RAG chunks were retrieved at
runtime (those flow through a separate path).
"""

import time
from typing import Any

import duckdb
import structlog
from pydantic import BaseModel, ConfigDict, Field

from customs_agent.observability.events import Events
from customs_agent.tools._filters import EntryFilters

log = structlog.get_logger()

# ─────────────────────────────────────────────────────────────────────────────
# Result envelope (returned by every tool)
# ─────────────────────────────────────────────────────────────────────────────


class Citation(BaseModel):
    """KB reference a tool's logic relies on.

    ``chunk_id`` MUST match an entry in
    :data:`customs_agent.rag.chunker.CHUNKS_REGISTRY` so the agent loop's
    marker validator (Fork 28) can resolve it deterministically.
    """

    doc: str            # e.g., "duties_fees_tariffs.txt"
    section: str        # e.g., "§Business Rule 6 — On-Hold Entries"
    chunk_id: str       # CHUNKS_REGISTRY key, e.g., "rule_6_on_hold_entries"


class ToolMeta(BaseModel):
    """Operational metadata for the sidecar / show-work panel."""

    tool_name: str
    sql_executed: str | None              # None for non-SQL tools (lookup_knowledge)
    view_used: str | None                 # "entries_v" | "entry_lines_v" | None
    filters_applied: dict[str, Any]
    shell_entries_excluded: int           # 0 when include_shell=True or no shells
    rows_inspected: int
    latency_ms: int


class ToolResult(BaseModel):
    """Universal tool return shape.

    ``data`` is tool-specific (e.g., ``{rate_pct, total_duty, ...}``);
    ``meta`` and ``citations`` are uniform across all tools.
    """

    data: Any
    meta: ToolMeta
    # Use default_factory to match the rest of the codebase's Pydantic style
    # (every other defaultable field in this branch uses Field(default_factory=...)).
    # Pydantic v2 deep-copies field defaults per instance, so this is also safe
    # against the classic shared-mutable-default trap.
    citations: list[Citation] = Field(default_factory=list)

    # Permit Decimal / date / datetime in data without explicit converters.
    model_config = ConfigDict(arbitrary_types_allowed=True)


# ─────────────────────────────────────────────────────────────────────────────
# WHERE clause builder (Fork 50 — all values via ? placeholders)
# ─────────────────────────────────────────────────────────────────────────────


def build_where_clause(filters: EntryFilters) -> tuple[str, list[Any]]:
    """Convert filters into a parameterized SQL WHERE fragment.

    Parameters
    ----------
    filters
        Validated filter model. Period fields are mutually exclusive
        (enforced by ``EntryFilters`` validators); only one is active
        at any time.

    Returns
    -------
    tuple[str, list[Any]]
        ``(where_sql, params)`` suitable for splicing into
        ``f"SELECT ... WHERE {where_sql}"`` and passing as the second
        argument to :func:`safe_execute`.

        The fragment is **always non-empty** so callers can splice it
        unconditionally:

        - With the default ``include_shell=False``, even a no-filter
          call returns ``("is_shell = FALSE", [])`` — the shell guard
          is always present unless explicitly disabled.
        - ``("TRUE", [])`` is returned only when ``include_shell=True``
          AND no other filters are set.

        This contract is locked by two paired tests in
        ``tests/unit/tools/test_shared.py``
        (``test_empty_filters_yield_shell_only_clause`` +
        ``test_include_shell_true_drops_shell_guard``).
    """
    conditions: list[str] = []
    params: list[Any] = []

    if filters.customer_code is not None:
        conditions.append("customer_code = ?")
        params.append(filters.customer_code)

    if filters.country_of_origin_code is not None:
        # NB: caller must target a view that exposes this column —
        # entries_v has no country_of_origin_code (it has
        # origin_country_codes as a LIST instead). Filter only valid
        # against entry_lines_v.
        conditions.append("country_of_origin_code = ?")
        params.append(filters.country_of_origin_code)

    if filters.port_of_entry_code is not None:
        conditions.append("port_of_entry_code = ?")
        params.append(filters.port_of_entry_code)

    if filters.release_date_from is not None:
        conditions.append("release_date >= ?")
        params.append(filters.release_date_from)

    if filters.release_date_to is not None:
        conditions.append("release_date <= ?")
        params.append(filters.release_date_to)

    if filters.release_year_month is not None:
        conditions.append("release_year_month = ?")
        params.append(filters.release_year_month)

    if filters.release_year_quarter is not None:
        conditions.append("release_year_quarter = ?")
        params.append(filters.release_year_quarter)

    if filters.on_hold is not None:
        conditions.append("on_hold = ?")
        params.append(filters.on_hold)

    # is_shell is a hard literal, not a parameter (it's never user-controlled).
    if not filters.include_shell:
        conditions.append("is_shell = FALSE")

    where_sql = " AND ".join(conditions) if conditions else "TRUE"
    return where_sql, params


# ─────────────────────────────────────────────────────────────────────────────
# SELECT-only execution guardrail (Fork 50)
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_LEADING_KEYWORDS: frozenset[str] = frozenset({"SELECT", "WITH"})


def safe_execute(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> duckdb.DuckDBPyConnection:
    """Run a read-only SQL statement after a SELECT/WITH leading-keyword check.

    DuckDB's Python binding doesn't natively execute multi-statement
    scripts via :py:meth:`execute`, so the practical attack surface is
    a single statement — but the guard remains as defense-in-depth and
    catches accidental DDL/DML in tool code during review.

    Parameters
    ----------
    con
        Open DuckDB connection.
    sql
        SQL string. Must start (after optional leading whitespace) with
        either ``SELECT`` or ``WITH`` (CTE-led queries are read-only).
    params
        Bound parameters for the ``?`` placeholders in ``sql``.

    Returns
    -------
    duckdb.DuckDBPyConnection
        The same connection, ready for ``.fetchone()`` / ``.fetchall()``
        / ``.fetchdf()`` chaining. DuckDB returns ``self`` from
        :py:meth:`execute`.

    Raises
    ------
    ValueError
        If the first non-whitespace token isn't ``SELECT`` or ``WITH``.
    """
    stripped = sql.lstrip()
    first_word = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_word not in _ALLOWED_LEADING_KEYWORDS:
        log.warning(
            Events.SQL_SAFETY_UNSAFE_SQL_BLOCKED,
            sql_prefix=stripped[:80],
            first_word=first_word,
        )
        raise ValueError(
            f"safe_execute refuses non-read-only statement "
            f"(starts with {first_word!r}; allowed: SELECT, WITH)"
        )
    return con.execute(sql, params or [])


# ─────────────────────────────────────────────────────────────────────────────
# Shell-count helper (for ToolMeta.shell_entries_excluded)
# ─────────────────────────────────────────────────────────────────────────────


def _count_shells_excluded(
    con: duckdb.DuckDBPyConnection,
    filters: EntryFilters,
) -> int:
    """Count entries the ``include_shell=False`` filter eliminated.

    The current dataset has 0 shell entries (per the boot-time INFO log
    in :mod:`customs_agent.data.validation`), so this returns 0 today.
    Kept correct for forward safety: when shell entries do appear, the
    sidecar's ``shell_entries_excluded`` field surfaces them so the
    operator knows the filter is doing its job.

    Country-of-origin filter is intentionally skipped (it's line-grain
    and ``entries_v`` lacks the column); the entry-grain filters that
    DO apply are honored.
    """
    if filters.include_shell:
        return 0
    # Build a WHERE that keeps shells in but drops the line-grain filter.
    flipped = filters.model_copy(
        update={"include_shell": True, "country_of_origin_code": None}
    )
    where, params = build_where_clause(flipped)
    sql = f"SELECT COUNT(*) FROM entries_v WHERE {where} AND is_shell"
    row = con.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: wall-clock timing for ToolMeta.latency_ms
# ─────────────────────────────────────────────────────────────────────────────


def now_ms() -> int:
    """Monotonic-clock millisecond stamp for latency measurement."""
    return int(time.perf_counter() * 1000)
