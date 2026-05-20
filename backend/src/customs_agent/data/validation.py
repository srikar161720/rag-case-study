"""Boot-time data validation (Fork 18, 20).

Five hard assertions plus one INFO log against the loaded ``entry_lines``
table and ``entries_v`` / ``entry_lines_v`` views:

1. Row count matches the expected dataset size.
2. Distinct entry count matches.
3. ``section_301_code`` is non-NULL only on CN-origin lines (KB §Quirk 1).
   The CODE column is the applicability signal — the duty column carries
   an explicit 0.00 on non-applicable lines, which is a true value, not
   an absence. See load.py for the data-shape rationale.
4. ``ieepa_code`` is non-NULL only on ``release_date ≥ 2025-02-01`` (KB
   §Quirk 2). Same applicability-via-code pattern as Section 301.
5. ``customer_code`` and ``country_of_origin_code`` enums match the expected sets.

Failing any of these aborts the app at boot. Silently wrong data is worse
than failing fast — the ``/ready`` endpoint returns 503 if this validation
hasn't completed successfully (wired up on the ``feat/fastapi-backend`` branch).

The shell-entry count is informational only — logged at INFO and not
asserted, because zero is expected in the current dataset but the
``include_shell`` filter on tools (Fork 20) remains for forward safety.

Note on structlog: this module uses ``structlog.get_logger()`` directly.
The proper boot configuration (dev/prod renderer split per Fork 54,
secret-shape scrubber processor per Fork 53, request-context binding)
lands on the ``feat/observability-base`` branch. Until then,
``structlog`` falls back to its library default (a console renderer to
stderr), which is correct behavior for the single INFO log emitted here.
"""

import duckdb
import structlog

log = structlog.get_logger()

EXPECTED_ROW_COUNT = 4574
EXPECTED_DISTINCT_ENTRIES = 1200
EXPECTED_CUSTOMERS: frozenset[str] = frozenset({"MHF", "PCA", "SAG"})
EXPECTED_COUNTRIES: frozenset[str] = frozenset({"CN", "VN", "IN", "ID", "BD", "TW", "KR"})


def validate_loaded_data(con: duckdb.DuckDBPyConnection) -> None:
    """Run 5 hard checks + shell-entry info log against the loaded views.

    Aborts via ``AssertionError`` if any check fails. Designed to be called
    once at app startup, after :func:`load_entries` and :func:`create_views`.

    Parameters
    ----------
    con
        An open DuckDB connection with ``entry_lines``, ``entries_v``, and
        ``entry_lines_v`` already materialized.
    """
    # 1. Row count
    row = con.execute("SELECT COUNT(*) FROM entry_lines").fetchone()
    assert row is not None
    n = int(row[0])
    assert n == EXPECTED_ROW_COUNT, (
        f"Expected {EXPECTED_ROW_COUNT} rows in entry_lines, got {n} — has the CSV changed?"
    )

    # 2. Distinct entries
    row = con.execute("SELECT COUNT(DISTINCT entry_number) FROM entry_lines").fetchone()
    assert row is not None
    e = int(row[0])
    assert e == EXPECTED_DISTINCT_ENTRIES, (
        f"Expected {EXPECTED_DISTINCT_ENTRIES} distinct entries, got {e}"
    )

    # 3. Section 301 applicability — code present only on CN-origin lines (KB §Quirk 1).
    #    Note: we check the CODE column, not the duty column. The duty column
    #    is zero-filled on non-CN lines; the code column is the authoritative
    #    applicability signal.
    row = con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE section_301_code IS NOT NULL AND country_of_origin_code != 'CN'
        """
    ).fetchone()
    assert row is not None
    bad_301 = int(row[0])
    assert bad_301 == 0, (
        f"Section 301 code present on {bad_301} non-CN line(s) — KB §Quirk 1 violated"
    )

    # 4. IEEPA applicability — code present only on release_date >= 2025-02-01 (KB §Quirk 2).
    #    Same code-column-is-the-signal pattern as Section 301.
    row = con.execute(
        """
        SELECT COUNT(*) FROM entry_lines
        WHERE ieepa_code IS NOT NULL AND release_date < DATE '2025-02-01'
        """
    ).fetchone()
    assert row is not None
    bad_ieepa = int(row[0])
    assert bad_ieepa == 0, (
        f"IEEPA code present on {bad_ieepa} pre-Feb-2025 line(s) — KB §Quirk 2 violated"
    )

    # 5a. Customer enum drift
    actual_customers = frozenset(
        r[0] for r in con.execute("SELECT DISTINCT customer_code FROM entries_v").fetchall()
    )
    assert actual_customers == EXPECTED_CUSTOMERS, (
        f"Customer enum drift: got {sorted(actual_customers)}, "
        f"expected {sorted(EXPECTED_CUSTOMERS)}"
    )

    # 5b. Country enum drift
    actual_countries = frozenset(
        r[0]
        for r in con.execute(
            "SELECT DISTINCT country_of_origin_code FROM entry_lines_v"
        ).fetchall()
    )
    assert actual_countries == EXPECTED_COUNTRIES, (
        f"Country enum drift: got {sorted(actual_countries)}, "
        f"expected {sorted(EXPECTED_COUNTRIES)}"
    )

    # 6. Shell-entry count — INFO log only (no abort)
    row = con.execute("SELECT COUNT(*) FROM entries_v WHERE is_shell").fetchone()
    assert row is not None
    shells = int(row[0])
    log.info(
        "data.validation.complete",
        rows=n,
        distinct_entries=e,
        shell_entries_detected=shells,
    )
