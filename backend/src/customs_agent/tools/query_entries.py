"""General-purpose entry query builder (Fork 22 — serves Q1/Q2/Q3/Q11
plus unseen questions).

The fallback when no specialized tool fits. Accepts:

- ``view``         — ``"entries_v"`` (default) or ``"entry_lines_v"``.
- ``filters``      — ``EntryFilters`` (same shape every other tool uses).
- ``group_by``     — list of dimensions to group by; each must be in
                     :data:`ALLOWED_GROUP_BY`.
- ``aggregations`` — list of measure expressions; each must be in
                     :data:`ALLOWED_AGGREGATIONS`. Defaults to
                     ``["count_distinct_entries"]``.
- ``order_by``     — list of ``(col_or_agg, "asc"|"desc")`` pairs; each
                     col must be in :data:`ALLOWED_ORDER_BY`.
- ``limit``        — capped at 200 (default 50).

SQL safety (Fork 50): every dimension / aggregation / order-by entry is
matched against a closed allowlist BEFORE any string interpolation
reaches DuckDB. Filter values still flow as ``?`` placeholders via
:func:`build_where_clause`. The combination makes SQL injection a
schema-level failure rather than a runtime concern.

Aggregation aliasing:

- ``count_distinct_entries`` → ``COUNT(DISTINCT entry_number) AS entry_count``
- ``count_lines``            → ``COUNT(*) AS line_count``
- ``sum(<col>)``             → ``SUM(<col>) AS <col>``         (alias = col)
- ``avg(<col>)``             → ``AVG(<col>) AS avg_<col>``
- ``min(<col>)``             → ``MIN(<col>) AS min_<col>``
- ``max(<col>)``             → ``MAX(<col>) AS max_<col>``

The ``sum`` alias collapses to the bare column name so the result key
in ``data[0]`` reads naturally (e.g., ``{"total_entered_value": …}``)
and matches the ground-truth shape for Q2.

Boot-time column auto-generation (Fork 21):

The tool description below carries the placeholders
``{available_columns_entries_v}`` and ``{available_columns_entry_lines_v}``.
``feat/agent-loop`` will substitute them at app bootstrap by calling
``con.execute("DESCRIBE entries_v")`` and joining the column names —
this branch ships only the placeholder. See ``tools/__init__.py``
``format_query_entries_description()`` for the substitution helper.
"""

import re
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from customs_agent.tools._allowlists import (
    ALLOWED_AGGREGATIONS,
    ALLOWED_GROUP_BY,
    ALLOWED_ORDER_BY,
)
from customs_agent.tools._filters import EntryFilters
from customs_agent.tools._shared import (
    ToolMeta,
    ToolResult,
    _count_shells_excluded,
    build_where_clause,
    now_ms,
    safe_execute,
)

TOOL_NAME = "query_entries"

# Description carries placeholder tokens that ``feat/agent-loop`` fills
# from DESCRIBE entries_v / DESCRIBE entry_lines_v at app bootstrap.
DESCRIPTION = (
    "General-purpose customs-entry query builder. Use this when no "
    "specialized tool fits (e.g., simple counts, sums, top-N by a "
    "custom group).\n\n"
    "Args:\n"
    "  view: 'entries_v' (entry-grain, capped MPF) or 'entry_lines_v' "
    "(line-grain — required for country_of_origin_code, hts_code, mid).\n"
    "  filters: standard EntryFilters.\n"
    "  group_by: list of dimension columns. Allowed: "
    "{available_columns_entries_v} (entries_v) / "
    "{available_columns_entry_lines_v} (entry_lines_v).\n"
    "  aggregations: list of measure expressions — count_distinct_entries, "
    "count_lines, sum(<col>), avg(<col>), min(<col>), max(<col>). "
    "Defaults to [count_distinct_entries].\n"
    "  order_by: list of (column-or-aggregation-name, 'asc' | 'desc') pairs.\n"
    "  limit: cap on rows returned (1-200; default 50).\n\n"
    "Returns a list of row dicts. Group-by columns appear with their "
    "column name; aggregations appear with the alias shown above "
    "(sum(X) → X; count_distinct_entries → entry_count; count_lines → line_count)."
)


# ─────────────────────────────────────────────────────────────────────────────
# Input model with allowlist validators
# ─────────────────────────────────────────────────────────────────────────────


