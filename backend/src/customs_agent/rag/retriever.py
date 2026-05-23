"""Hybrid BM25 + semantic retriever with Reciprocal Rank Fusion (Fork 16).

Loads the build-time artifacts (``chroma_db/`` + ``bm25.pkl``) produced by
``backend/scripts/build_index.py`` and serves a single ``retrieve(query, k)``
call that:

1. Pulls ``k * 2`` candidates from each retriever:
   * Semantic: ChromaDB collection ``"knowledge"`` (embeddings via OpenAI
     ``text-embedding-3-small``; runtime calls the embedding function once
     per query to embed the user query).
   * Lexical: pickled :class:`rank_bm25.BM25Okapi`, queried with the same
     tokenizer used at build time (:mod:`customs_agent.rag._tokenize`).
2. Fuses the two candidate lists via Reciprocal Rank Fusion::

       fused[chunk_id] = Σ 1 / (rank_in_each_list + 60)

   The constant 60 is the well-known RRF default (Cormack et al., 2009)
   and is intentionally NOT tunable. No score normalization, no
   calibration — just rank-based aggregation that is robust to the
   different score distributions BM25 and cosine similarity produce.
3. Returns the top-``k`` :class:`RetrievedChunk` records with both
   per-retriever ranks and the fused score, so observability hooks
   (Langfuse span on ``feat/langfuse-traces``) and the show-work UI
   panel (Fork 31) can present a faithful retrieval audit trail.

Test-friendliness: ``__init__`` accepts the ChromaDB collection and the
BM25 instance as already-constructed objects. The :meth:`from_artifacts`
classmethod is the production constructor that reads them from disk;
unit tests inject a stub collection to keep the suite offline and
free of network/credit dependencies.
"""

import os
import pickle
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import chromadb
import structlog
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from customs_agent.rag._tokenize import tokenize
from customs_agent.rag.chunker import Chunk

COLLECTION_NAME = "knowledge"
EMBEDDING_MODEL = "text-embedding-3-small"

# RRF constant per Cormack et al. (2009). Spec note in
# context/03-rag-layer.md: "the well-established default — don't tune it."
DEFAULT_RRF_K = 60
DEFAULT_TOP_K = 5

# Match the spec: HTS codes with embedded dots stay as a single token.
# Mirrors customs_agent.rag._tokenize so the BM25 query path is identical
# to the build-time corpus path. Re-exported as a module-level constant
# for tests that want to verify the regex itself.
TOKEN_PATTERN = re.compile(r"\d+\.\d+\.\d+|\w+")

log = structlog.get_logger()


