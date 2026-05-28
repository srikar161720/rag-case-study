"""Shared fixtures for ``tests/unit/data/``.

Two fixtures, picked by mutation discipline:

- :func:`duckdb_con` (session-scoped) — load + create_views + validate.
  Use for read-only assertions. Sharing one connection across the
  session amortizes the CSV parse and view materialization.
- :func:`fresh_duckdb_con` (function-scoped) — load + create_views only.
  Use whenever a test needs to ``INSERT`` / ``UPDATE`` / ``DELETE`` on
  ``entry_lines`` and re-run ``validate_loaded_data`` to verify the
  negative branch of an assertion. Function scope keeps the mutations
  hermetic so later tests aren't polluted.

Mirrors the per-subdir conftest pattern in :mod:`tests.unit.tools` and
:mod:`tests.unit.agent`.
"""

import duckdb
import pytest

from customs_agent.data.load import load_entries
from customs_agent.data.validation import validate_loaded_data
from customs_agent.data.views import create_views


@pytest.fixture(scope="session")
def duckdb_con() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with entry_lines + views + validation (session-scoped).

    Tests using this fixture MUST NOT mutate the connection — use
    :func:`fresh_duckdb_con` for any test that touches DML.
    """
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)
    return con


@pytest.fixture
def fresh_duckdb_con() -> duckdb.DuckDBPyConnection:
    """Function-scoped DuckDB with entry_lines + views (no validation yet).

    Validation is intentionally skipped so callers can call
    :func:`validate_loaded_data` themselves — typically inside a
    :func:`pytest.raises` block after mutating the underlying table to
    violate a specific invariant. DuckDB's views are logical
    (unmaterialized), so mutations on ``entry_lines`` reflect in
    ``entries_v`` / ``entry_lines_v`` automatically without a re-create.
    """
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    return con
