"""Tests for ``query_entries`` (Fork 22 — Q1, Q2, Q3, Q11).

Covers the four ground-truth questions the general builder serves, the
allowlist rejection path (Fork 50 SQL-safety boundary), and the SQL
shape (GROUP BY / ORDER BY / LIMIT).
"""

import duckdb
import pytest
from pydantic import ValidationError

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools.query_entries import (
    QueryEntriesInput,
    _parse_aggregation,
    _resolve_order_by,
    query_entries,
)
from tests.ground_truth import q1, q2, q3, q11

# ─────────────────────────────────────────────────────────────────────────────
# Ground-truth parity
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_q1_pca_january_entries(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Q1: COUNT(DISTINCT entry_number) FROM entries_v WHERE PCA + 2025-01."""
    expected = q1(duckdb_con)
    result = query_entries(
        duckdb_con,
        view="entries_v",
        filters=EntryFilters(
            customer_code="PCA",
            release_year_month="2025-01",
        ),
        aggregations=["count_distinct_entries"],
    )
    assert len(result.data) == 1
    assert result.data[0]["entry_count"] == expected["entry_count"]


@pytest.mark.unit
def test_q2_sag_q1_2025_entered_value(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Q2: SUM(total_entered_value) FROM entries_v WHERE SAG + 2025-Q1.

    Verifies the sum-alias-collapses-to-column-name rule (so the result
    key reads ``total_entered_value`` not ``sum_total_entered_value``)."""
    expected = q2(duckdb_con)
    result = query_entries(
        duckdb_con,
        view="entries_v",
        filters=EntryFilters(
            customer_code="SAG",
            release_year_quarter="2025-Q1",
        ),
        aggregations=["sum(total_entered_value)"],
    )
    assert len(result.data) == 1
    assert result.data[0]["total_entered_value"] == expected["total_entered_value"]


@pytest.mark.unit
def test_q3_top_port_by_entry_count(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Q3: GROUP BY port + ORDER BY entry_count DESC + LIMIT 1.

    Exercises every structural feature: group_by, aggregations, order_by
    (with aggregation-name → alias resolution), and limit."""
    expected = q3(duckdb_con)
    result = query_entries(
        duckdb_con,
        view="entries_v",
        group_by=["port_of_entry_code", "port_of_entry_name"],
        aggregations=["count_distinct_entries"],
        order_by=[("count_distinct_entries", "desc")],
        limit=1,
    )
    assert len(result.data) == 1
    row = result.data[0]
    assert row["port_of_entry_code"] == expected["port_of_entry_code"]
    assert row["port_of_entry_name"] == expected["port_of_entry_name"]
    assert row["entry_count"] == expected["entry_count"]


@pytest.mark.unit
def test_q11_entry_vs_line_count_for_mhf_nov_2024(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Q11: two calls — one entries_v + count_distinct_entries, one
    entry_lines_v + count_lines. Difference confirms Business Rule 2."""
    expected = q11(duckdb_con)

    entry_result = query_entries(
        duckdb_con,
        view="entries_v",
        filters=EntryFilters(
            customer_code="MHF",
            release_year_month="2024-11",
        ),
        aggregations=["count_distinct_entries"],
    )
    line_result = query_entries(
        duckdb_con,
        view="entry_lines_v",
        filters=EntryFilters(
            customer_code="MHF",
            release_year_month="2024-11",
        ),
        aggregations=["count_lines"],
    )
    entry_count = entry_result.data[0]["entry_count"]
    line_count = line_result.data[0]["line_count"]
    assert entry_count == expected["entry_count"]
    assert line_count == expected["line_count"]
    assert line_count - entry_count == expected["difference"]


# ─────────────────────────────────────────────────────────────────────────────
# Allowlist enforcement (Fork 50)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_invalid_group_by_column_rejected_at_input_model() -> None:
    """QueryEntriesInput.field_validator rejects non-allowlisted columns
    BEFORE any SQL is built."""
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(group_by=["entered_value"])  # measure, not dim
    assert "Invalid group_by" in str(exc.value)


@pytest.mark.unit
def test_invalid_aggregation_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(aggregations=["sum(secret_password)"])
    assert "Invalid aggregations" in str(exc.value)


@pytest.mark.unit
def test_invalid_order_by_column_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(order_by=[("rogue_col", "asc")])
    assert "Invalid order_by" in str(exc.value)


@pytest.mark.unit
def test_limit_capped_at_200() -> None:
    with pytest.raises(ValidationError):
        QueryEntriesInput(limit=201)


@pytest.mark.unit
def test_limit_floor_at_1() -> None:
    with pytest.raises(ValidationError):
        QueryEntriesInput(limit=0)


@pytest.mark.unit
def test_unknown_view_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryEntriesInput(view="information_schema")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation parsing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "agg, expected_sql, expected_alias",
    [
        ("count_distinct_entries", "COUNT(DISTINCT entry_number)", "entry_count"),
        ("count_lines", "COUNT(*)", "line_count"),
        ("sum(total_entered_value)", "SUM(total_entered_value)", "total_entered_value"),
        ("avg(entered_value)", "AVG(entered_value)", "avg_entered_value"),
        ("min(release_date)", "MIN(release_date)", "min_release_date"),
        (
            "max(total_duty_taxes_fees_correct)",
            "MAX(total_duty_taxes_fees_correct)",
            "max_total_duty_taxes_fees_correct",
        ),
    ],
)
def test_parse_aggregation(agg: str, expected_sql: str, expected_alias: str) -> None:
    sql, alias = _parse_aggregation(agg)
    assert sql == expected_sql
    assert alias == expected_alias


@pytest.mark.unit
def test_resolve_order_by_translates_aggregation() -> None:
    """ORDER BY count_distinct_entries → ORDER BY entry_count (the alias)."""
    assert _resolve_order_by("count_distinct_entries") == "entry_count"
    assert _resolve_order_by("count_lines") == "line_count"
    assert _resolve_order_by("sum(total_entered_value)") == "total_entered_value"


@pytest.mark.unit
def test_resolve_order_by_passes_through_columns() -> None:
    """Group-by column names pass through unchanged."""
    assert _resolve_order_by("customer_code") == "customer_code"
    assert _resolve_order_by("release_year_month") == "release_year_month"


# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sql_includes_group_by_and_order_by(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """sidecar's sql_executed must show the actual emitted SQL."""
    result = query_entries(
        duckdb_con,
        view="entries_v",
        group_by=["customer_code"],
        aggregations=["count_distinct_entries"],
        order_by=[("count_distinct_entries", "desc")],
        limit=10,
    )
    sql = result.meta.sql_executed
    assert "GROUP BY customer_code" in sql
    assert "ORDER BY entry_count DESC" in sql
    assert "LIMIT 10" in sql


@pytest.mark.unit
def test_default_aggregation_is_count_distinct_entries() -> None:
    """No explicit aggregations → defaults to count_distinct_entries."""
    inp = QueryEntriesInput()
    assert inp.aggregations == ["count_distinct_entries"]
