"""Tests for ``total_duty_breakdown`` (Fork 22 — Q4)."""

import duckdb
import pytest

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools.total_duty_breakdown import total_duty_breakdown
from tests.ground_truth import q4


@pytest.mark.unit
def test_q4_matches_ground_truth(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Q4: total Section 301 duty in Dec 2024 across all customers."""
    expected = q4(duckdb_con)
    result = total_duty_breakdown(
        duckdb_con,
        EntryFilters(release_year_month="2024-12"),
    )
    assert result.data["section_301"] == expected["section_301"]


@pytest.mark.unit
def test_no_country_filter_uses_entries_v(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Default view is entries_v (entry-grain, capped MPF available)."""
    result = total_duty_breakdown(duckdb_con, EntryFilters())
    assert result.meta.view_used == "entries_v"
    # entries_v exposes the capped MPF and total_correct fields
    assert result.data["mpf_capped"] is not None
    assert result.data["total_correct"] is not None


@pytest.mark.unit
def test_country_filter_switches_to_line_grain(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """country_of_origin_code is line-grain → swap to entry_lines_v."""
    result = total_duty_breakdown(
        duckdb_con,
        EntryFilters(country_of_origin_code="CN"),
    )
    assert result.meta.view_used == "entry_lines_v"
    # Capped MPF can't be re-derived from a line subset; report as None.
    assert result.data["mpf_capped"] is None
    assert result.data["total_correct"] is None
    # Raw line-sum totals ARE still meaningful.
    assert result.data["mpf_raw"] is not None
    assert result.data["total_line_sum"] is not None


@pytest.mark.unit
def test_breakdown_components_sum_to_total_correct(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """primary + 301 + IEEPA + mpf_capped + hmf == total_correct on entries_v.

    This is exactly the formula encoded into the view's
    ``total_duty_taxes_fees_correct`` column; tool output must agree."""
    result = total_duty_breakdown(duckdb_con, EntryFilters())
    d = result.data
    summed = (
        d["primary"] + d["section_301"] + d["ieepa"] + d["mpf_capped"] + d["hmf"]
    )
    assert summed == d["total_correct"]


@pytest.mark.unit
def test_citations_include_three_quirks_and_rule_3(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = total_duty_breakdown(duckdb_con, EntryFilters())
    chunk_ids = {c.chunk_id for c in result.citations}
    assert chunk_ids == {
        "rule_3_duty_spend_aggregation",
        "quirk_1_section_301_china_only",
        "quirk_2_ieepa_feb_2025",
        "quirk_3_mpf_per_entry_cap",
    }


@pytest.mark.unit
def test_zero_row_filter_returns_coalesced_zeros_entry_grain(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Filter that matches no rows must return zero-coalesced values, not
    NULLs. Exercises the ``row[i] or 0`` path in _query_entry_grain — the
    dead ``if row is None:`` branch was removed per Copilot PR review;
    this test pins the actual NULL-handling path that ships."""
    result = total_duty_breakdown(
        duckdb_con,
        EntryFilters(release_year_month="1999-01"),  # before dataset
    )
    d = result.data
    assert result.meta.view_used == "entries_v"
    for field in ("primary", "section_301", "ieepa", "mpf_capped",
                  "mpf_raw", "hmf", "total_correct", "total_line_sum"):
        assert d[field] == 0, f"{field} should coalesce NULL → 0; got {d[field]!r}"
    assert d["line_count"] == 0
    assert d["entry_count"] == 0


@pytest.mark.unit
def test_zero_row_filter_returns_coalesced_zeros_line_grain(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Same path exercised on _query_line_grain. mpf_capped + total_correct
    are explicitly ``None`` on line-grain (the cap can't be re-applied);
    every other numeric field coalesces to 0."""
    result = total_duty_breakdown(
        duckdb_con,
        EntryFilters(
            country_of_origin_code="CN",   # forces line-grain branch
            release_year_month="1999-01",
        ),
    )
    d = result.data
    assert result.meta.view_used == "entry_lines_v"
    for field in ("primary", "section_301", "ieepa",
                  "mpf_raw", "hmf", "total_line_sum"):
        assert d[field] == 0, f"{field} should coalesce NULL → 0; got {d[field]!r}"
    assert d["mpf_capped"] is None
    assert d["total_correct"] is None
    assert d["line_count"] == 0
    assert d["entry_count"] == 0
