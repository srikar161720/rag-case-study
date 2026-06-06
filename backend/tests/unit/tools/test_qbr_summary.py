"""Tests for ``qbr_summary`` (Fork 22 — Q9)."""

import duckdb
import pytest
from pydantic import ValidationError

from customs_agent.tools.qbr_summary import (
    QbrSummaryInput,
    qbr_summary,
)
from tests.ground_truth import q9


@pytest.mark.unit
def test_q9_matches_ground_truth(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """SAG Q1 2025 QBR must match ``tests.ground_truth.q9`` across all 4
    sections (volume, duty breakdown, top countries, hold rate)."""
    expected = q9(duckdb_con)
    got = qbr_summary(duckdb_con, "SAG", "2025-Q1").data

    # 1. entry volume by month
    assert got["entry_volume_by_month"] == expected["entry_volume_by_month"]

    # 2. duty breakdown (component sums + combined total)
    for key in ("primary", "section_301", "ieepa", "mpf_capped", "hmf", "total"):
        assert float(got["duty_breakdown"][key]) == pytest.approx(
            float(expected["duty_breakdown"][key]), abs=0.01
        )

    # 3. top sourcing countries (order + counts)
    assert got["top_countries"] == expected["top_countries"]

    # 4. hold summary
    assert got["hold_summary"]["entries_total"] == expected["hold_summary"]["entries_total"]
    assert (
        got["hold_summary"]["entries_on_hold"]
        == expected["hold_summary"]["entries_on_hold"]
    )
    assert got["hold_summary"]["hold_rate_pct"] == pytest.approx(
        expected["hold_summary"]["hold_rate_pct"], abs=0.01
    )


@pytest.mark.unit
def test_top_countries_capped_at_five(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    got = qbr_summary(duckdb_con, "SAG", "2025-Q1").data
    assert len(got["top_countries"]) <= 5


@pytest.mark.unit
def test_meta_is_composed_across_both_views(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Composed tool: no single view, but the show-work SQL spans both."""
    result = qbr_summary(duckdb_con, "SAG", "2025-Q1")
    assert result.meta.view_used is None
    assert "entries_v" in result.meta.sql_executed
    assert "entry_lines_v" in result.meta.sql_executed


@pytest.mark.unit
def test_citations_reference_qbr_and_metrics(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = qbr_summary(duckdb_con, "SAG", "2025-Q1")
    chunk_ids = {c.chunk_id for c in result.citations}
    assert chunk_ids == {
        "qbr_structure",
        "metric_hold_rate_benchmark",
        "metric_effective_duty_rate",
    }


@pytest.mark.unit
def test_input_period_pattern_enforced() -> None:
    """period must match YYYY-Q[1-4]; customer_code must be a valid Literal."""
    assert QbrSummaryInput(customer_code="SAG", period="2025-Q1").period == "2025-Q1"
    with pytest.raises(ValidationError):
        QbrSummaryInput(customer_code="SAG", period="2025-Q5")
    with pytest.raises(ValidationError):
        QbrSummaryInput(customer_code="SAG", period="2025-01")
    with pytest.raises(ValidationError):
        QbrSummaryInput(customer_code="XXX", period="2025-Q1")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        QbrSummaryInput(customer_code="SAG", period="2025-Q1", bogus="x")  # type: ignore[call-arg]
