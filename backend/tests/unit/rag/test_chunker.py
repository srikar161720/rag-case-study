"""Tests for the section-header chunker (Fork 14).

The most important test in this file is
:func:`test_all_expected_citation_ids_present` — it enforces the hard
contract between the chunker (this branch, ``feat/rag-pipeline``) and
the eval suite (Day 4, ``feat/remaining-tools-and-eval``) that every
``chunk_id`` declared in ``backend/tests/ground_truth.py`` is actually
produced. A failure here means the eval suite will silently fail to
locate the expected citation chunks downstream.
"""

import pytest

from customs_agent.rag.chunker import (
    CHUNKS_REGISTRY,
    SECTION_KINDS,
    Chunk,
)
from tests.ground_truth import EXPECTED_CITATIONS


@pytest.mark.unit
def test_parse_chunks_returns_nonempty(chunks: list[Chunk]) -> None:
    """The corpus should be at least the size of the registered chunk list."""
    assert len(chunks) == len(CHUNKS_REGISTRY)
    assert len(chunks) >= 25, (
        "Chunker emitted fewer than 25 chunks — registry may be incomplete."
    )


@pytest.mark.unit
def test_all_expected_citation_ids_present(chunks: list[Chunk]) -> None:
    """Hard contract: every chunk_id ground_truth.py cites must exist.

    Failing this test means the chunker drifted from the eval ground
    truth. Fix the chunker registry rather than the ground truth — the
    ground truth is the authoritative answer key.
    """
    chunk_ids = {c.chunk_id for c in chunks}
    required: set[str] = set()
    for citation_list in EXPECTED_CITATIONS.values():
        required.update(citation_list)
    missing = required - chunk_ids
    assert not missing, (
        f"Chunker is missing required chunk_ids from ground_truth.py "
        f"EXPECTED_CITATIONS: {sorted(missing)}"
    )


@pytest.mark.unit
def test_chunk_ids_are_unique(chunks: list[Chunk]) -> None:
    """No duplicate IDs — ChromaDB and the retriever's lookup map both
    rely on uniqueness."""
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids)), (
        f"Duplicate chunk_ids: {sorted(i for i in ids if ids.count(i) > 1)}"
    )


@pytest.mark.unit
def test_section_kinds_in_taxonomy(chunks: list[Chunk]) -> None:
    """Every chunk's section_kind must be in the closed taxonomy.

    Catches typos like 'rules' → 'rule' that would silently break
    always_on.py's filter on the next branch.
    """
    bad = [c for c in chunks if c.section_kind not in SECTION_KINDS]
    assert not bad, (
        "Out-of-taxonomy section_kinds: "
        + ", ".join(f"{c.chunk_id}={c.section_kind!r}" for c in bad)
    )


@pytest.mark.unit
def test_always_on_kinds_have_expected_counts(chunks: list[Chunk]) -> None:
    """The three always-on kinds must hit the spec'd cardinalities.

    Per context/03-rag-layer.md §Always-On Context: 6 rules + 4 quirks
    + 4 metrics. A miscount means a Business Rule or Quirk slipped out
    of the registry — those are universal preconditions; missing one
    tanks accuracy on every Tier 1-4 question.
    """
    counts: dict[str, int] = {"rule": 0, "quirk": 0, "metric": 0}
    for c in chunks:
        if c.section_kind in counts:
            counts[c.section_kind] += 1
    assert counts == {"rule": 6, "quirk": 4, "metric": 4}, counts


@pytest.mark.unit
def test_chunk_text_includes_doc_and_section_header(chunks: list[Chunk]) -> None:
    """Every enriched chunk text must lead with DOCUMENT: / SECTION: lines.

    The enrichment carries section placement into the embedding so
    semantic ranking captures 'rule about date filtering' near
    rule_1_date_filtering even when the query doesn't repeat the title.
    """
    for c in chunks:
        head = c.text[:200]
        assert head.startswith(f"DOCUMENT: {c.doc}"), c.chunk_id
        assert f"SECTION: {c.section_id} {c.section_title}" in head, c.chunk_id


@pytest.mark.unit
def test_marker_uniqueness_within_each_doc(chunks: list[Chunk]) -> None:
    """Each section_marker must appear exactly once in its source file.

    The parser uses str.find() which returns the FIRST match — a duplicate
    marker would silently truncate the wrong section. This is a structural
    invariant of the knowledge files + the registry, worth a guard.
    """
    from collections import defaultdict
    from pathlib import Path

    from customs_agent.rag.chunker import KNOWLEDGE_DIR

    by_doc: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        by_doc[c.doc].append(c.section_marker)

    for doc, markers in by_doc.items():
        text = (Path(KNOWLEDGE_DIR) / doc).read_text(encoding="utf-8")
        for marker in markers:
            occurrences = text.count(marker)
            assert occurrences == 1, (
                f"section_marker {marker!r} appears {occurrences}x in {doc} "
                f"(must be exactly 1)"
            )
