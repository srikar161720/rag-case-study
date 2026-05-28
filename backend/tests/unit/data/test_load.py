"""Unit tests for :mod:`customs_agent.data.load` (Fork 18).

Covers:

- The typed CAST schema (DECIMAL / DATE / BOOLEAN / INTEGER on the
  columns where it matters).
- The ``NULLIF('', col)`` behavior on Section 301 and IEEPA CODE columns
  combined with the zero-fill on their DUTY siblings (KB §Quirks 1+2 —
  CODE column is the authoritative applicability signal; duty columns
  are populated to ``0.00`` on non-applicable rows in the actual CSV,
  NOT ``NULL``).
- The four columns derived at load time: ``port_of_entry_code``,
  ``port_of_entry_name``, ``entry_type_code``, ``is_china_origin``.
- Idempotency of :func:`load_entries` (re-running on the same connection
  must not double-load — guarded by ``DROP TABLE IF EXISTS``).
"""

import duckdb
import pytest

from customs_agent.data.load import load_entries
from customs_agent.data.validation import (
    EXPECTED_DISTINCT_ENTRIES,
    EXPECTED_ROW_COUNT,
)


@pytest.mark.unit
def test_load_creates_entry_lines_table(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """After :func:`load_entries`, the ``entry_lines`` table exists."""
    row = duckdb_con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = 'entry_lines'"
    ).fetchone()
    assert row is not None
    assert row[0] == "entry_lines"


@pytest.mark.unit
def test_load_row_count_matches_expected(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """``EXPECTED_ROW_COUNT`` rows present after load."""
    row = duckdb_con.execute("SELECT COUNT(*) FROM entry_lines").fetchone()
    assert row is not None
    assert row[0] == EXPECTED_ROW_COUNT


@pytest.mark.unit
def test_load_distinct_entry_count(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """``EXPECTED_DISTINCT_ENTRIES`` distinct entry numbers after load."""
    row = duckdb_con.execute(
        "SELECT COUNT(DISTINCT entry_number) FROM entry_lines"
    ).fetchone()
    assert row is not None
    assert row[0] == EXPECTED_DISTINCT_ENTRIES


@pytest.mark.unit
def test_load_typed_column_schemas(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Spot-check the CAST schema — money is DECIMAL, dates are DATE,
    booleans are BOOLEAN, ordinals are INTEGER.

    Catches accidental ``all_varchar=True`` regressions or a forgotten
    CAST in :func:`load_entries`.
    """
    types = {
        row[0]: row[1]
        for row in duckdb_con.execute("DESCRIBE entry_lines").fetchall()
    }
    # Dates
    assert types["entry_filed_date"] == "DATE"
    assert types["release_date"] == "DATE"
    assert types["summary_date"] == "DATE"
    # Decimals (money)
    assert types["entered_value"] == "DECIMAL(18,2)"
    assert types["primary_duty"] == "DECIMAL(18,2)"
    assert types["section_301_duty"] == "DECIMAL(18,2)"
    assert types["ieepa_duty"] == "DECIMAL(18,2)"
    assert types["mpf"] == "DECIMAL(18,2)"
    assert types["hmf"] == "DECIMAL(18,2)"
    assert types["total_duty_taxes_fees"] == "DECIMAL(18,2)"
    # Decimal — fractional precision
    assert types["duty_rate_pct"] == "DECIMAL(7,4)"
    assert types["units"] == "DECIMAL(18,4)"
    # Integer
    assert types["invoice_tariff_line"] == "INTEGER"
    # Booleans
    assert types["on_hold"] == "BOOLEAN"
    assert types["is_china_origin"] == "BOOLEAN"


@pytest.mark.unit
def test_load_is_idempotent(fresh_duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Calling :func:`load_entries` twice on the same connection still
    yields exactly :data:`EXPECTED_ROW_COUNT` rows (DROP IF EXISTS, not
    append).
    """
    load_entries(fresh_duckdb_con)
    row = fresh_duckdb_con.execute("SELECT COUNT(*) FROM entry_lines").fetchone()
    assert row is not None
    assert row[0] == EXPECTED_ROW_COUNT


@pytest.mark.unit
def test_load_section_301_code_nulled_on_non_cn(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Section 301 CODE column is ``NULL`` on every non-CN line (KB §Quirk 1).

    The ``NULLIF('', "Section 301 Code")`` converts the empty string in
    the CSV to ``NULL`` on non-applicable rows. The CODE column is the
    authoritative applicability signal — see :mod:`customs_agent.data.load`.
    """
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE section_301_code IS NOT NULL AND country_of_origin_code != 'CN'
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_load_section_301_duty_zero_filled_on_non_cn(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Section 301 DUTY column is ``0.00`` (NOT NULL) on non-CN lines.

    Counterpart to the CODE-column NULL test — the duty column carries an
    explicit zero in the CSV on non-applicable rows. This contrast is
    what makes the CODE column the canonical applicability signal.
    """
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE country_of_origin_code != 'CN' AND section_301_duty IS NULL
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_load_ieepa_code_nulled_on_pre_feb_2025(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """IEEPA CODE column is ``NULL`` on every pre-2025-02-01 release (KB §Quirk 2)."""
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE ieepa_code IS NOT NULL AND release_date < DATE '2025-02-01'
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_load_ieepa_duty_zero_filled_on_pre_feb_2025(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """IEEPA DUTY column is ``0.00`` (NOT NULL) on pre-Feb-2025 lines."""
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE release_date < DATE '2025-02-01' AND ieepa_duty IS NULL
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_load_derives_port_of_entry_code_and_name(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``port_of_entry_code`` is the leading digits; ``port_of_entry_name``
    is the parenthesized text, on the same row.
    """
    rows = duckdb_con.execute(
        """
        SELECT DISTINCT port_of_entry, port_of_entry_code, port_of_entry_name
        FROM entry_lines
        WHERE port_of_entry_code = '5301'
        """
    ).fetchall()
    assert len(rows) == 1
    raw, code, name = rows[0]
    assert raw.startswith("5301")
    assert code == "5301"
    assert name == "Houston"


@pytest.mark.unit
def test_load_derives_entry_type_code(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """``entry_type_code`` is the first 2 characters of ``entry_type``."""
    rows = duckdb_con.execute(
        "SELECT DISTINCT entry_type, entry_type_code FROM entry_lines"
    ).fetchall()
    # Sanity: at least one row, and code is always the first 2 chars of the source.
    assert len(rows) > 0
    for entry_type, code in rows:
        assert code == entry_type[:2]


@pytest.mark.unit
def test_load_derives_is_china_origin(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """``is_china_origin`` is ``True`` iff ``country_of_origin_code = 'CN'``."""
    rows = duckdb_con.execute(
        """
        SELECT country_of_origin_code, is_china_origin, COUNT(*)
        FROM entry_lines
        GROUP BY 1, 2
        """
    ).fetchall()
    for country_code, is_cn, _ in rows:
        assert is_cn == (country_code == "CN")
