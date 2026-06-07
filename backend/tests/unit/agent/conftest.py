"""Shared fixtures for ``tests/unit/agent/``.

Provides:

- ``duckdb_con`` — in-memory DuckDB with the dataset loaded + views
  materialized. Duplicated here (rather than hoisted to a parent
  conftest) to keep the per-directory fixtures self-contained.
- ``fake_retriever`` — a stub satisfying the
  :class:`customs_agent.rag.retriever.HybridRetriever` ``retrieve``
  surface; tests parameterize the canned chunks it returns.
- ``fake_anthropic_client`` — a stub for ``anthropic.Anthropic`` with
  a ``.messages.create`` method that records every call and pops
  queued ``FakeResponse`` objects. The matching FakeResponse + block
  dataclasses live in :mod:`tests._fakes` (extracted on
  ``feat/fastapi-backend`` so the integration suite at
  ``tests/integration/`` can reuse the exact same fakes without a
  cross-subdir conftest import).
- ``agent_context_factory`` — composes the above into an
  :class:`AgentContext` so loop tests can spin one up in one line.
"""

import duckdb
import pytest

from customs_agent.agent.bootstrap import (
    AgentContext,
    build_tool_definitions,
    compute_always_on_chunk_ids,
)
from customs_agent.data.load import load_entries
from customs_agent.data.validation import validate_loaded_data
from customs_agent.data.views import create_views
from customs_agent.rag.chunker import Chunk
from tests._fakes import (
    FakeAnthropicClient,
    FakeResponse,
    FakeRetrievedChunk,
    FakeRetriever,
    FakeTextBlock,
    FakeToolUseBlock,
    FakeUsage,
)

# Re-export so existing tests' ``from tests.unit.agent.conftest import
# FakeResponse, ...`` style imports continue to work unchanged.
__all__ = [
    "FakeAnthropicClient",
    "FakeResponse",
    "FakeRetrievedChunk",
    "FakeRetriever",
    "FakeTextBlock",
    "FakeToolUseBlock",
    "FakeUsage",
]

# ─────────────────────────────────────────────────────────────────────────────
# DuckDB session fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def duckdb_con() -> duckdb.DuckDBPyConnection:
    """Read-only in-memory DuckDB with entry_lines + views + validation."""
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)
    return con


# ─────────────────────────────────────────────────────────────────────────────
# Fake retriever — dataclasses live in tests/_fakes.py; factory fixture below
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_retriever_factory():
    """Factory: ``fake_retriever_factory([chunk1, chunk2, ...])`` → FakeRetriever."""
    def _make(chunks: list[Chunk] | None = None) -> FakeRetriever:
        return FakeRetriever(chunks_to_return=list(chunks or []))
    return _make


# ─────────────────────────────────────────────────────────────────────────────
# Fake Anthropic client — dataclasses live in tests/_fakes.py; fixture below
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_anthropic_client() -> FakeAnthropicClient:
    """Fresh empty FakeAnthropicClient per test."""
    return FakeAnthropicClient()


# ─────────────────────────────────────────────────────────────────────────────
# Agent context factory
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def agent_context_factory(
    duckdb_con: duckdb.DuckDBPyConnection,
    fake_anthropic_client: FakeAnthropicClient,
    fake_retriever_factory,
):
    """Factory: ``agent_context_factory(chunks=[...])`` → AgentContext.

    Real DuckDB + real bootstrap (tool defs built from live DESCRIBE) +
    fake retriever + fake Anthropic client.
    """
    def _make(retrieved_chunks: list[Chunk] | None = None) -> AgentContext:
        return AgentContext(
            con=duckdb_con,
            retriever=fake_retriever_factory(retrieved_chunks or []),  # type: ignore[arg-type]
            client=fake_anthropic_client,  # type: ignore[arg-type]
            tool_definitions=build_tool_definitions(duckdb_con),
            always_on_chunk_ids=compute_always_on_chunk_ids(),
        )
    return _make
