"""Tests for ``effective_duty_rate`` (Fork 22 — Q5)."""

import duckdb
import pytest

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools.effective_duty_rate import effective_duty_rate
from tests.ground_truth import q5


@pytest.mark.unit
def test_q5_matches_ground_truth(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Q5: MHF + CN + 2025-Q1 effective duty rate must match
    ``tests.ground_truth.q5`` to the cent."""
    expected = q5(duckdb_con)
    result = effective_duty_rate(
        duckdb_con,
        EntryFilters(
            customer_code="MHF",
            country_of_origin_code="CN",
            release_year_quarter="2025-Q1",
        ),
    )
    assert result.data["rate_pct"] == pytest.approx(expected["rate_pct"], abs=0.001)
    assert result.data["total_duty"] == expected["total_duty"]
    assert result.data["total_entered_value"] == expected["total_entered_value"]
    assert result.data["line_count"] == expected["line_count"]


@pytest.mark.unit
def test_meta_records_view_and_sql(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Sidecar must record view_used + actual SQL for the show-work panel."""
    result = effective_duty_rate(duckdb_con, EntryFilters())
    assert result.meta.tool_name == "effective_duty_rate"
    assert result.meta.view_used == "entry_lines_v"
    assert "entry_lines_v" in result.meta.sql_executed
    assert "SUM(total_duty_taxes_fees)" in result.meta.sql_executed


@pytest.mark.unit
def test_empty_match_returns_zeros(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Filter that matches no rows → rate_pct=0, line_count=0 (no crash).

    Uses a release_year_month outside the Oct 2024 - Mar 2025 dataset to
    guarantee zero matching rows regardless of how customer/country
    distributions evolve."""
    result = effective_duty_rate(
        duckdb_con,
        EntryFilters(release_year_month="1999-01"),
    )
    assert result.data["line_count"] == 0
    assert result.data["rate_pct"] == 0.0


@pytest.mark.unit
def test_citations_reference_kb_rule_and_metric(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Two citations: Rule 3 (duty spend aggregation) + Effective Duty Rate metric."""
    result = effective_duty_rate(duckdb_con, EntryFilters())
    chunk_ids = {c.chunk_id for c in result.citations}
    assert chunk_ids == {
        "rule_3_duty_spend_aggregation",
        "metric_effective_duty_rate",
    }
