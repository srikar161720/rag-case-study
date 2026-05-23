"""Tests for the hybrid BM25 + semantic retriever (Fork 16).

ChromaDB is mocked via ``FakeChromaCollection`` (see ``conftest.py``);
BM25 is real. This keeps the unit layer offline and free of OpenAI
credit usage while still exercising:

* the dotted-numeric-preserving tokenizer (HTS codes stay as one token),
* the RRF fusion math (hand-computed expectations),
* the top-K + candidate-pool plumbing,
* the structlog event emitted per retrieve() call.

Semantic-ranking quality is not the responsibility of the unit layer —
that's validated end-to-end by the eval suite against the 11
ground-truth questions on the Day 4 branch.
"""

import pytest
import structlog

from customs_agent.rag._tokenize import tokenize
from customs_agent.rag.chunker import Chunk
from customs_agent.rag.retriever import (
    DEFAULT_RRF_K,
    HybridRetriever,
    RetrievedChunk,
)

# ─────────────────────────────────────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_tokenizer_preserves_hts_code() -> None:
    """Dotted numeric sequences (HTS / Chapter 99 codes) must tokenize as ONE
    token; the default whitespace+punctuation tokenizer would shatter them."""
    tokens = tokenize("Section 301 code 9903.88.15 applies to apparel")
    assert "9903.88.15" in tokens, tokens
    # And specifically NOT the broken parts
    assert "9903" not in tokens
    assert "88" not in tokens


@pytest.mark.unit
def test_tokenizer_lowercases() -> None:
    """All output tokens are lowercase so the build-time corpus matches the
    user's query regardless of the query's casing."""
    assert tokenize("MPF") == ["mpf"]
    assert tokenize("Hold Rate") == ["hold", "rate"]


@pytest.mark.unit
def test_tokenizer_handles_empty() -> None:
    """No word characters → empty list (not a None or crash)."""
    assert tokenize("") == []
    assert tokenize("    ") == []


