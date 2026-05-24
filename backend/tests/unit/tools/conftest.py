"""Shared fixtures for ``tests/unit/tools/``.

A session-scoped DuckDB connection with the real dataset loaded gives every
tool test a consistent ground-truth substrate. Pattern mirrors
:func:`tests.ground_truth.main` so the tools and the answer-key
generator query the same materialized views.
"""

import duckdb
import pytest

from customs_agent.data.load import load_entries
from customs_agent.data.validation import validate_loaded_data
from customs_agent.data.views import create_views


@pytest.fixture(scope="session")
def duckdb_con() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with entry_lines + views + validation (session-scoped).

    Tools are read-only — sharing one connection across tests in the
    session is safe and shaves boot time off every test.
    """
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)
    return con
