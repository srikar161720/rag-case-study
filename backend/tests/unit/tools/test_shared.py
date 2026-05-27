"""Tests for shared tool utilities (Forks 22, 28, 50).

Three concerns:

1. ``build_where_clause`` emits parameterized SQL — every user value
   flows as a ``?`` placeholder, never inline.
2. ``safe_execute`` accepts SELECT and WITH; refuses everything else.
3. The ``ToolResult`` / ``ToolMeta`` / ``Citation`` envelope round-trips
   through ``model_dump_json`` so the sidecar (Fork 28) can serialize
   any tool's output uniformly.
"""

from datetime import date

import duckdb
import pytest

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools._shared import (
    Citation,
    ToolMeta,
    ToolResult,
    build_where_clause,
    safe_execute,
)

# ─────────────────────────────────────────────────────────────────────────────
# build_where_clause
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_filters_yield_shell_only_clause() -> None:
    """No fields set, but include_shell defaults to False → just the shell
    guard. Output must always be a non-empty WHERE so callers can splice
    it unconditionally."""
    where, params = build_where_clause(EntryFilters())
    assert where == "is_shell = FALSE"
    assert params == []


@pytest.mark.unit
def test_include_shell_true_drops_shell_guard() -> None:
    """include_shell=True with no other filters → "TRUE" (no conditions)."""
    where, params = build_where_clause(EntryFilters(include_shell=True))
    assert where == "TRUE"
    assert params == []


@pytest.mark.unit
def test_single_customer_filter() -> None:
    where, params = build_where_clause(EntryFilters(customer_code="MHF"))
    assert where == "customer_code = ? AND is_shell = FALSE"
    assert params == ["MHF"]


@pytest.mark.unit
def test_country_filter_only_valid_on_line_grain() -> None:
    """Builder emits the column unconditionally — caller chooses the view.
    Sanity that the placeholder + value pair is emitted regardless of grain."""
    where, params = build_where_clause(EntryFilters(country_of_origin_code="CN"))
    assert "country_of_origin_code = ?" in where
    assert params == ["CN"]


@pytest.mark.unit
def test_combined_filter_emits_and_join() -> None:
    where, params = build_where_clause(
        EntryFilters(
            customer_code="PCA",
            port_of_entry_code="2704",
            release_year_month="2025-01",
        )
    )
    # Order tracks the sequence of `if filters.<field> is not None:` checks
    # in build_where_clause (customer → country → port → date-range →
    # year-month → year-quarter → on_hold → is_shell guard).
    assert where == (
        "customer_code = ? "
        "AND port_of_entry_code = ? "
        "AND release_year_month = ? "
        "AND is_shell = FALSE"
    )
    assert params == ["PCA", "2704", "2025-01"]


@pytest.mark.unit
def test_date_range_emits_two_conditions() -> None:
    where, params = build_where_clause(
        EntryFilters(
            release_date_from=date(2025, 2, 1),
            release_date_to=date(2025, 3, 31),
        )
    )
    assert "release_date >= ?" in where
    assert "release_date <= ?" in where
    assert params == [date(2025, 2, 1), date(2025, 3, 31)]


@pytest.mark.unit
def test_on_hold_emits_bool_param() -> None:
    where, params = build_where_clause(EntryFilters(on_hold=True))
    assert "on_hold = ?" in where
    assert params == [True]


@pytest.mark.unit
def test_no_filter_values_inline_interpolated() -> None:
    """Belt-and-suspenders: a SQL-injection-shaped value must not appear
    in the WHERE string — it must be in the params list as data."""
    where, params = build_where_clause(EntryFilters(customer_code="MHF"))
    assert "MHF" not in where
    assert "MHF" in params


# ─────────────────────────────────────────────────────────────────────────────
# safe_execute
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


@pytest.mark.unit
def test_safe_execute_runs_select(con: duckdb.DuckDBPyConnection) -> None:
    row = safe_execute(con, "SELECT 1 AS x").fetchone()
    assert row == (1,)


