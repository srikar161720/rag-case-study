"""Total Duty Breakdown tool (Fork 22 — serves Q4, primitive for Q7/Q9).

Splits the total duty into the 5 program components: Primary, Section 301,
IEEPA, MPF (capped per entry), HMF. Returns both ``total_correct``
(entry-grain with the per-entry MPF cap applied) and ``total_line_sum``
(line-grain raw sum) so callers can pick the right grain.

View selection: ``entries_v`` (default) — entry-grain, exposes the
``total_mpf_capped`` column that already applies KB §Quirk 3's
``$31.67`` / ``$614.35`` cap. When a ``country_of_origin_code`` filter
is present, swap to ``entry_lines_v`` (origin is line-grain) and report
the line-grain figures only (the per-entry MPF cap cannot be re-applied
once the result is restricted to a subset of lines).

Tool output ``data`` shape::

    {
        "primary":         Decimal,
        "section_301":     Decimal,
        "ieepa":           Decimal,
        "mpf_capped":      Decimal | None,    # None on line-grain query
        "mpf_raw":         Decimal,
        "hmf":             Decimal,
        "total_correct":   Decimal | None,    # None on line-grain query
        "total_line_sum":  Decimal,
        "line_count":      int,
        "entry_count":     int,
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

TOOL_NAME = "total_duty_breakdown"

DESCRIPTION = (
    "Break the total duty into its program components: Primary, Section 301, "
    "IEEPA, MPF (capped per entry), HMF. Returns the per-program sums plus "
    "two totals — ``total_correct`` (entry-grain with capped MPF) and "
    "``total_line_sum`` (raw line-grain sum). Uses entries_v by default; "
    "switches to entry_lines_v when a country_of_origin_code filter is "
    "present (origin is line-grain). Honors the MPF cap (KB Quirk 3), "
    "Section 301 CN-only applicability (Quirk 1), and IEEPA February 2025 "
    "applicability (Quirk 2)."
)


class TotalDutyBreakdownInput(BaseModel):
    """Input schema for ``total_duty_breakdown``."""

    filters: EntryFilters = Field(
        default_factory=EntryFilters,
        description="Filter set — customer, country, port, period, hold, shell inclusion.",
    )
    model_config = ConfigDict(extra="forbid")


def _query_entry_grain(
    con: duckdb.DuckDBPyConnection,
    where: str,
    params: list[Any],
) -> tuple[dict[str, Any], str, int]:
    """Entry-grain breakdown using entries_v columns with capped MPF."""
    sql = f"""
        SELECT
            SUM(total_primary_duty)                       AS primary_duty,
            COALESCE(SUM(total_section_301_duty), 0)      AS section_301,
            COALESCE(SUM(total_ieepa_duty), 0)            AS ieepa,
            SUM(total_mpf_capped)                         AS mpf_capped,
            SUM(total_mpf_raw)                            AS mpf_raw,
            SUM(total_hmf)                                AS hmf,
            SUM(total_duty_taxes_fees_correct)            AS total_correct,
            SUM(total_duty_taxes_fees_line_sum)           AS total_line_sum,
            SUM(line_count)                               AS line_count,
            COUNT(*)                                      AS entry_count
        FROM entries_v
        WHERE {where}
    """
    # Aggregate-without-GROUP-BY: DuckDB always returns exactly one row
    # (NULL aggregates when zero rows match). ``fetchone()`` cannot return
    # None here; the ``row[i] or 0`` coalescing below covers the NULL case.
    row = safe_execute(con, sql, params).fetchone()
    assert row is not None  # see comment above; satisfies mypy
    data: dict[str, Any] = {
        "primary": row[0] or 0,
        "section_301": row[1] or 0,
        "ieepa": row[2] or 0,
        "mpf_capped": row[3] or 0,
        "mpf_raw": row[4] or 0,
        "hmf": row[5] or 0,
        "total_correct": row[6] or 0,
        "total_line_sum": row[7] or 0,
        "line_count": int(row[8] or 0),
        "entry_count": int(row[9] or 0),
    }
    return data, sql.strip(), int(row[9] or 0)


def _query_line_grain(
    con: duckdb.DuckDBPyConnection,
    where: str,
    params: list[Any],
) -> tuple[dict[str, Any], str, int]:
    """Line-grain breakdown using entry_lines_v (origin filter applies).

    MPF cap is NOT re-applied at line grain — once you restrict to a
    subset of lines for an entry, the per-entry cap is no longer
    meaningful. ``mpf_capped`` and ``total_correct`` are returned as
    ``None`` to make this obvious.
    """
    sql = f"""
        SELECT
            SUM(primary_duty)                          AS primary_duty,
            COALESCE(SUM(section_301_duty), 0)         AS section_301,
            COALESCE(SUM(ieepa_duty), 0)               AS ieepa,
            SUM(mpf)                                   AS mpf_raw,
            SUM(hmf)                                   AS hmf,
            SUM(total_duty_taxes_fees)                 AS total_line_sum,
            COUNT(*)                                   AS line_count,
            COUNT(DISTINCT entry_number)               AS entry_count
        FROM entry_lines_v
        WHERE {where}
    """
    # Aggregate-without-GROUP-BY: see note in _query_entry_grain above.
    row = safe_execute(con, sql, params).fetchone()
    assert row is not None
    data: dict[str, Any] = {
        "primary": row[0] or 0,
        "section_301": row[1] or 0,
        "ieepa": row[2] or 0,
        "mpf_capped": None,
        "mpf_raw": row[3] or 0,
        "hmf": row[4] or 0,
        "total_correct": None,
        "total_line_sum": row[5] or 0,
        "line_count": int(row[6] or 0),
        "entry_count": int(row[7] or 0),
    }
    return data, sql.strip(), int(row[6] or 0)


def total_duty_breakdown(
    con: duckdb.DuckDBPyConnection,
    filters: EntryFilters,
) -> ToolResult:
    """Compute the duty breakdown; picks entries_v vs entry_lines_v by grain."""
    use_line_grain = filters.country_of_origin_code is not None
    view = "entry_lines_v" if use_line_grain else "entries_v"

    where, params = build_where_clause(filters)
    t0 = now_ms()
    if use_line_grain:
        data, sql_executed, rows_inspected = _query_line_grain(con, where, params)
    else:
        data, sql_executed, rows_inspected = _query_entry_grain(con, where, params)
    latency = now_ms() - t0

    return ToolResult(
        data=data,
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=sql_executed,
            view_used=view,
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=rows_inspected,
            latency_ms=latency,
        ),
        citations=[
            Citation(
                doc="duties_fees_tariffs.txt",
                section="§Business Rule 3 — Duty Spend Aggregation",
                chunk_id="rule_3_duty_spend_aggregation",
            ),
            Citation(
                doc="data_dictionary.txt",
                section="§Quirk 1 — Section 301 China-Only",
                chunk_id="quirk_1_section_301_china_only",
            ),
            Citation(
                doc="data_dictionary.txt",
                section="§Quirk 2 — IEEPA Feb 2025+",
                chunk_id="quirk_2_ieepa_feb_2025",
            ),
            Citation(
                doc="data_dictionary.txt",
                section="§Quirk 3 — MPF Per-Entry Cap",
                chunk_id="quirk_3_mpf_per_entry_cap",
            ),
        ],
    )
