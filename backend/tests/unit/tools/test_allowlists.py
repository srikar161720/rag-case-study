"""Drift detection for the view-column frozensets.

PR #5 Copilot Comment 4 follow-up: ``_allowlists.py`` hardcodes
:data:`ENTRIES_V_COLUMNS` and :data:`ENTRY_LINES_V_COLUMNS` to
support the view-compatibility validator on ``QueryEntriesInput``.
The trade-off vs. boot-time ``DESCRIBE`` registration is that the
hardcoded sets can drift from the actual views in ``views.py``.

These tests close that drift gap: they run ``DESCRIBE`` on a live
in-memory DuckDB and assert the frozensets match. Failure here means
``views.py`` grew or lost a column and ``_allowlists.py`` needs to be
updated to match.
"""

import duckdb
import pytest

from customs_agent.tools._allowlists import (
    ENTRIES_V_COLUMNS,
    ENTRIES_V_ONLY,
    ENTRY_LINES_V_COLUMNS,
    ENTRY_LINES_V_ONLY,
)


@pytest.mark.unit
def test_entries_v_columns_match_live_describe(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Drift detector: ENTRIES_V_COLUMNS must match ``DESCRIBE entries_v``."""
    live = frozenset(
        row[0] for row in duckdb_con.execute("DESCRIBE entries_v").fetchall()
    )
    missing_from_constant = live - ENTRIES_V_COLUMNS
    extra_in_constant = ENTRIES_V_COLUMNS - live
    assert not missing_from_constant and not extra_in_constant, (
        f"ENTRIES_V_COLUMNS out of sync with views.py.\n"
        f"  Missing from constant (add to _allowlists.py): "
        f"{sorted(missing_from_constant)}\n"
        f"  Extra in constant (remove from _allowlists.py): "
        f"{sorted(extra_in_constant)}"
    )


@pytest.mark.unit
def test_entry_lines_v_columns_match_live_describe(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Drift detector: ENTRY_LINES_V_COLUMNS must match ``DESCRIBE entry_lines_v``."""
    live = frozenset(
        row[0] for row in duckdb_con.execute("DESCRIBE entry_lines_v").fetchall()
    )
    missing_from_constant = live - ENTRY_LINES_V_COLUMNS
    extra_in_constant = ENTRY_LINES_V_COLUMNS - live
    assert not missing_from_constant and not extra_in_constant, (
        f"ENTRY_LINES_V_COLUMNS out of sync with views.py.\n"
        f"  Missing from constant (add to _allowlists.py): "
        f"{sorted(missing_from_constant)}\n"
        f"  Extra in constant (remove from _allowlists.py): "
        f"{sorted(extra_in_constant)}"
    )


@pytest.mark.unit
def test_only_sets_are_disjoint() -> None:
    """ENTRIES_V_ONLY and ENTRY_LINES_V_ONLY are derived via set
    difference and must not overlap (a column can't be exclusive to
    both views simultaneously)."""
    assert ENTRIES_V_ONLY & ENTRY_LINES_V_ONLY == frozenset()


@pytest.mark.unit
def test_only_sets_correctly_derived() -> None:
    """Sanity: ENTRIES_V_ONLY is exactly ENTRIES_V_COLUMNS minus the shared
    columns. Mirror for ENTRY_LINES_V_ONLY."""
    shared = ENTRIES_V_COLUMNS & ENTRY_LINES_V_COLUMNS
    assert ENTRIES_V_ONLY == ENTRIES_V_COLUMNS - shared
    assert ENTRY_LINES_V_ONLY == ENTRY_LINES_V_COLUMNS - shared


@pytest.mark.unit
def test_known_line_grain_columns_in_lines_only() -> None:
    """Sanity check on the well-known line-grain columns the validator
    relies on for its rejection logic. If these ever leak into entries_v,
    the validator's safety guarantee weakens silently."""
    line_only_must_haves = {
        "country_of_origin_code",  # Quirk 1 — line-grain
        "hts_code",                # HTS is line-grain
        "mid",                     # MID is line-grain
        "entered_value",           # line-level financial column
        "primary_duty",
        "section_301_duty",
        "ieepa_duty",
    }
    missing = line_only_must_haves - ENTRY_LINES_V_ONLY
    assert not missing, (
        f"These columns must remain ENTRY_LINES_V_ONLY for the view-compat "
        f"validator to keep its safety guarantee: {sorted(missing)}"
    )


@pytest.mark.unit
def test_known_entries_grain_columns_in_entries_only() -> None:
    """Symmetric check on entry-grain rollup columns."""
    entries_only_must_haves = {
        "total_entered_value",
        "total_primary_duty",
        "total_section_301_duty",
        "total_ieepa_duty",
        "total_mpf_capped",
        "total_hmf",
        "total_duty_taxes_fees_correct",
        "line_count",
    }
    missing = entries_only_must_haves - ENTRIES_V_ONLY
    assert not missing, (
        f"These columns must remain ENTRIES_V_ONLY for the view-compat "
        f"validator to keep its safety guarantee: {sorted(missing)}"
    )
