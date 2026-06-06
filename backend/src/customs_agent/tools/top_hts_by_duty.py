"""Top HTS by Duty tool (Fork 22 — serves Q8).

Ranks HTS codes by total duty contribution (all duty programs combined)
for a filtered subset of customs entry lines, returning the top ``limit``
by descending total duty.

Always queries ``entry_lines_v`` — HTS code + description live at line
grain, and an origin filter (``country_of_origin_code``) is line-grain
too. ``total_duty`` is the explicit five-program sum
(primary + Section 301 + IEEPA + MPF + HMF) at line grain, matching the
ground-truth answer-key formula in :func:`tests.ground_truth.q8`. The
per-entry MPF cap (KB §Quirk 3) is *not* applied here because the result
is restricted to a subset of lines, where the per-entry cap is no longer
meaningful — line-grain raw MPF is the correct component.

Rows are grouped by ``hts_code`` alone (with ``ANY_VALUE(hts_description)``)
so a code that carries slightly varied description text across lines still
collapses to a single ranked row.

Tool output ``data`` shape::

    {
        "top_hts": [
            {
                "hts_code":        str,       # dotted XXXX.XX.XXXX form, as stored
                "hts_description": str,
                "total_duty":      Decimal,   # primary + 301 + ieepa + mpf + hmf
                "primary_duty":    Decimal,
                "section_301":     Decimal,
                "ieepa":           Decimal,
                "line_count":      int,
                "entered_value":   Decimal,
            },
            ...
        ],
        "limit": int,
    }
"""

from typing import Any

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

TOOL_NAME = "top_hts_by_duty"
VIEW = "entry_lines_v"

DESCRIPTION = (
    "Rank HTS codes by total duty contribution (all programs combined: "
    "primary + Section 301 + IEEPA + MPF + HMF) for a filtered subset of "
    "entry lines, returning the top `limit` by descending total duty. Each "
    "row carries the HTS code (dotted XXXX.XX.XXXX form), its description, "
    "the combined total duty, the per-program component sums, the line "
    "count, and the entered value. Uses entry_lines_v (HTS and origin are "
    "line-grain). Use for 'top N HTS codes by duty' questions."
)


class TopHtsByDutyInput(BaseModel):
    """Input schema for ``top_hts_by_duty``."""

    filters: EntryFilters = Field(
        default_factory=EntryFilters,
        description="Filter set — customer, country, port, period, hold, shell inclusion.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="How many top HTS codes to return (by descending total duty).",
    )
    model_config = ConfigDict(extra="forbid")


def top_hts_by_duty(
    con: duckdb.DuckDBPyConnection,
    filters: EntryFilters,
    limit: int = 5,
) -> ToolResult:
    """Return the top ``limit`` HTS codes by combined total duty."""
    where, params = build_where_clause(filters)
    sql = f"""
        SELECT
            hts_code,
            ANY_VALUE(hts_description)                AS hts_description,
            SUM(primary_duty)
                + COALESCE(SUM(section_301_duty), 0)
                + COALESCE(SUM(ieepa_duty), 0)
                + SUM(mpf)
                + SUM(hmf)                            AS total_duty,
            SUM(primary_duty)                         AS primary_duty,
            COALESCE(SUM(section_301_duty), 0)        AS section_301,
            COALESCE(SUM(ieepa_duty), 0)              AS ieepa,
            COUNT(*)                                  AS line_count,
            SUM(entered_value)                        AS entered_value
        FROM {VIEW}
        WHERE {where}
        GROUP BY hts_code
        ORDER BY total_duty DESC
        LIMIT {limit}
    """
    t0 = now_ms()
    rows = safe_execute(con, sql, params).fetchall()
    latency = now_ms() - t0

    top_hts: list[dict[str, Any]] = [
        {
            "hts_code": r[0],
            "hts_description": r[1],
            "total_duty": r[2],
            "primary_duty": r[3],
            "section_301": r[4],
            "ieepa": r[5],
            "line_count": int(r[6]),
            "entered_value": r[7],
        }
        for r in rows
    ]

    return ToolResult(
        data={"top_hts": top_hts, "limit": limit},
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
                doc="duties_fees_tariffs.txt",
                section="§1 — HTS Code (Harmonized Tariff Schedule)",
                chunk_id="hts_format_xxxx_xx_xxxx",
            ),
            Citation(
                doc="data_dictionary.txt",
                section="§Quirk 1 — Section 301 China-Only",
                chunk_id="quirk_1_section_301_china_only",
            ),
        ],
    )