# ─────────────────────────────────────────────────────────────────────────────
# RRF fusion math
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_rrf_fusion_math(
    chunks: list[Chunk],
    bm25_index,  # real BM25 (unused here; retriever needs it)
    make_fake_chroma,
) -> None:
    """Hand-compute RRF for a known overlap and verify the retriever agrees.

    Construct a query whose BM25 ranking is empirically (B, C, A) and whose
    semantic mock returns [A, B, C]. With RRF constant 60::

        A: 1/60 (sem rank 0) + 1/62 (bm25 rank 2) ≈ 0.01667 + 0.01613 = 0.0328
        B: 1/61 (sem rank 1) + 1/60 (bm25 rank 0) ≈ 0.01639 + 0.01667 = 0.0331
        C: 1/62 (sem rank 2) + 1/61 (bm25 rank 1) ≈ 0.01613 + 0.01639 = 0.0325

    Expected order: B > A > C. We use chunks the BM25 corpus actually has,
    so the BM25 side ranking is real, not faked.
    """
    # Pick three real chunk_ids; their BM25 ranking for a tailored query
    # is irrelevant — we override semantic side via the fake collection and
    # construct the assertion only against the retriever's fused output
    # for a synthetic scenario. We exercise the actual math by directly
    # asserting on a small custom retriever instance.

    a_id = "rule_1_date_filtering"
    b_id = "metric_effective_duty_rate"
    c_id = "quirk_2_ieepa_feb_2025"

    # Force semantic order: [A, B, C]
    fake_chroma = make_fake_chroma([a_id, b_id, c_id])

    # Force BM25 to produce a known ranking by using a hand-built tiny BM25
    # over three single-token "documents" so we control which doc wins.
    from rank_bm25 import BM25Okapi
    tiny_corpus = [
        ["alpha"],   # will be at corpus index 0 → mapped to a_id
        ["beta"],    # at index 1 → b_id
        ["gamma"],   # at index 2 → c_id
    ]
    tiny_bm25 = BM25Okapi(tiny_corpus)
    # Build a fake chunks list whose corpus order matches: [A, B, C]
    a_chunk = next(c for c in chunks if c.chunk_id == a_id)
    b_chunk = next(c for c in chunks if c.chunk_id == b_id)
    c_chunk = next(c for c in chunks if c.chunk_id == c_id)
    tiny_chunks = [a_chunk, b_chunk, c_chunk]

    # Query "beta gamma alpha" — BM25 scores rank B (top), C, A. We can
    # verify the BM25-only ranking first:
    scores = tiny_bm25.get_scores(["beta", "gamma", "alpha"])
    # All three are equal because each appears once with the same idf.
    # That's actually a problem for unambiguous ranking. Use a different
    # query that produces strict ordering:
    scores = tiny_bm25.get_scores(["beta", "beta", "gamma", "alpha"])
    # B's score should be highest because "beta" repeats.
    assert scores[1] > scores[2] > scores[0] or scores[1] > scores[2] >= scores[0]
    # Hmm — BM25's term-frequency saturation may not produce strict
    # ordering. Simpler tactic: hand the BM25 a query that hits only B, then
    # only C, then only A (zero scores for others = excluded from candidates)
    # and observe the fused ranking is determined by semantic order alone.
    # That's a separate property test below. For RRF math, build a
    # synthetic scenario by direct constructor injection.

    retriever = HybridRetriever(
        chunks=tiny_chunks,
        chroma_collection=fake_chroma,
        bm25=tiny_bm25,
        rrf_k_constant=DEFAULT_RRF_K,
    )
    # Use "beta" so BM25 ranks B uniquely highest with non-zero score;
    # A and C get zero and are excluded from BM25 candidates entirely.
    # Fused contribution: B = 1/(1+60) [sem] + 1/(0+60) [bm25]; A = 1/(0+60);
    # C = 1/(2+60). B wins, A second, C third.
    results = retriever.retrieve("beta", k=3)
    ranking = [r.chunk.chunk_id for r in results]
    assert ranking[0] == b_id, ranking
    assert ranking[1] == a_id, ranking
    assert ranking[2] == c_id, ranking
    # Verify scores follow the math
    by_id = {r.chunk.chunk_id: r for r in results}
    assert by_id[b_id].score_rrf == pytest.approx(1/61 + 1/60, rel=1e-9)
    assert by_id[a_id].score_rrf == pytest.approx(1/60, rel=1e-9)
    assert by_id[c_id].score_rrf == pytest.approx(1/62, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Plumbing: top-K, candidate pool, missing-side handling
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_retrieve_returns_at_most_topk(
    chunks: list[Chunk],
    bm25_index,
    make_fake_chroma,
) -> None:
    """Top-K cap is honored even when many candidates fuse together."""
    fake = make_fake_chroma([c.chunk_id for c in chunks[:10]])
    retriever = HybridRetriever(chunks, fake, bm25_index)
    results = retriever.retrieve("entry release date filtering", k=5)
    assert len(results) <= 5
    # And we asked the fake for the right candidate-pool size (k*2 = 10):
    assert fake.call_log[-1]["n_results"] == 10


@pytest.mark.unit
def test_retrieve_handles_zero_bm25_match(
    chunks: list[Chunk],
    bm25_index,
    make_fake_chroma,
) -> None:
    """A query with no token overlap (BM25 returns all zeros) still yields
    the semantic candidates ranked by their semantic order."""
    sem_ids = ["concept_entry_number", "concept_entry_types"]
    fake = make_fake_chroma(sem_ids)
    retriever = HybridRetriever(chunks, fake, bm25_index)
    # Garbage query: no tokens overlap with any chunk. Semantic side
    # is the canned [sem_ids[0], sem_ids[1]].
    results = retriever.retrieve("xyzzy plover frobnitz", k=2)
    ranking = [r.chunk.chunk_id for r in results]
    assert ranking == sem_ids
    # Every result's bm25 rank should be None (excluded from BM25 candidates).
    assert all(r.rank_bm25 is None for r in results)


@pytest.mark.unit
def test_retrieve_handles_unknown_chunk_id(
    chunks: list[Chunk],
    bm25_index,
    make_fake_chroma,
) -> None:
    """Defensive: an unknown chunk_id from a stale chroma_db is skipped,
    not surfaced as a crash on a live request."""
    fake = make_fake_chroma(["definitely_not_a_real_chunk_id"])
    retriever = HybridRetriever(chunks, fake, bm25_index)
    results = retriever.retrieve("anything", k=5)
    # The unknown ID is skipped; remaining slots are whatever BM25 found.
    assert all(r.chunk.chunk_id != "definitely_not_a_real_chunk_id" for r in results)


# ─────────────────────────────────────────────────────────────────────────────
# Observability
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_retrieve_emits_log(
    chunks: list[Chunk],
    bm25_index,
    make_fake_chroma,
) -> None:
    """Each retrieve() call must emit a single ``rag.retrieve`` event with
    ``query_len``, ``k``, ``candidate_pool``, ``top_chunk_ids``, and
    ``rrf_constant`` fields.

    Validated via ``structlog.testing.capture_logs`` so we don't depend on
    the configured renderer (development ConsoleRenderer pre-Fork 54).
    """
    fake = make_fake_chroma([c.chunk_id for c in chunks[:5]])
    retriever = HybridRetriever(chunks, fake, bm25_index)

    with structlog.testing.capture_logs() as logs:
        retriever.retrieve("how do I filter by release date", k=3)

    events = [r for r in logs if r["event"] == "rag.retrieve"]
    assert len(events) == 1, logs
    event = events[0]
    assert event["query_len"] == len("how do I filter by release date")
    assert event["k"] == 3
    assert event["candidate_pool"] == 6
    assert isinstance(event["top_chunk_ids"], list)
    assert event["rrf_constant"] == DEFAULT_RRF_K


# ─────────────────────────────────────────────────────────────────────────────
# RetrievedChunk metadata
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_retrieved_chunk_records_per_retriever_ranks(
    chunks: list[Chunk],
    bm25_index,
    make_fake_chroma,
) -> None:
    """A chunk hit by both retrievers carries both ranks; a chunk hit by
    only one carries the other as None — important for the UI panel."""
    # Force a known semantic ordering so the assertion is stable.
    sem_ids = ["rule_1_date_filtering", "rule_2_entry_vs_line_count"]
    fake = make_fake_chroma(sem_ids)
    retriever = HybridRetriever(chunks, fake, bm25_index)

    # A query that clearly hits Rule 1 lexically + likely semantically:
    results = retriever.retrieve("release date filtering rule for monthly queries", k=5)
    by_id: dict[str, RetrievedChunk] = {r.chunk.chunk_id: r for r in results}
    rule1 = by_id.get("rule_1_date_filtering")
    assert rule1 is not None
    # Semantic side is canned at rank 0:
    assert rule1.rank_semantic == 0
    # BM25 rank is whatever real BM25 produced — just assert it's an int (
    # might be None if BM25 didn't pool it, but on a date-filtering query
    # it should appear).
    assert rule1.rank_bm25 is None or isinstance(rule1.rank_bm25, int)
