"""Tests for ``lookup_knowledge`` (Fork 22 — Q10).

The tool is a thin wrapper over the retriever. Tests use a stub
retriever rather than the real ChromaDB-backed one so the unit layer
stays offline and free of OpenAI cost. Real retriever integration is
exercised by the rag retriever tests + the eval suite (Day 4).
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from customs_agent.rag.chunker import Chunk, parse_chunks
from customs_agent.tools.lookup_knowledge import (
    LookupKnowledgeInput,
    lookup_knowledge,
)


# Match the minimal shape of customs_agent.rag.retriever.RetrievedChunk.
@dataclass
class _FakeRetrievedChunk:
    chunk: Chunk
    rank_semantic: int | None = None
    rank_bm25: int | None = None
    score_rrf: float = 0.0


@dataclass
class _StubRetriever:
    """Replays a canned list of chunks; records every retrieve() call."""

    chunks_to_return: list[Chunk]
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def retrieve(self, query: str, k: int = 5) -> list[_FakeRetrievedChunk]:
        self.call_log.append({"query": query, "k": k})
        return [
            _FakeRetrievedChunk(chunk=c, score_rrf=1.0 / (i + 1))
            for i, c in enumerate(self.chunks_to_return[:k])
        ]


@pytest.fixture(scope="module")
def all_chunks() -> list[Chunk]:
    return parse_chunks()


@pytest.mark.unit
def test_lookup_knowledge_returns_chunks_in_retriever_order(
    all_chunks: list[Chunk],
) -> None:
    """No synthesis: output preserves the retriever's ordering exactly."""
    canned = [
        c for c in all_chunks
        if c.chunk_id in {"rule_1_date_filtering", "rule_2_entry_vs_line_count"}
    ]
    stub = _StubRetriever(chunks_to_return=canned)
    result = lookup_knowledge(stub, "any query", top_k=5)
    returned_ids = [row["chunk_id"] for row in result.data]
    assert returned_ids == [c.chunk_id for c in canned]


@pytest.mark.unit
def test_lookup_knowledge_passes_top_k_through(all_chunks: list[Chunk]) -> None:
    stub = _StubRetriever(chunks_to_return=all_chunks[:10])
    lookup_knowledge(stub, "anything", top_k=3)
    assert stub.call_log[-1]["k"] == 3


@pytest.mark.unit
def test_lookup_knowledge_respects_top_k_truncation(
    all_chunks: list[Chunk],
) -> None:
    """If the retriever returns 10 but top_k=3, only 3 reach data."""
    stub = _StubRetriever(chunks_to_return=all_chunks[:10])
    result = lookup_knowledge(stub, "anything", top_k=3)
    assert len(result.data) == 3


@pytest.mark.unit
def test_lookup_knowledge_data_shape(all_chunks: list[Chunk]) -> None:
    """Each row carries exactly 5 keys: chunk_id, doc, section_id,
    section_title, text."""
    stub = _StubRetriever(chunks_to_return=all_chunks[:2])
    result = lookup_knowledge(stub, "x")
    for row in result.data:
        assert set(row.keys()) == {
            "chunk_id", "doc", "section_id", "section_title", "text",
        }


@pytest.mark.unit
def test_lookup_knowledge_meta_records_filters_applied(
    all_chunks: list[Chunk],
) -> None:
    """Sidecar must record the query + top_k for show-work transparency."""
    stub = _StubRetriever(chunks_to_return=all_chunks[:1])
    result = lookup_knowledge(stub, "which date field for monthly?", top_k=5)
    assert result.meta.tool_name == "lookup_knowledge"
    assert result.meta.view_used is None
    assert result.meta.sql_executed is None
    assert result.meta.filters_applied == {
        "query": "which date field for monthly?",
        "top_k": 5,
    }


@pytest.mark.unit
def test_lookup_knowledge_emits_no_citations(all_chunks: list[Chunk]) -> None:
    """The returned chunks ARE the citation source; the sidecar builder
    in the agent loop will convert them. The tool itself attaches no
    extra citations."""
    stub = _StubRetriever(chunks_to_return=all_chunks[:1])
    result = lookup_knowledge(stub, "x")
    assert result.citations == []


@pytest.mark.unit
def test_lookup_knowledge_input_model_validates_query_length() -> None:
    """Empty queries get rejected at the schema boundary."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LookupKnowledgeInput(query="")
    with pytest.raises(ValidationError):
        LookupKnowledgeInput(query="x" * 2001)


@pytest.mark.unit
def test_lookup_knowledge_input_model_top_k_bounds() -> None:
    """top_k bounded to 1..20 — defends against denial-of-service via huge K."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LookupKnowledgeInput(query="x", top_k=0)
    with pytest.raises(ValidationError):
        LookupKnowledgeInput(query="x", top_k=21)
    # in-range values pass
    assert LookupKnowledgeInput(query="x", top_k=1).top_k == 1
    assert LookupKnowledgeInput(query="x", top_k=20).top_k == 20