class _ChromaQueryable(Protocol):
    """Minimal interface a Chroma collection must satisfy for the retriever.

    Production: a real :class:`chromadb.api.models.Collection.Collection`.
    Tests: a tiny stub that returns canned ``ids[][...]``. Defining the
    protocol explicitly keeps mypy happy in both cases without importing
    Chroma's internals.
    """

    def query(
        self,
        query_texts: list[str],
        n_results: int,
    ) -> dict[str, Any]: ...  # pragma: no cover - protocol


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One result from a retrieval call, with provenance for the UI panel.

    ``rank_semantic`` / ``rank_bm25`` are zero-indexed — rank 0 means
    "first hit from that retriever". A ``None`` value means the chunk
    didn't make that retriever's top ``candidate_pool``. ``score_rrf`` is
    the fused score used for ordering.
    """
    chunk: Chunk
    rank_semantic: int | None
    rank_bm25: int | None
    score_rrf: float


class HybridRetriever:
    """Hybrid BM25 + semantic retriever with RRF fusion.

    Construct directly when injecting test doubles; use
    :meth:`from_artifacts` for the on-disk artifacts emitted by
    ``scripts/build_index.py``.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        chroma_collection: _ChromaQueryable,
        bm25: BM25Okapi,
        rrf_k_constant: int = DEFAULT_RRF_K,
    ) -> None:
        self._chunks_by_id: dict[str, Chunk] = {c.chunk_id: c for c in chunks}
        # The BM25 corpus index order is the same order chunks were
        # tokenized at build time; we mirror that order here so BM25 score
        # array positions map back to chunk_ids without a separate mapping.
        self._chunk_ids_in_corpus_order: list[str] = [c.chunk_id for c in chunks]
        self._chroma = chroma_collection
        self._bm25 = bm25
        self._rrf_k = rrf_k_constant

    @classmethod
    def from_artifacts(
        cls,
        chunks: list[Chunk],
        chroma_path: Path,
        bm25_path: Path,
        rrf_k_constant: int = DEFAULT_RRF_K,
    ) -> "HybridRetriever":
        """Load the persistent ChromaDB collection and the pickled BM25.

        ``OPENAI_API_KEY`` is read from the environment when the embedding
        function is built. Per Fork 17, the production Docker image ships
        the persisted embeddings; the embedding function is still wired
        up because :py:meth:`chromadb.Collection.query` needs to embed
        the incoming user query at runtime.
        """
        client = chromadb.PersistentClient(path=str(chroma_path))
        # chromadb's published typing is narrower than its actual runtime
        # surface — the assignments below are correct at runtime but trip
        # mypy. Suppressed locally; the unit suite's tiny stub keeps the
        # actual call shape honest.
        collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=OpenAIEmbeddingFunction(  # type: ignore[arg-type]
                api_key=os.environ.get("OPENAI_API_KEY", ""),
                model_name=EMBEDDING_MODEL,
            ),
        )
        bm25: BM25Okapi = pickle.loads(bm25_path.read_bytes())
        return cls(chunks, collection, bm25, rrf_k_constant=rrf_k_constant)  # type: ignore[arg-type]

    def retrieve(
        self,
        query: str,
        k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedChunk]:
        """Return the top ``k`` chunks for ``query``, RRF-fused.

        Parameters
        ----------
        query
            User query text. Tokenized by :func:`customs_agent.rag._tokenize.tokenize`
            for BM25 and passed verbatim to ChromaDB for semantic search.
        k
            Number of results to return. The candidate pool per retriever
            is ``k * 2``.

        Returns
        -------
        list[RetrievedChunk]
            Ordered by fused score, highest first. Length ``≤ k``; can be
            shorter if both retrievers return < ``k`` distinct chunks.
        """
        candidate_pool = k * 2

        # ── Semantic candidates via ChromaDB ─────────────────────────────
        sem_result = self._chroma.query(
            query_texts=[query],
            n_results=candidate_pool,
        )
        # ChromaDB shape: {"ids": [[id, id, ...]], "distances": [[...]], ...}
        # We only need the first (and only) inner list.
        sem_ids: list[str] = list(sem_result.get("ids", [[]])[0])
        sem_rank: dict[str, int] = {cid: rank for rank, cid in enumerate(sem_ids)}

        # ── Lexical candidates via BM25 ──────────────────────────────────
        tokens = tokenize(query)
        bm25_scores = self._bm25.get_scores(tokens)
        # argsort descending; truncate to candidate_pool
        bm25_top_idx = sorted(
            range(len(bm25_scores)),
            key=lambda i: -bm25_scores[i],
        )[:candidate_pool]
        # A BM25 score of exactly 0 means no token overlap — exclude those
        # so a query unrelated to any chunk doesn't pollute the fused list.
        bm25_ids: list[str] = [
            self._chunk_ids_in_corpus_order[i]
            for i in bm25_top_idx
            if bm25_scores[i] > 0
        ]
        bm25_rank: dict[str, int] = {cid: rank for rank, cid in enumerate(bm25_ids)}

        # ── Reciprocal Rank Fusion ───────────────────────────────────────
        fused: dict[str, float] = defaultdict(float)
        for rank, cid in enumerate(sem_ids):
            fused[cid] += 1.0 / (rank + self._rrf_k)
        for rank, cid in enumerate(bm25_ids):
            fused[cid] += 1.0 / (rank + self._rrf_k)

        # ── Pick top-k and assemble result objects ───────────────────────
        top = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
        results: list[RetrievedChunk] = []
        for cid, score in top:
            chunk = self._chunks_by_id.get(cid)
            if chunk is None:
                # Defensive: a chunk_id we don't recognise shouldn't appear,
                # but if it does (stale chroma_db vs. fresh chunker), skip
                # rather than crash a live request.
                continue
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    rank_semantic=sem_rank.get(cid),
                    rank_bm25=bm25_rank.get(cid),
                    score_rrf=score,
                )
            )

        log.info(
            "rag.retrieve",
            query_len=len(query),
            k=k,
            candidate_pool=candidate_pool,
            top_chunk_ids=[r.chunk.chunk_id for r in results],
            rrf_constant=self._rrf_k,
        )
        return results
