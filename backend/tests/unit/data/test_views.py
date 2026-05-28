"""Unit tests for :mod:`customs_agent.data.views` (Fork 19, 20).

Covers the encoded business rules in ``entries_v`` and ``entry_lines_v``:

- **MPF cap math** (KB §Quirk 3): per-entry $31.67 minimum, $614.35
  maximum. Real data exercises the ceiling (911 entries) and a passthrough
  case; a synthetic insert covers the floor (zero real entries fall below).
- **Shell detection** (Fork 20): ``LENGTH(entry_number) != 11`` OR
  ``SUM(entered_value) = 0``. Real dataset has zero shells; synthetic
  inserts cover both branches.
- **COALESCE** on ``total_section_301_duty`` / ``total_ieepa_duty`` —
  defensive zero-fill so downstream tools never see NULL.
- **``total_duty_taxes_fees_correct``** formula:
  ``primary + 301 + ieepa + capped_mpf + hmf`` (the version tools must
  use, NOT the raw line-sum).
- View existence, idempotency, LEFT JOIN integrity between the two views,
  and period-helper string formats.
"""

from decimal import Decimal

import duckdb
import pytest

from customs_agent.data.views import create_views


@pytest.mark.unit
def test_create_views_creates_both_views(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Both ``entries_v`` and ``entry_lines_v`` exist after
    :func:`create_views`.
    """
    names = {
        row[0]
        for row in duckdb_con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type = 'VIEW'"
        ).fetchall()
    }
    assert "entries_v" in names
    assert "entry_lines_v" in names


@pytest.mark.unit
def test_create_views_is_idempotent(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Calling :func:`create_views` twice succeeds (DROP VIEW IF EXISTS
    on both, in the order that respects ``entry_lines_v`` →
    ``entries_v`` dependency)."""
    create_views(fresh_duckdb_con)
    # Smoke check that both views still query cleanly.
    row = fresh_duckdb_con.execute("SELECT COUNT(*) FROM entries_v").fetchone()
    assert row is not None
    assert row[0] > 0


@pytest.mark.unit
def test_entries_v_one_row_per_entry_number(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``entries_v`` collapses to one row per distinct entry_number."""
    row_v = duckdb_con.execute("SELECT COUNT(*) FROM entries_v").fetchone()
    row_distinct = duckdb_con.execute(
        "SELECT COUNT(DISTINCT entry_number) FROM entry_lines"
    ).fetchone()
    assert row_v is not None
    assert row_distinct is not None
    assert row_v[0] == row_distinct[0]


@pytest.mark.unit
def test_entry_lines_v_row_count_matches_base_table(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """LEFT JOIN integrity: ``entry_lines_v`` row count equals
    ``entry_lines``. A regression to INNER JOIN here would silently
    drop lines whose entry_number doesn't appear in ``entries_v``.
    """
    base = duckdb_con.execute("SELECT COUNT(*) FROM entry_lines").fetchone()
    joined = duckdb_con.execute("SELECT COUNT(*) FROM entry_lines_v").fetchone()
    assert base is not None
    assert joined is not None
    assert base[0] == joined[0]


@pytest.mark.unit
def test_mpf_ceiling_caps_at_614_35_on_real_data(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Real-data ceiling: any entry whose raw MPF sum exceeds $614.35
    is capped to exactly $614.35 in ``total_mpf_capped``.
    """
    row = duckdb_con.execute(
        """
        SELECT total_mpf_raw, total_mpf_capped
        FROM entries_v
        WHERE total_mpf_raw > 614.35
        LIMIT 1
        """
    ).fetchone()
    assert row is not None, "expected at least one entry with raw MPF > $614.35"
    raw, capped = row
    assert raw > Decimal("614.35")
    assert capped == Decimal("614.35")


@pytest.mark.unit
def test_mpf_floor_caps_to_31_67_when_raw_below(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Floor cap: when a single-line entry's raw MPF sum is below $31.67,
    ``total_mpf_capped`` floors to exactly $31.67.

    The real dataset has zero entries below the floor (every existing
    entry's raw MPF sums to ≥ $31.67 exactly), so this assertion can
    only be exercised against a synthetic row.
    """
    fresh_duckdb_con.execute(
        """
        INSERT INTO entry_lines (
            entry_number, customer_code, country_of_origin_code,
            release_date, entered_value, mpf
        )
        VALUES ('99999999999', 'MHF', 'CN', DATE '2025-03-01', 1000.00, 5.00)
        """
    )
    row = fresh_duckdb_con.execute(
        """
        SELECT total_mpf_raw, total_mpf_capped
        FROM entries_v
        WHERE entry_number = '99999999999'
        """
    ).fetchone()
    assert row is not None
    raw, capped = row
    assert raw == Decimal("5.00")
    assert capped == Decimal("31.67")


@pytest.mark.unit
def test_mpf_passthrough_when_within_bounds(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """When the raw MPF sum is within ``[31.67, 614.35]``,
    ``total_mpf_capped`` equals ``total_mpf_raw`` (no cap applied).
    """
    row = duckdb_con.execute(
        """
        SELECT total_mpf_raw, total_mpf_capped
        FROM entries_v
        WHERE total_mpf_raw > 100 AND total_mpf_raw < 500
        LIMIT 1
        """
    ).fetchone()
    assert row is not None, "expected at least one entry with mid-range MPF"
    raw, capped = row
    assert raw == capped
    assert Decimal("31.67") <= capped <= Decimal("614.35")


@pytest.mark.unit
def test_section_301_coalesced_to_zero_no_nulls(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``total_section_301_duty`` is never NULL — ``COALESCE(SUM(...), 0)``
    in ``entries_v`` zero-fills any entry whose lines all have NULL
    section_301_duty (defensive shape; real data is zero-filled already).
    """
    row = duckdb_con.execute(
        "SELECT COUNT(*) FROM entries_v WHERE total_section_301_duty IS NULL"
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_ieepa_coalesced_to_zero_no_nulls(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``total_ieepa_duty`` is never NULL — same COALESCE pattern as
    Section 301."""
    row = duckdb_con.execute(
        "SELECT COUNT(*) FROM entries_v WHERE total_ieepa_duty IS NULL"
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_origin_country_codes_is_list_consistent_with_count(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``LIST(DISTINCT country_of_origin_code)`` and the parallel
    ``COUNT(DISTINCT ...)`` agree on cardinality per entry.

    A future regression that swapped ``DISTINCT`` for raw ``LIST`` would
    diverge here for entries with repeated country codes across lines.
    """
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entries_v
        WHERE LEN(origin_country_codes) != distinct_origin_count
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_shell_flag_true_when_entry_number_length_not_11(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``is_shell`` is True when ``LENGTH(entry_number) != 11``
    (Fork 20 left-branch)."""
    fresh_duckdb_con.execute(
        """
        INSERT INTO entry_lines (
            entry_number, customer_code, country_of_origin_code,
            release_date, entered_value
        )
        VALUES ('12345', 'MHF', 'CN', DATE '2025-03-01', 1000.00)
        """
    )
    row = fresh_duckdb_con.execute(
        "SELECT is_shell FROM entries_v WHERE entry_number = '12345'"
    ).fetchone()
    assert row is not None
    assert row[0] is True


@pytest.mark.unit
def test_shell_flag_true_when_total_entered_value_zero(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``is_shell`` is True when ``SUM(entered_value) = 0``
    (Fork 20 right-branch)."""
    fresh_duckdb_con.execute(
        """
        INSERT INTO entry_lines (
            entry_number, customer_code, country_of_origin_code,
            release_date, entered_value
        )
        VALUES ('99999999988', 'MHF', 'CN', DATE '2025-03-01', 0.00)
        """
    )
    row = fresh_duckdb_con.execute(
        "SELECT is_shell FROM entries_v WHERE entry_number = '99999999988'"
    ).fetchone()
    assert row is not None
    assert row[0] is True


@pytest.mark.unit
def test_total_duty_taxes_fees_correct_formula(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``total_duty_taxes_fees_correct`` equals
    ``primary + 301 + ieepa + capped_mpf + hmf``. Pick an entry that
    exercises every term (CN-origin + post-Feb-2025 → both 301 and IEEPA
    populated; high enough MPF to engage the cap)."""
    row = duckdb_con.execute(
        """
        SELECT
            total_primary_duty,
            total_section_301_duty,
            total_ieepa_duty,
            total_mpf_capped,
            total_hmf,
            total_duty_taxes_fees_correct
        FROM entries_v
        WHERE total_section_301_duty > 0
          AND total_ieepa_duty > 0
        LIMIT 1
        """
    ).fetchone()
    assert row is not None
    primary, sec_301, ieepa, mpf_capped, hmf, correct = row
    assert correct == primary + sec_301 + ieepa + mpf_capped + hmf


@pytest.mark.unit
def test_release_year_month_format(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``release_year_month`` follows ``YYYY-MM`` format (matches the
    Pydantic filter pattern in :data:`EntryFilters.release_year_month`).
    """
    rows = duckdb_con.execute(
        "SELECT DISTINCT release_year_month FROM entries_v"
    ).fetchall()
    assert len(rows) > 0
    import re

    pattern = re.compile(r"^\d{4}-\d{2}$")
    for (ym,) in rows:
        assert pattern.match(ym), f"release_year_month {ym!r} does not match YYYY-MM"


@pytest.mark.unit
def test_release_year_quarter_format(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``release_year_quarter`` follows ``YYYY-Q[1-4]`` format (matches the
    Pydantic filter pattern in :data:`EntryFilters.release_year_quarter`).
    """
    rows = duckdb_con.execute(
        "SELECT DISTINCT release_year_quarter FROM entries_v"
    ).fetchall()
    assert len(rows) > 0
    import re

    pattern = re.compile(r"^\d{4}-Q[1-4]$")
    for (yq,) in rows:
        assert pattern.match(yq), f"release_year_quarter {yq!r} does not match YYYY-Q[1-4]"
