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
  dataclasses live in this module so loop tests can construct
  scenarios concisely.
- ``agent_context_factory`` — composes the above into an
  :class:`AgentContext` so loop tests can spin one up in one line.
"""

from dataclasses import dataclass, field
from typing import Any

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
# Fake retriever
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeRetrievedChunk:
    """Mirrors ``customs_agent.rag.retriever.RetrievedChunk`` shape."""
    chunk: Chunk
    rank_semantic: int | None = None
    rank_bm25: int | None = None
    score_rrf: float = 0.0


@dataclass
class FakeRetriever:
    """Replays canned chunks; records every retrieve() call."""

    chunks_to_return: list[Chunk]
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def retrieve(self, query: str, k: int = 5) -> list[FakeRetrievedChunk]:
        self.call_log.append({"query": query, "k": k})
        return [
            FakeRetrievedChunk(
                chunk=c, rank_semantic=i, rank_bm25=None,
                score_rrf=1.0 / (i + 1),
            )
            for i, c in enumerate(self.chunks_to_return[:k])
        ]


@pytest.fixture
def fake_retriever_factory():
    """Factory: ``fake_retriever_factory([chunk1, chunk2, ...])`` → FakeRetriever."""
    def _make(chunks: list[Chunk] | None = None) -> FakeRetriever:
        return FakeRetriever(chunks_to_return=list(chunks or []))
    return _make


# ─────────────────────────────────────────────────────────────────────────────
# Fake Anthropic client
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeTextBlock:
    """Mirrors anthropic's TextBlock surface (the bits the loop reads)."""
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    """Mirrors anthropic's ToolUseBlock surface."""
    name: str
    input: dict[str, Any]
    id: str
    type: str = "tool_use"


@dataclass
class FakeUsage:
    """Mirrors anthropic's Usage object (subset)."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class FakeResponse:
    """Mirrors anthropic's Message response surface."""
    stop_reason: str
    content: list[FakeTextBlock | FakeToolUseBlock]
    usage: FakeUsage | None = None


@dataclass
class _FakeMessagesAPI:
    """Stand-in for ``Anthropic().messages``."""
    parent: "FakeAnthropicClient"

    def create(self, **kwargs: Any) -> FakeResponse:
        self.parent.calls.append(kwargs)
        if not self.parent._queued:
            raise RuntimeError(
                "FakeAnthropicClient: no canned response queued. "
                "Did the test forget to call .queue() enough times?"
            )
        return self.parent._queued.pop(0)


@dataclass
class FakeAnthropicClient:
    """Records every messages.create call; replays queued responses in order.

    Drop-in replacement for ``anthropic.Anthropic()`` for any test that
    exercises run_agent. Set up scenarios via ``.queue(FakeResponse(...))``;
    inspect ``.calls`` to assert on what the loop sent.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)
    _queued: list[FakeResponse] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = _FakeMessagesAPI(parent=self)

    def queue(self, response: FakeResponse) -> None:
        """Add a response to the FIFO replay queue."""
        self._queued.append(response)


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
