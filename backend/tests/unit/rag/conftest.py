"""Shared fixtures for the ``tests/unit/rag/`` suite.

The retriever tests intentionally MOCK ChromaDB so the unit layer stays
offline and free of OpenAI cost / network coupling (Fork 16's
unit-vs-integration split; see context/08-cicd-and-testing.md).

BM25 is real — it operates over the in-memory chunked corpus and needs
no external state, so there's no reason to fake it.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from rank_bm25 import BM25Okapi

from customs_agent.rag._tokenize import tokenize
from customs_agent.rag.chunker import Chunk, parse_chunks


@pytest.fixture(scope="session")
def chunks() -> list[Chunk]:
    """All chunks parsed from the on-disk knowledge files (session-scoped)."""
    return parse_chunks()


@pytest.fixture(scope="session")
def bm25_index(chunks: list[Chunk]) -> BM25Okapi:
    """Real BM25Okapi over the real corpus; mirrors what build_index.py emits."""
    tokenized = [tokenize(c.text) for c in chunks]
    return BM25Okapi(tokenized)


@dataclass
class FakeChromaCollection:
    """Stand-in for a real ChromaDB ``Collection`` that satisfies the
    retriever's :class:`_ChromaQueryable` protocol.

    Returns a canned list of ``chunk_id`` strings as the semantic-side
    candidate ranking, in the order provided. Records every call for
    assertion in tests that care about the embedding-side argument shape.
    """

    canned_ids: list[str]
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def query(self, query_texts: list[str], n_results: int) -> dict[str, Any]:
        self.call_log.append({"query_texts": query_texts, "n_results": n_results})
        return {"ids": [self.canned_ids[:n_results]]}


@pytest.fixture
def make_fake_chroma() -> Any:
    """Factory fixture: ``make_fake_chroma([id1, id2, ...])`` → collection stub."""
    def _make(canned_ids: list[str]) -> FakeChromaCollection:
        return FakeChromaCollection(canned_ids=list(canned_ids))
    return _make
