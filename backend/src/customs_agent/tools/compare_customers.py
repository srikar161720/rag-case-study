"""Compare Customers tool (Fork 22 — serves Q7).

Ranks the three customers (MHF / PCA / SAG) by a chosen metric in a
single grouped query — so cross-customer comparison never depends on the
LLM doing arithmetic across separate tool calls.

Always queries ``entries_v`` (entry grain), which already encodes the
per-entry MPF cap (KB §Quirk 3); ``total_duty`` is therefore the correct
capped figure. A CTE computes the per-customer base aggregates, then an
outer SELECT derives the percentage metrics in SQL with the same
``100.0 * num / denom`` expression and zero-denominator guard as the
ground-truth answer key (:func:`tests.ground_truth.q7`) — so the numbers
match to the cent. Python only rounds the percentages to 4 decimals and
ranks the rows (the metric is dynamic, so ranking stays in Python).

Supported metrics (ranked descending):

- ``ieepa_pct``               — IEEPA duty as a % of total duty
- ``section_301_pct``         — Section 301 duty as a % of total duty
- ``effective_duty_rate_pct`` — total duty as a % of total entered value
- ``total_duty``              — total duty (capped MPF)
- ``total_entered_value``     — total entered value
- ``entry_count``             — number of entries

``country_of_origin_code`` is line-grain and not valid on ``entries_v``;
the input model rejects it with a clear message.

Tool output ``data`` shape (for ``ieepa_pct``)::

    {
        "metric": "ieepa_pct",
        "ranked": [
            {"customer_code": str, "ieepa": Decimal,
             "total_duty": Decimal, "ieepa_pct": float, "rank": int},
            ...
        ],
        "highest_customer_code": str | None,
    }
"""

from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, model_validator

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

TOOL_NAME = "compare_customers"
VIEW = "entries_v"

CompareMetric = Literal[
    "ieepa_pct",
    "section_301_pct",
    "effective_duty_rate_pct",
    "total_duty",
    "total_entered_value",
    "entry_count",
]

DESCRIPTION = (
    "Rank all three customers (MHF / PCA / SAG) by a chosen metric in one "
    "grouped query — avoids cross-customer LLM arithmetic. Metrics: "
    "ieepa_pct (IEEPA as % of total duty), section_301_pct (Section 301 as "
    "% of total duty), effective_duty_rate_pct (total duty as % of entered "
    "value), total_duty, total_entered_value, entry_count. Uses entries_v "
    "(entry grain, capped MPF). Returns a descending-ranked list plus the "
    "highest customer. Use for 'compare/which customer has the highest ...' "
    "questions."
)


class CompareCustomersInput(BaseModel):
    """Input schema for ``compare_customers``."""

    metric: CompareMetric = Field(
        description="Which metric to rank customers by (descending).",
    )
    filters: EntryFilters = Field(
        default_factory=EntryFilters,
        description="Filter set — period, port, hold, shell inclusion. "
        "Do not set customer_code (the tool compares all customers) or "
        "country_of_origin_code (line-grain; not valid at entry grain).",
    )
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _reject_incompatible_filters(self) -> "CompareCustomersInput":
        if self.filters.country_of_origin_code is not None:
            raise ValueError(
                "compare_customers operates on entries_v (entry grain); "
                "country_of_origin_code is line-grain and cannot be applied. "
                "Drop the country filter, or use a line-grain tool."
            )
        if self.filters.customer_code is not None:
            raise ValueError(
                "compare_customers ranks ALL customers; do not set "
                "customer_code in filters — it would restrict the comparison "
                "to a single customer and make the ranking meaningless."
            )
        return self


# metric → (value key in the ranked entry, extra context keys to include).
# All ranked entries always carry customer_code + the metric value + rank.
_PCT_METRICS = {
    "ieepa_pct": ("ieepa", "total_duty"),
    "section_301_pct": ("section_301", "total_duty"),
    "effective_duty_rate_pct": ("total_duty", "total_entered_value"),
}


def compare_customers(
    con: duckdb.DuckDBPyConnection,
    metric: CompareMetric,
    filters: EntryFilters,
) -> ToolResult:
    """Rank customers by ``metric`` (descending) over the filtered set."""
    where, params = build_where_clause(filters)
    # Compute the per-customer base aggregates in a CTE, then derive the
    # three percentage metrics in the outer SELECT — all in SQL — so the
    # values match the ground-truth answer key exactly (same 100.0-DOUBLE
    # expression and zero-denominator guard as tests.ground_truth.q7).
    sql = f"""
        WITH per_customer AS (
            SELECT
                customer_code,
                SUM(total_primary_duty)                  AS primary_duty,
                COALESCE(SUM(total_section_301_duty), 0) AS section_301,
                COALESCE(SUM(total_ieepa_duty), 0)       AS ieepa,
                SUM(total_mpf_capped)                    AS mpf_capped,
                SUM(total_hmf)                           AS hmf,
                SUM(total_entered_value)                 AS total_entered_value,
                COUNT(*)                                 AS entry_count,
                (
                    SUM(total_primary_duty)
                    + COALESCE(SUM(total_section_301_duty), 0)
                    + COALESCE(SUM(total_ieepa_duty), 0)
                    + SUM(total_mpf_capped)
                    + SUM(total_hmf)
                )                                        AS total_duty
            FROM {VIEW}
            WHERE {where}
            GROUP BY customer_code
        )
        SELECT
            customer_code,
            primary_duty, section_301, ieepa, mpf_capped, hmf,
            total_entered_value, entry_count, total_duty,
            CASE WHEN total_duty > 0
                 THEN 100.0 * ieepa / total_duty ELSE 0 END AS ieepa_pct,
            CASE WHEN total_duty > 0
                 THEN 100.0 * section_301 / total_duty ELSE 0 END AS section_301_pct,
            CASE WHEN total_entered_value > 0
                 THEN 100.0 * total_duty / total_entered_value ELSE 0 END
                 AS effective_duty_rate_pct
        FROM per_customer
    """
    t0 = now_ms()
    cursor = safe_execute(con, sql, params)
    columns = [d[0] for d in cursor.description]
    rows = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
    latency = now_ms() - t0

    def _value(agg: dict[str, Any]) -> Any:
        """Read the metric's SQL-computed value; round percentages to 4
        decimals (q7 rounds the SQL-computed pct the same way)."""
        v = agg[metric]
        return round(float(v), 4) if metric.endswith("_pct") else v

    scored = sorted(rows, key=lambda a: float(_value(a)), reverse=True)

    ranked: list[dict[str, Any]] = []
    for i, agg in enumerate(scored):
        entry: dict[str, Any] = {"customer_code": agg["customer_code"]}
        if metric in _PCT_METRICS:
            num_key, denom_key = _PCT_METRICS[metric]
            entry[num_key] = agg[num_key]
            entry[denom_key] = agg[denom_key]
        entry[metric] = _value(agg)
        entry["rank"] = i + 1
        ranked.append(entry)

    return ToolResult(
        data={
            "metric": metric,
            "ranked": ranked,
            "highest_customer_code": ranked[0]["customer_code"] if ranked else None,
        },
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=sql.strip(),
            view_used=VIEW,
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=len(rows),
            latency_ms=latency,
        ),
        citations=[
            Citation(
                doc="data_dictionary.txt",
                section="§Quirk 2 — IEEPA Feb 2025+",
                chunk_id="quirk_2_ieepa_feb_2025",
            ),
            Citation(
                doc="customer_profiles_qbr_metrics.txt",
                section="§Metric: Effective Duty Rate",
                chunk_id="metric_effective_duty_rate",
            ),
        ],
    )