class QueryEntriesInput(BaseModel):
    """Input schema for ``query_entries`` — agent-visible shape."""

    view: Literal["entries_v", "entry_lines_v"] = "entries_v"
    filters: EntryFilters = Field(default_factory=EntryFilters)
    group_by: list[str] = Field(default_factory=list)
    aggregations: list[str] = Field(
        default_factory=lambda: ["count_distinct_entries"]
    )
    order_by: list[tuple[str, Literal["asc", "desc"]]] = Field(
        default_factory=list
    )
    limit: int = Field(default=50, ge=1, le=200)

    model_config = ConfigDict(extra="forbid")

    @field_validator("group_by")
    @classmethod
    def _check_group_by(cls, v: list[str]) -> list[str]:
        bad = set(v) - ALLOWED_GROUP_BY
        if bad:
            raise ValueError(
                f"Invalid group_by columns: {sorted(bad)}. "
                f"Allowed: {sorted(ALLOWED_GROUP_BY)}"
            )
        return v

    @field_validator("aggregations")
    @classmethod
    def _check_aggregations(cls, v: list[str]) -> list[str]:
        bad = set(v) - ALLOWED_AGGREGATIONS
        if bad:
            raise ValueError(
                f"Invalid aggregations: {sorted(bad)}. "
                f"Must be in ALLOWED_AGGREGATIONS."
            )
        if not v:
            raise ValueError("aggregations must contain at least one entry")
        return v

    @field_validator("order_by")
    @classmethod
    def _check_order_by(
        cls,
        v: list[tuple[str, Literal["asc", "desc"]]],
    ) -> list[tuple[str, Literal["asc", "desc"]]]:
        bad = {col for col, _ in v if col not in ALLOWED_ORDER_BY}
        if bad:
            raise ValueError(
                f"Invalid order_by columns: {sorted(bad)}. "
                f"Must be in ALLOWED_ORDER_BY (group_by columns or aggregation names)."
            )
        return v


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation parsing
# ─────────────────────────────────────────────────────────────────────────────

# Pattern intentionally restrictive: lowercase identifiers only, since
# both ALLOWED_AGGREGATIONS entries and view column names are lowercase.
_AGG_RE = re.compile(r"^(sum|avg|min|max)\(([a-z_][a-z0-9_]*)\)$")


def _parse_aggregation(agg: str) -> tuple[str, str]:
    """Return ``(sql_fragment, alias)`` for one validated aggregation entry.

    Raises ValueError if the form is unparseable — but the upstream
    validator already restricts to ``ALLOWED_AGGREGATIONS`` membership,
    so this is defense-in-depth.
    """
    if agg == "count_distinct_entries":
        return "COUNT(DISTINCT entry_number)", "entry_count"
    if agg == "count_lines":
        return "COUNT(*)", "line_count"
    match = _AGG_RE.match(agg)
    if not match:
        raise ValueError(f"Unparseable aggregation: {agg!r}")
    func, col = match.groups()
    func_upper = func.upper()
    alias = col if func == "sum" else f"{func}_{col}"
    return f"{func_upper}({col})", alias


def _resolve_order_by(col_or_agg: str) -> str:
    """Map an aggregation NAME to its SELECT alias; pass column names through.

    ``order_by=[("count_distinct_entries", "desc")]`` becomes
    ``ORDER BY entry_count DESC`` in the emitted SQL.
    """
    if col_or_agg in ALLOWED_AGGREGATIONS:
        return _parse_aggregation(col_or_agg)[1]
    return col_or_agg


# ─────────────────────────────────────────────────────────────────────────────
# Tool function
# ─────────────────────────────────────────────────────────────────────────────


def query_entries(
    con: duckdb.DuckDBPyConnection,
    view: Literal["entries_v", "entry_lines_v"] = "entries_v",
    filters: EntryFilters | None = None,
    group_by: list[str] | None = None,
    aggregations: list[str] | None = None,
    order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    limit: int = 50,
) -> ToolResult:
    """Build and execute a SELECT / GROUP BY / ORDER BY / LIMIT query.

    All structural args are validated upstream by :class:`QueryEntriesInput`;
    callers from the agent loop should construct that model first, then
    pass its fields through. Direct callers (e.g., unit tests) pass
    pre-validated values.
    """
    filters = filters if filters is not None else EntryFilters()
    group_by = group_by if group_by is not None else []
    aggregations = (
        aggregations if aggregations is not None else ["count_distinct_entries"]
    )
    order_by = order_by if order_by is not None else []

    where, params = build_where_clause(filters)

    # Build SELECT list: group_by columns first, then aggregations with aliases.
    select_parts: list[str] = list(group_by)
    for agg in aggregations:
        sql_frag, alias = _parse_aggregation(agg)
        select_parts.append(f"{sql_frag} AS {alias}")
    select_clause = ", ".join(select_parts)

    sql = f"SELECT {select_clause} FROM {view} WHERE {where}"
    if group_by:
        sql += " GROUP BY " + ", ".join(group_by)
    if order_by:
        order_parts = [
            f"{_resolve_order_by(col)} {direction.upper()}"
            for col, direction in order_by
        ]
        sql += " ORDER BY " + ", ".join(order_parts)
    sql += f" LIMIT {limit}"

    t0 = now_ms()
    cursor = safe_execute(con, sql, params)
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    latency = now_ms() - t0

    data: list[dict[str, Any]] = [dict(zip(columns, row, strict=False)) for row in rows]

    return ToolResult(
        data=data,
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=sql,
            view_used=view,
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=len(rows),
            latency_ms=latency,
        ),
        citations=[
            # query_entries is a general builder — it doesn't encode a
            # specific business rule beyond the universal ones
            # (shell-exclusion default, date-field default). Always-on
            # context carries those, so no per-call citations here.
        ],
    )
