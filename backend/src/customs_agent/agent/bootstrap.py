"""Boot-time wiring for the agent loop (Fork 21 + Fork 23).

Three responsibilities:

1. :func:`describe_view` — read the actual column list of a DuckDB view
   via ``information_schema.columns``. ``safe_execute`` requires SELECT
   or WITH leading keyword; ``DESCRIBE <view>`` doesn't qualify (DuckDB
   parses ``DESCRIBE`` as a top-level statement), so we use the
   standard-SQL view of view columns instead.
2. :func:`build_tool_definitions` — turn :data:`customs_agent.tools.TOOL_REGISTRY`
   into the list of Anthropic-shaped tool dicts that the loop passes to
   ``messages.create(tools=...)``. Substitutes the
   ``{available_columns_entries_v}`` / ``{available_columns_entry_lines_v}``
   placeholders in the ``query_entries`` description with the live column
   list, fulfilling the Fork 21 auto-generation deferral.
3. :class:`AgentContext` — frozen dataclass bundling the four runtime
   deps (DuckDB conn, retriever, Anthropic client, pre-built tool
   definitions) plus the always-on chunk-ID set used for retriever
   dedup (Fork 15). Built once at app startup; passed into ``run_agent``
   on every request.

This module is called from ``feat/fastapi-backend``'s ``main.py`` at
app startup. The agent loop itself only needs the resulting
:class:`AgentContext`.
"""

from dataclasses import dataclass
from typing import Any

import duckdb
import structlog
from anthropic import Anthropic

from customs_agent.rag.always_on import ALWAYS_ON_KINDS
from customs_agent.rag.chunker import CHUNKS_REGISTRY
from customs_agent.rag.retriever import HybridRetriever
from customs_agent.tools import (
    TOOL_REGISTRY,
    build_anthropic_tool_def,
    format_query_entries_description,
)
from customs_agent.tools._shared import safe_execute

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class AgentContext:
    """All runtime dependencies the agent loop needs, bundled once at boot."""

    con: duckdb.DuckDBPyConnection
    retriever: HybridRetriever
    client: Anthropic
    tool_definitions: list[dict[str, Any]]
    always_on_chunk_ids: frozenset[str]


def describe_view(
    con: duckdb.DuckDBPyConnection,
    view_name: str,
) -> tuple[str, ...]:
    """Return the column names of a DuckDB view, sorted alphabetically.

    Uses ``information_schema.columns`` (standard SQL) so the call goes
    through :func:`customs_agent.tools._shared.safe_execute` cleanly —
    ``DESCRIBE`` would be rejected by the SELECT-only guard.

    Raises
    ------
    ValueError
        If the view returns zero columns (probably means the view name
        is wrong; we'd rather fail boot than ship an empty allowlist).
    """
    sql = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY column_name"
    )
    rows = safe_execute(con, sql, [view_name]).fetchall()
    if not rows:
        raise ValueError(
            f"describe_view: no columns found for {view_name!r}. "
            f"Is the view materialized on this connection?"
        )
    return tuple(r[0] for r in rows)


def build_tool_definitions(
    con: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    """Build the Anthropic ``tools`` parameter for the agent loop.

    Iterates :data:`customs_agent.tools.TOOL_REGISTRY`, calls
    :func:`build_anthropic_tool_def` for each, and substitutes the
    ``query_entries`` description's column-list placeholders with
    real column names from
    :func:`describe_view`.

    Returns
    -------
    list[dict[str, Any]]
        Ready to splice directly into
        ``client.messages.create(tools=...)``.
    """
    cols_entries_v = describe_view(con, "entries_v")
    cols_entry_lines_v = describe_view(con, "entry_lines_v")
    query_entries_desc = format_query_entries_description(
        cols_entries_v, cols_entry_lines_v
    )

    overrides = {"query_entries": query_entries_desc}
    defs = [build_anthropic_tool_def(spec, overrides) for spec in TOOL_REGISTRY]

    log.info(
        "agent.bootstrap.tools_built",
        tool_count=len(defs),
        entries_v_col_count=len(cols_entries_v),
        entry_lines_v_col_count=len(cols_entry_lines_v),
    )
    return defs


def compute_always_on_chunk_ids() -> frozenset[str]:
    """Set of ``chunk_id``s that are baked into the cached system prompt.

    The agent loop uses this to dedup retrieved chunks against the
    always-on block (Fork 15) — if the retriever surfaces a chunk
    that's already in the system prompt, don't inject it again under
    ``<retrieved_knowledge>`` (waste of cache tokens).
    """
    return frozenset(
        spec.chunk_id
        for spec in CHUNKS_REGISTRY
        if spec.section_kind in ALWAYS_ON_KINDS
    )


def build_agent_context(
    con: duckdb.DuckDBPyConnection,
    retriever: HybridRetriever,
    client: Anthropic,
) -> AgentContext:
    """Factory: wire up an :class:`AgentContext` from the three runtime deps.

    Called once at app startup. The returned context is immutable
    (``frozen=True``) and passed into ``run_agent`` on every request.
    """
    return AgentContext(
        con=con,
        retriever=retriever,
        client=client,
        tool_definitions=build_tool_definitions(con),
        always_on_chunk_ids=compute_always_on_chunk_ids(),
    )
