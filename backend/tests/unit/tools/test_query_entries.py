"""Tests for ``query_entries`` (Fork 22 — Q1, Q2, Q3, Q11).

Covers the four ground-truth questions the general builder serves, the
allowlist rejection path (Fork 50 SQL-safety boundary), and the SQL
shape (GROUP BY / ORDER BY / LIMIT).
"""

import duckdb
import pytest
import structlog.testing
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
def test_invalid_columns_emit_sql_safety_event() -> None:
    """Each allowlist validator logs ``sql_safety.invalid_column_name`` with
    the offending field + values before raising ``ValidationError`` (Fork 52)."""
    cases = [
        ({"group_by": ["entered_value"]}, "group_by", "entered_value"),
        (
            {"aggregations": ["sum(secret_password)"]},
            "aggregations",
            "sum(secret_password)",
        ),
        ({"order_by": [("rogue_col", "asc")]}, "order_by", "rogue_col"),
    ]
    for kwargs, field, bad_value in cases:
        with structlog.testing.capture_logs() as logs:
            with pytest.raises(ValidationError):
                QueryEntriesInput(**kwargs)
        events = [e for e in logs if e["event"] == "sql_safety.invalid_column_name"]
        assert len(events) == 1, f"expected one event for field={field}"
        assert events[0]["field"] == field
        assert bad_value in events[0]["invalid_values"]


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


# ─────────────────────────────────────────────────────────────────────────────
# View-compatibility validator (PR #5 Copilot Comment 4 follow-up)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_country_filter_on_entries_v_rejected() -> None:
    """country_of_origin_code is line-grain and not in entries_v."""
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(
            view="entries_v",
            filters=EntryFilters(country_of_origin_code="CN"),
        )
    assert "country_of_origin_code" in str(exc.value)
    assert "entries_v" in str(exc.value)


@pytest.mark.unit
def test_hts_code_group_by_on_entries_v_rejected() -> None:
    """hts_code is line-grain (entry_lines_v) only."""
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(view="entries_v", group_by=["hts_code"])
    assert "hts_code" in str(exc.value)
    assert "line-grain" in str(exc.value)


@pytest.mark.unit
def test_mid_group_by_on_entries_v_rejected() -> None:
    """mid (manufacturer ID) is line-grain only."""
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(view="entries_v", group_by=["mid"])
    assert "mid" in str(exc.value)


@pytest.mark.unit
def test_line_grain_sum_on_entries_v_rejected() -> None:
    """sum(entered_value) references the line-grain column; on entries_v
    use sum(total_entered_value) instead."""
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(
            view="entries_v",
            aggregations=["sum(entered_value)"],
        )
    assert "sum(entered_value)" in str(exc.value)
    assert "total_entered_value" in str(exc.value)  # suggestion in error msg


@pytest.mark.unit
def test_entries_v_aggregate_on_line_grain_view_rejected() -> None:
    """sum(total_entered_value) is an entries_v rollup; on entry_lines_v
    use sum(entered_value)."""
    with pytest.raises(ValidationError) as exc:
        QueryEntriesInput(
            view="entry_lines_v",
            aggregations=["sum(total_entered_value)"],
        )
    assert "sum(total_entered_value)" in str(exc.value)
    assert "entries_v" in str(exc.value)


@pytest.mark.unit
def test_compatible_combos_pass_through() -> None:
    """Sanity: each ground-truth combo (Q1, Q2, Q3, Q11) parses cleanly."""
    # Q1: entries_v + customer + period filter + default count
    QueryEntriesInput(
        view="entries_v",
        filters=EntryFilters(customer_code="PCA", release_year_month="2025-01"),
    )
    # Q2: entries_v + sum(total_entered_value)
    QueryEntriesInput(
        view="entries_v",
        filters=EntryFilters(customer_code="SAG", release_year_quarter="2025-Q1"),
        aggregations=["sum(total_entered_value)"],
    )
    # Q3: entries_v + group by port columns + count + order by
    QueryEntriesInput(
        view="entries_v",
        group_by=["port_of_entry_code", "port_of_entry_name"],
        aggregations=["count_distinct_entries"],
        order_by=[("count_distinct_entries", "desc")],
        limit=1,
    )
    # Q11 (line side): entry_lines_v + customer + period + count_lines
    QueryEntriesInput(
        view="entry_lines_v",
        filters=EntryFilters(customer_code="MHF", release_year_month="2024-11"),
        aggregations=["count_lines"],
    )


@pytest.mark.unit
def test_shared_columns_work_on_both_views() -> None:
    """port_of_entry_code / customer_code / release_year_month / etc. exist
    on both views and must pass through regardless of selected view."""
    for view in ("entries_v", "entry_lines_v"):
        QueryEntriesInput(
            view=view,  # type: ignore[arg-type]
            filters=EntryFilters(
                customer_code="MHF",
                port_of_entry_code="2704",
                release_year_month="2025-01",
            ),
            group_by=["customer_code"],
        )


@pytest.mark.unit
def test_count_aggregations_work_on_both_views() -> None:
    """count_distinct_entries and count_lines reference entry_number (shared)
    and don't trip the view-compat check on either view."""
    for view in ("entries_v", "entry_lines_v"):
        QueryEntriesInput(
            view=view,  # type: ignore[arg-type]
            aggregations=["count_distinct_entries", "count_lines"],
        )