@pytest.mark.unit
def test_safe_execute_runs_select_with_params(con: duckdb.DuckDBPyConnection) -> None:
    row = safe_execute(con, "SELECT ? AS x, ? AS y", ["hello", 42]).fetchone()
    assert row == ("hello", 42)


@pytest.mark.unit
def test_safe_execute_accepts_cte_with(con: duckdb.DuckDBPyConnection) -> None:
    """CTE-led queries are read-only too — must pass the guard."""
    row = safe_execute(
        con,
        "WITH t AS (SELECT 1 AS x) SELECT x + 1 FROM t",
    ).fetchone()
    assert row == (2,)


@pytest.mark.unit
def test_safe_execute_accepts_leading_whitespace(con: duckdb.DuckDBPyConnection) -> None:
    """\\n   SELECT ... → still a SELECT."""
    row = safe_execute(con, "\n   SELECT 7").fetchone()
    assert row == (7,)


@pytest.mark.unit
def test_safe_execute_lowercase_select_ok(con: duckdb.DuckDBPyConnection) -> None:
    """Case-insensitive guard — agents might emit lowercase keywords."""
    row = safe_execute(con, "select 5").fetchone()
    assert row == (5,)


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO entries_v VALUES (1)",
        "UPDATE entries_v SET on_hold = TRUE",
        "DELETE FROM entries_v",
        "DROP TABLE entries_v",
        "CREATE TABLE foo (x INT)",
        "ALTER TABLE entries_v ADD COLUMN x INT",
        "TRUNCATE entries_v",
        "PRAGMA database_list",
        "ATTACH 'other.db'",
        "",
        "   ",
    ],
)
def test_safe_execute_refuses_non_read(
    con: duckdb.DuckDBPyConnection, sql: str
) -> None:
    with pytest.raises(ValueError) as exc:
        safe_execute(con, sql)
    assert "safe_execute" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# ToolResult / ToolMeta / Citation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tool_result_round_trip() -> None:
    """ToolResult → JSON → ToolResult preserves shape."""
    original = ToolResult(
        data={"answer": 42, "extra": [1, 2, 3]},
        meta=ToolMeta(
            tool_name="example",
            sql_executed="SELECT 42",
            view_used="entries_v",
            filters_applied={"customer_code": "MHF"},
            shell_entries_excluded=0,
            rows_inspected=1,
            latency_ms=3,
        ),
        citations=[
            Citation(
                doc="duties_fees_tariffs.txt",
                section="§Rule 1",
                chunk_id="rule_1_date_filtering",
            ),
        ],
    )
    rehydrated = ToolResult.model_validate_json(original.model_dump_json())
    assert rehydrated.data == original.data
    assert rehydrated.meta == original.meta
    assert rehydrated.citations == original.citations


@pytest.mark.unit
def test_tool_meta_allows_null_sql_for_non_sql_tools() -> None:
    """lookup_knowledge has no SQL — sql_executed must accept None."""
    meta = ToolMeta(
        tool_name="lookup_knowledge",
        sql_executed=None,
        view_used=None,
        filters_applied={},
        shell_entries_excluded=0,
        rows_inspected=5,
        latency_ms=12,
    )
    assert meta.sql_executed is None
    assert meta.view_used is None


@pytest.mark.unit
def test_tool_result_citations_do_not_share_state() -> None:
    """Regression: ``citations`` uses ``Field(default_factory=list)`` so two
    instances created without an explicit citations list don't share the
    same underlying object. Pydantic v2 deep-copies field defaults, but the
    explicit factory matches our codebase style AND defends against future
    Pydantic behavior changes / lint rules (RUF012).
    """
    meta = ToolMeta(
        tool_name="example", sql_executed=None, view_used=None,
        filters_applied={}, shell_entries_excluded=0,
        rows_inspected=0, latency_ms=0,
    )
    a = ToolResult(data={}, meta=meta)
    b = ToolResult(data={}, meta=meta)
    # Different list instances.
    assert a.citations is not b.citations
    # Mutating one must not leak into the other.
    a.citations.append(
        Citation(doc="x.txt", section="§1", chunk_id="rule_1_date_filtering")
    )
    assert len(a.citations) == 1
    assert len(b.citations) == 0
