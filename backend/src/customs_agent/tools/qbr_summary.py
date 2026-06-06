"""QBR Summary tool (Fork 22 — serves Q9).

Composes a mini Quarterly Business Review for one customer over one
quarter, in the four standard sections from
``customer_profiles_qbr_metrics.txt §QBR``:

1. **entry_volume_by_month** — entry counts per month in the quarter
2. **duty_breakdown** — total duty by program (primary / 301 / IEEPA /
   capped MPF / HMF) plus the combined total
3. **top_countries** — top 5 sourcing countries by line count
4. **hold_summary** — entries total / on hold / hold rate %

Rather than re-implement SQL, this tool **composes the already-tested
tool functions** (:func:`query_entries`, :func:`total_duty_breakdown`,
:func:`hold_summary`) against a shared ``EntryFilters`` built from the
customer + quarter. Shapes match the ground-truth answer key
(:func:`tests.ground_truth.q9`).

Tool output ``data`` shape::

    {
        "entry_volume_by_month": [{"month": str, "count": int}, ...],
        "duty_breakdown": {
            "primary": Decimal, "section_301": Decimal, "ieepa": Decimal,
            "mpf_capped": Decimal, "hmf": Decimal, "total": Decimal,
        },
        "top_countries": [{"country_of_origin_code": str, "line_count": int}, ...],
        "hold_summary": {
            "entries_total": int, "entries_on_hold": int, "hold_rate_pct": float,
        },
    }
"""


import duckdb
from pydantic import BaseModel, ConfigDict, Field

from customs_agent.tools._filters import CustomerCode, EntryFilters
from customs_agent.tools._shared import (
    Citation,
    ToolMeta,
    ToolResult,
    _count_shells_excluded,
    now_ms,
)
from customs_agent.tools.hold_summary import hold_summary
from customs_agent.tools.query_entries import query_entries
from customs_agent.tools.total_duty_breakdown import total_duty_breakdown

TOOL_NAME = "qbr_summary"

DESCRIPTION = (
    "Compose a mini Quarterly Business Review for one customer over one "
    "quarter, in the 4 standard KB §QBR sections: entry volume by month, "
    "total duty breakdown by program, top 5 sourcing countries by line "
    "count, and hold rate. Pass customer_code and period (e.g. '2025-Q1'). "
    "Use for 'generate a QBR' / 'quarterly summary' questions."
)


class QbrSummaryInput(BaseModel):
    """Input schema for ``qbr_summary``."""

    customer_code: CustomerCode = Field(
        description="Customer to summarize (MHF / PCA / SAG).",
    )
    period: str = Field(
        pattern=r"^\d{4}-Q[1-4]$",
        description="Quarter to cover, e.g. '2025-Q1'.",
    )
    model_config = ConfigDict(extra="forbid")


def qbr_summary(
    con: duckdb.DuckDBPyConnection,
    customer_code: CustomerCode,
    period: str,
) -> ToolResult:
    """Compose the 4-section QBR for ``customer_code`` over ``period``."""
    filters = EntryFilters(customer_code=customer_code, release_year_quarter=period)

    t0 = now_ms()

    # 1. Entry volume by month (entry grain).
    volume_res = query_entries(
        con,
        view="entries_v",
        filters=filters,
        group_by=["release_year_month"],
        aggregations=["count_distinct_entries"],
        order_by=[("release_year_month", "asc")],
        limit=200,
    )
    entry_volume_by_month = [
        {"month": row["release_year_month"], "count": int(row["entry_count"])}
        for row in volume_res.data
    ]

    # 2. Duty breakdown by program (entry grain → capped MPF). Compute the
    #    total from the five components so it matches the answer key exactly.
    duty_res = total_duty_breakdown(con, filters)
    duty = duty_res.data
    duty_breakdown = {
        "primary": duty["primary"],
        "section_301": duty["section_301"],
        "ieepa": duty["ieepa"],
        "mpf_capped": duty["mpf_capped"],
        "hmf": duty["hmf"],
        "total": (
            duty["primary"]
            + duty["section_301"]
            + duty["ieepa"]
            + duty["mpf_capped"]
            + duty["hmf"]
        ),
    }

    # 3. Top 5 sourcing countries by line count (line grain).
    country_res = query_entries(
        con,
        view="entry_lines_v",
        filters=filters,
        group_by=["country_of_origin_code"],
        aggregations=["count_lines"],
        order_by=[("count_lines", "desc")],
        limit=5,
    )
    top_countries = [
        {
            "country_of_origin_code": row["country_of_origin_code"],
            "line_count": int(row["line_count"]),
        }
        for row in country_res.data
    ]

    # 4. Hold summary (entry grain).
    hold_res = hold_summary(con, filters)
    hold = hold_res.data
    hold_section = {
        "entries_total": hold["entries_total"],
        "entries_on_hold": hold["entries_on_hold"],
        "hold_rate_pct": hold["hold_rate_pct"],
    }

    latency = now_ms() - t0

    composed_sql = "\n\n".join(
        [
            volume_res.meta.sql_executed or "",
            duty_res.meta.sql_executed or "",
            country_res.meta.sql_executed or "",
            hold_res.meta.sql_executed or "",
        ]
    )

    return ToolResult(
        data={
            "entry_volume_by_month": entry_volume_by_month,
            "duty_breakdown": duty_breakdown,
            "top_countries": top_countries,
            "hold_summary": hold_section,
        },
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=composed_sql,
            view_used=None,  # composed across entries_v + entry_lines_v
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=hold_section["entries_total"],
            latency_ms=latency,
        ),
        citations=[
            Citation(
                doc="customer_profiles_qbr_metrics.txt",
                section="§QBR — Structure (5 Standard Sections)",
                chunk_id="qbr_structure",
            ),
            Citation(
                doc="customer_profiles_qbr_metrics.txt",
                section="§Metric: Hold Rate",
                chunk_id="metric_hold_rate_benchmark",
            ),
            Citation(
                doc="customer_profiles_qbr_metrics.txt",
                section="§Metric: Effective Duty Rate",
                chunk_id="metric_effective_duty_rate",
            ),
        ],
    )
