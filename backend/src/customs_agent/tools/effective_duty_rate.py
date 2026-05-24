"""Effective Duty Rate tool (Fork 22 — serves Q5).

Effective Duty Rate = ``(SUM(total_duty_taxes_fees) / SUM(entered_value)) * 100``.

Always queries ``entry_lines_v`` so a ``country_of_origin_code`` filter
(line-grain) can apply. The line-grain ``total_duty_taxes_fees`` column
already includes MPF, HMF, and any 301 / IEEPA contributions on each
line — the formula is the spec definition from
``customer_profiles_qbr_metrics.txt §EFFECTIVE DUTY RATE``.

Tool input shape (passed by the Anthropic tool-use boundary):

.. code-block:: json

    {"filters": { ...EntryFilters fields... }}

Tool output ``data`` shape::

    {
        "rate_pct":           float,       # rounded to 4 decimal places
        "total_duty":         Decimal,
        "total_entered_value": Decimal,
        "line_count":         int,
        "breakdown": {
            "primary_duty":  Decimal,
            "section_301":   Decimal,
            "ieepa":         Decimal,
            "mpf":           Decimal,
            "hmf":           Decimal,
        }
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

TOOL_NAME = "effective_duty_rate"
VIEW = "entry_lines_v"

DESCRIPTION = (
    "Calculate the Effective Duty Rate — total duties and fees as a percentage "
    "of total entered value — for a filtered subset of customs entry lines. "
    "Formula: (SUM(total_duty_taxes_fees) / SUM(entered_value)) * 100. "
    "Uses entry_lines_v so country_of_origin_code filters work (origin is "
    "line-grain). Returns the rate, the duty + value sums, the line count, "
    "and a per-program breakdown (primary / Section 301 / IEEPA / MPF / HMF)."
)


class EffectiveDutyRateInput(BaseModel):
    """Input schema for ``effective_duty_rate``."""

    filters: EntryFilters = Field(
        default_factory=EntryFilters,
        description="Filter set — customer, country, port, period, hold, shell inclusion.",
    )
    model_config = ConfigDict(extra="forbid")


def effective_duty_rate(
    con: duckdb.DuckDBPyConnection,
    filters: EntryFilters,
) -> ToolResult:
    """Compute the effective duty rate for the filtered set of lines."""
    where, params = build_where_clause(filters)
    sql = f"""
        SELECT
            SUM(total_duty_taxes_fees)                 AS total_duty,
            SUM(entered_value)                         AS total_entered_value,
            CASE WHEN SUM(entered_value) > 0
                 THEN CAST(SUM(total_duty_taxes_fees) AS DOUBLE)
                      / SUM(entered_value) * 100.0
                 ELSE 0
            END                                        AS rate_pct,
            COUNT(*)                                   AS line_count,
            SUM(primary_duty)                          AS primary_duty,
            COALESCE(SUM(section_301_duty), 0)         AS section_301,
            COALESCE(SUM(ieepa_duty), 0)               AS ieepa,
            SUM(mpf)                                   AS mpf,
            SUM(hmf)                                   AS hmf
        FROM {VIEW}
        WHERE {where}
    """
    t0 = now_ms()
    row = safe_execute(con, sql, params).fetchone()
    latency = now_ms() - t0

    # Defensive: if zero matching lines, row is still returned but with NULL aggregates.
    line_count = int(row[3]) if row and row[3] is not None else 0
    rate_pct = round(float(row[2]), 4) if row and row[2] is not None else 0.0

    data = {
        "rate_pct": rate_pct,
        "total_duty": row[0] if row else 0,
        "total_entered_value": row[1] if row else 0,
        "line_count": line_count,
        "breakdown": {
            "primary_duty": row[4] if row else 0,
            "section_301": row[5] if row else 0,
            "ieepa": row[6] if row else 0,
            "mpf": row[7] if row else 0,
            "hmf": row[8] if row else 0,
        },
    }

    return ToolResult(
        data=data,
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=sql.strip(),
            view_used=VIEW,
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=line_count,
            latency_ms=latency,
        ),
        citations=[
            Citation(
                doc="duties_fees_tariffs.txt",
                section="§Business Rule 3 — Duty Spend Aggregation",
                chunk_id="rule_3_duty_spend_aggregation",
            ),
            Citation(
                doc="customer_profiles_qbr_metrics.txt",
                section="§Metric: Effective Duty Rate",
                chunk_id="metric_effective_duty_rate",
            ),
        ],
    )
