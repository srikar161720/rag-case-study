"""Unit tests for :mod:`customs_agent.data.validation` (Fork 18, 20, 21).

Three layers:

1. **Happy path + structlog INFO log** — confirms the validator runs
   cleanly on the real dataset and emits the
   ``data.validation.complete`` event with ``shell_entries_detected=0``.
2. **Positive baselines** (5) — assert each expected invariant holds on
   the real, unmodified dataset. These double as living documentation
   of what the validator considers "OK" data.
3. **Negative drift tests** (7) — one per assertion in
   :func:`validate_loaded_data`. Each mutates exactly one column so a
   specific :class:`AssertionError` fires, captured via
   :func:`pytest.raises` with a ``match=`` regex anchored on the
   error string.

The order of assertions in :func:`validate_loaded_data` matters for the
mutation choice: each negative test mutates the *smallest* slice of
data that triggers its target assertion without tripping an earlier
one (row count is checked first, then distinct entries, then Section
301, IEEPA, customer / country / port enums).
"""

import duckdb
import pytest
import structlog.testing

from customs_agent.data.validation import (
    EXPECTED_COUNTRIES,
    EXPECTED_CUSTOMERS,
    EXPECTED_DISTINCT_ENTRIES,
    EXPECTED_PORTS,
    EXPECTED_ROW_COUNT,
    validate_loaded_data,
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Happy path + log assertion
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_validate_passes_on_real_data(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Sanity: the validator runs to completion without raising on the
    real dataset.

    Uses ``fresh_duckdb_con`` rather than ``duckdb_con`` because the
    session fixture already calls :func:`validate_loaded_data` once;
    we want this test to exercise the call explicitly with no prior
    state.
    """
    validate_loaded_data(fresh_duckdb_con)  # must not raise


@pytest.mark.unit
def test_validate_logs_shell_count_zero(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """The INFO event ``data.validation.complete`` carries the row count,
    distinct entry count, and ``shell_entries_detected`` (which is 0 on
    current data — recorded but not asserted by the validator itself).

    Uses :func:`structlog.testing.capture_logs` so the test doesn't
    depend on whichever renderer structlog defaults to outside the
    boot configuration (see CLAUDE.md Critical Gotcha #11).
    """
    with structlog.testing.capture_logs() as captured:
        validate_loaded_data(fresh_duckdb_con)

    events = [e for e in captured if e.get("event") == "data.validation.complete"]
    assert len(events) == 1
    event = events[0]
    assert event["rows"] == EXPECTED_ROW_COUNT
    assert event["distinct_entries"] == EXPECTED_DISTINCT_ENTRIES
    assert event["shell_entries_detected"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Positive baselines — each invariant the validator checks holds on
#    the real, unmodified dataset.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_real_data_row_count_matches_constant(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``entry_lines`` carries exactly ``EXPECTED_ROW_COUNT`` rows."""
    row = duckdb_con.execute("SELECT COUNT(*) FROM entry_lines").fetchone()
    assert row is not None
    assert row[0] == EXPECTED_ROW_COUNT


@pytest.mark.unit
def test_real_data_distinct_entries_matches_constant(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """``entry_lines`` carries exactly ``EXPECTED_DISTINCT_ENTRIES``
    distinct entry numbers."""
    row = duckdb_con.execute(
        "SELECT COUNT(DISTINCT entry_number) FROM entry_lines"
    ).fetchone()
    assert row is not None
    assert row[0] == EXPECTED_DISTINCT_ENTRIES


@pytest.mark.unit
def test_real_data_section_301_only_on_cn(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """No non-CN row has ``section_301_code`` populated (KB §Quirk 1)."""
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE section_301_code IS NOT NULL AND country_of_origin_code != 'CN'
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_real_data_ieepa_only_on_post_feb_2025(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """No pre-2025-02-01 row has ``ieepa_code`` populated (KB §Quirk 2)."""
    row = duckdb_con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE ieepa_code IS NOT NULL AND release_date < DATE '2025-02-01'
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0


@pytest.mark.unit
def test_real_data_enums_match_filter_literals(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Distinct customer / country / port codes in the loaded data equal
    the ``Literal`` aliases declared in
    :mod:`customs_agent.tools._filters`.
    """
    actual_customers = frozenset(
        r[0]
        for r in duckdb_con.execute(
            "SELECT DISTINCT customer_code FROM entries_v"
        ).fetchall()
    )
    actual_countries = frozenset(
        r[0]
        for r in duckdb_con.execute(
            "SELECT DISTINCT country_of_origin_code FROM entry_lines_v"
        ).fetchall()
    )
    actual_ports = frozenset(
        r[0]
        for r in duckdb_con.execute(
            "SELECT DISTINCT port_of_entry_code FROM entries_v"
        ).fetchall()
    )
    assert actual_customers == EXPECTED_CUSTOMERS
    assert actual_countries == EXPECTED_COUNTRIES
    assert actual_ports == EXPECTED_PORTS


# ─────────────────────────────────────────────────────────────────────────────
# 3. Negative drift tests — one per assertion. Each mutation isolates a
#    single invariant so the right error message surfaces.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_validate_fails_on_row_count_drift(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """INSERT one extra line into an existing entry — row count rises
    to ``EXPECTED_ROW_COUNT + 1``, distinct entries unchanged. Row-count
    assertion fires first.
    """
    target = fresh_duckdb_con.execute(
        "SELECT entry_number FROM entry_lines LIMIT 1"
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        """
        INSERT INTO entry_lines (
            entry_number, customer_code, country_of_origin_code,
            release_date, entered_value, port_of_entry_code
        )
        VALUES (?, 'MHF', 'CN', DATE '2025-03-01', 1000.00, '5301')
        """,
        [target[0]],
    )
    with pytest.raises(AssertionError, match=rf"Expected {EXPECTED_ROW_COUNT} rows"):
        validate_loaded_data(fresh_duckdb_con)


@pytest.mark.unit
def test_validate_fails_on_distinct_entries_drift(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """UPDATE one line of a multi-line entry to a brand-new
    ``entry_number``. Row count stays at ``EXPECTED_ROW_COUNT``, the old
    entry retains its other lines (so it remains distinct), and the new
    entry_number bumps distinct count to ``EXPECTED_DISTINCT_ENTRIES + 1``.
    """
    target = fresh_duckdb_con.execute(
        """
        SELECT entry_number, MIN(invoice_tariff_line)
        FROM entry_lines
        GROUP BY entry_number
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        """
        UPDATE entry_lines
        SET entry_number = '88888888888'
        WHERE entry_number = ? AND invoice_tariff_line = ?
        """,
        [target[0], target[1]],
    )
    with pytest.raises(
        AssertionError,
        match=rf"Expected {EXPECTED_DISTINCT_ENTRIES} distinct entries",
    ):
        validate_loaded_data(fresh_duckdb_con)


@pytest.mark.unit
def test_validate_fails_on_section_301_non_cn_violation(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """UPDATE a non-CN line's ``section_301_code`` to a non-NULL HTS code
    — the Section 301 applicability assertion (KB §Quirk 1) fires.
    """
    target = fresh_duckdb_con.execute(
        """
        SELECT entry_number, invoice_tariff_line FROM entry_lines
        WHERE country_of_origin_code = 'VN' AND section_301_code IS NULL
        LIMIT 1
        """
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        """
        UPDATE entry_lines
        SET section_301_code = '9903.88.15'
        WHERE entry_number = ? AND invoice_tariff_line = ?
        """,
        [target[0], target[1]],
    )
    with pytest.raises(
        AssertionError, match=r"Section 301 code present on \d+ non-CN line"
    ):
        validate_loaded_data(fresh_duckdb_con)


@pytest.mark.unit
def test_validate_fails_on_ieepa_pre_feb_2025_violation(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """UPDATE a pre-Feb-2025 line's ``ieepa_code`` to a non-NULL value —
    the IEEPA applicability assertion (KB §Quirk 2) fires.
    """
    target = fresh_duckdb_con.execute(
        """
        SELECT entry_number, invoice_tariff_line FROM entry_lines
        WHERE release_date < DATE '2025-02-01' AND ieepa_code IS NULL
        LIMIT 1
        """
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        """
        UPDATE entry_lines
        SET ieepa_code = '9903.01.20'
        WHERE entry_number = ? AND invoice_tariff_line = ?
        """,
        [target[0], target[1]],
    )
    with pytest.raises(
        AssertionError, match=r"IEEPA code present on \d+ pre-Feb-2025"
    ):
        validate_loaded_data(fresh_duckdb_con)


@pytest.mark.unit
def test_validate_fails_on_customer_enum_drift(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """UPDATE every line of one entry to a customer_code outside
    ``EXPECTED_CUSTOMERS`` — entries_v.customer_code (via ANY_VALUE)
    deterministically picks the new value, so the distinct set
    includes ``'XXX'``.
    """
    target = fresh_duckdb_con.execute(
        "SELECT entry_number FROM entry_lines LIMIT 1"
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        "UPDATE entry_lines SET customer_code = 'XXX' WHERE entry_number = ?",
        [target[0]],
    )
    with pytest.raises(AssertionError, match=r"Customer enum drift"):
        validate_loaded_data(fresh_duckdb_con)


@pytest.mark.unit
def test_validate_fails_on_country_enum_drift(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """UPDATE one non-CN line's ``country_of_origin_code`` to a code
    outside ``EXPECTED_COUNTRIES`` — the country drift assertion fires.

    Pick a non-CN row whose ``section_301_code`` is NULL so the
    Section 301 assertion stays clean (line-grain check sees every row,
    so even one ``'ZZ'`` row trips the drift).
    """
    target = fresh_duckdb_con.execute(
        """
        SELECT entry_number, invoice_tariff_line FROM entry_lines
        WHERE country_of_origin_code = 'VN' AND section_301_code IS NULL
        LIMIT 1
        """
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        """
        UPDATE entry_lines
        SET country_of_origin_code = 'ZZ'
        WHERE entry_number = ? AND invoice_tariff_line = ?
        """,
        [target[0], target[1]],
    )
    with pytest.raises(AssertionError, match=r"Country enum drift"):
        validate_loaded_data(fresh_duckdb_con)


@pytest.mark.unit
def test_validate_fails_on_port_enum_drift(
    fresh_duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """UPDATE every line of one entry's ``port_of_entry_code`` to a code
    outside ``EXPECTED_PORTS`` — the port drift assertion fires.

    All lines of the entry must change so ANY_VALUE in entries_v
    deterministically surfaces the bad code.
    """
    target = fresh_duckdb_con.execute(
        "SELECT entry_number FROM entry_lines LIMIT 1"
    ).fetchone()
    assert target is not None
    fresh_duckdb_con.execute(
        "UPDATE entry_lines SET port_of_entry_code = '9999' WHERE entry_number = ?",
        [target[0]],
    )
    with pytest.raises(AssertionError, match=r"Port enum drift"):
        validate_loaded_data(fresh_duckdb_con)
