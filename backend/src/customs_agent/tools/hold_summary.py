"""Hold Summary tool (Fork 22 — serves Q6, primitive for Q9).

Computes entry hold rate against the KB §Hold Rate benchmarks:

- **< 5%** → ``status: "below"`` (within industry benchmark)
- **5-8%** → ``status: "above"`` (elevated; worth surfacing)
- **> 8%** → ``status: "warrants_investigation"`` (compliance issue)

Always queries ``entries_v`` (hold status is entry-grain). Returns the
total entry count, the on-hold count, the rate as a percentage rounded
to 2 decimals, the benchmark constant, the status classification, and a
breakdown of hold reasons.

Implementation mirrors the worked example in ``context/04-agent-and-
tools.md`` lines 237-289 verbatim.

Tool output ``data`` shape::

    {
        "entries_total":   int,
        "entries_on_hold": int,
        "hold_rate_pct":   float,             # rounded to 2 decimals
        "benchmark_pct":   5.0,               # constant from KB
        "status":          str,               # "below" | "above" | "warrants_investigation"
        "hold_reasons":    dict[str, int],    # {reason: count}
    }
"""

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools._shared import (
    Citation,
    ToolMeta,
    ToolResult,
    _count_shells_excluded,
    build_where_clause,
    now_ms,
    safe_execute,
)

TOOL_NAME = "hold_summary"
VIEW = "entries_v"
BENCHMARK_PCT = 5.0
INVESTIGATION_THRESHOLD_PCT = 8.0

DESCRIPTION = (
    "Compute entry hold rate against the KB §Hold Rate benchmarks. "
    "Returns the total entry count, on-hold count, hold rate percentage, "
    "the 5% industry benchmark, a status classification "
    "(below / above / warrants_investigation at >8%), and a breakdown of "
    "hold reasons. Always queries entries_v (hold status is entry-grain)."
)


class HoldSummaryInput(BaseModel):
    """Input schema for ``hold_summary``."""

    filters: EntryFilters = Field(
        default_factory=EntryFilters,
        description="Filter set — customer, port, period, shell inclusion.",
    )
    model_config = ConfigDict(extra="forbid")


def _classify(rate_pct: float) -> str:
    if rate_pct > INVESTIGATION_THRESHOLD_PCT:
        return "warrants_investigation"
    if rate_pct > BENCHMARK_PCT:
        return "above"
    return "below"


def hold_summary(
    con: duckdb.DuckDBPyConnection,
    filters: EntryFilters,
) -> ToolResult:
    """Compute hold rate + status + reason breakdown for the filtered set."""
    where, params = build_where_clause(filters)

    summary_sql = f"""
        SELECT
            COUNT(*)                                              AS total_entries,
            COUNT(*) FILTER (WHERE on_hold)                       AS entries_on_hold,
            COALESCE(
                COUNT(*) FILTER (WHERE on_hold) * 100.0
                / NULLIF(COUNT(*), 0), 0
            )                                                     AS hold_rate_pct
        FROM {VIEW} WHERE {where}
    """

    reasons_sql = f"""
        SELECT hold_reason, COUNT(*)
        FROM {VIEW}
        WHERE {where} AND on_hold AND hold_reason IS NOT NULL
        GROUP BY hold_reason
    """

    t0 = now_ms()
    row = safe_execute(con, summary_sql, params).fetchone()
    reasons = dict(safe_execute(con, reasons_sql, params).fetchall())
    latency = now_ms() - t0

    total = int(row[0]) if row else 0
    on_hold = int(row[1]) if row else 0
    rate = float(row[2]) if row else 0.0

    return ToolResult(
        data={
            "entries_total": total,
            "entries_on_hold": on_hold,
            "hold_rate_pct": round(rate, 2),
            "benchmark_pct": BENCHMARK_PCT,
            "status": _classify(rate),
            "hold_reasons": reasons,
        },
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=summary_sql.strip(),
            view_used=VIEW,
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=total,
            latency_ms=latency,
        ),
        citations=[
            Citation(
                doc="customer_profiles_qbr_metrics.txt",
                section="§Metric: Hold Rate",
                chunk_id="metric_hold_rate_benchmark",
            ),
            Citation(
                doc="duties_fees_tariffs.txt",
                section="§Business Rule 6 — On-Hold Entries",
                chunk_id="rule_6_on_hold_entries",
            ),
        ],
    )
