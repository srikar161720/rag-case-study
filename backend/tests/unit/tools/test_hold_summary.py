"""Tests for ``hold_summary`` (Fork 22 — Q6)."""

import duckdb
import pytest

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools.hold_summary import (
    BENCHMARK_PCT,
    INVESTIGATION_THRESHOLD_PCT,
    _classify,
    hold_summary,
)
from tests.ground_truth import q6


@pytest.mark.unit
def test_q6_matches_ground_truth(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Q6 (no filters): hold-rate calc must match
    ``tests.ground_truth.q6`` to two decimals."""
    expected = q6(duckdb_con)
    result = hold_summary(duckdb_con, EntryFilters())
    d = result.data
    assert d["entries_total"] == expected["entries_total"]
    assert d["entries_on_hold"] == expected["entries_on_hold"]
    assert d["hold_rate_pct"] == pytest.approx(expected["hold_rate_pct"], abs=0.01)
    assert d["benchmark_pct"] == expected["benchmark_pct"]
    assert d["status"] == expected["status"]


@pytest.mark.unit
def test_status_classification_at_boundaries() -> None:
    """5%/8% thresholds: 4.99 → below; 5.0 → below; 5.01 → above; 8.0 → above;
    8.01 → warrants_investigation."""
    assert _classify(0.0) == "below"
    assert _classify(BENCHMARK_PCT) == "below"
    assert _classify(BENCHMARK_PCT + 0.01) == "above"
    assert _classify(INVESTIGATION_THRESHOLD_PCT) == "above"
    assert _classify(INVESTIGATION_THRESHOLD_PCT + 0.01) == "warrants_investigation"
    assert _classify(100.0) == "warrants_investigation"


@pytest.mark.unit
def test_constants_match_kb_spec() -> None:
    """KB §Hold Rate: benchmark 5%, investigation threshold 8%. These are
    user-facing numbers — guard against silent edits."""
    assert BENCHMARK_PCT == 5.0
    assert INVESTIGATION_THRESHOLD_PCT == 8.0


@pytest.mark.unit
def test_meta_records_entries_v_view(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    result = hold_summary(duckdb_con, EntryFilters())
    assert result.meta.view_used == "entries_v"
    assert "entries_v" in result.meta.sql_executed


@pytest.mark.unit
def test_citations_reference_metric_and_rule(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = hold_summary(duckdb_con, EntryFilters())
    chunk_ids = {c.chunk_id for c in result.citations}
    assert chunk_ids == {
        "metric_hold_rate_benchmark",
        "rule_6_on_hold_entries",
    }


@pytest.mark.unit
def test_filter_narrows_correctly(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """A customer filter must produce a SUBSET of the unfiltered result."""
    full = hold_summary(duckdb_con, EntryFilters())
    mhf = hold_summary(duckdb_con, EntryFilters(customer_code="MHF"))
    assert mhf.data["entries_total"] <= full.data["entries_total"]
    assert mhf.data["entries_on_hold"] <= full.data["entries_on_hold"]
