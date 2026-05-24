"""Tests for the always-on knowledge block assembler (Fork 15).

The assembler must:
1. Select ONLY chunks whose ``section_kind`` is in
   :data:`ALWAYS_ON_KINDS` (rule / quirk / metric — never anything else).
2. Order them deterministically by ``(section_kind, section_id,
   chunk_id)`` so Anthropic's prompt cache (Fork 55) doesn't silently
   rotate across runs.
3. Render each as a ``### <doc_title> — <section_title>`` header
   followed by the chunk body (with the chunker's DOCUMENT/SECTION
   enrichment prefix stripped — it's redundant noise in the prompt).
4. Produce the exact spec-mandated cardinalities: 6 rules + 4 quirks +
   4 metrics = 14 always-on chunks total.
"""

import pytest

from customs_agent.rag.always_on import (
    ALWAYS_ON_KINDS,
    _extract_body,
    assemble_always_on_block,
)
from customs_agent.rag.chunker import Chunk


@pytest.mark.unit
def test_always_on_kinds_are_the_three_expected() -> None:
    """Closed taxonomy guard — adding a kind here without updating the
    cache-stability story is a bug."""
    assert ALWAYS_ON_KINDS == frozenset({"rule", "quirk", "metric"})


@pytest.mark.unit
def test_block_contains_exactly_14_sections(chunks: list[Chunk]) -> None:
    """6 rules + 4 quirks + 4 metrics = 14 always-on sections."""
    block = assemble_always_on_block(chunks)
    headers = [line for line in block.splitlines() if line.startswith("### ")]
    assert len(headers) == 14, (
        f"Expected 14 always-on sections, got {len(headers)}.\n"
        + "\n".join(headers)
    )


@pytest.mark.unit
def test_block_excludes_non_always_on_kinds(chunks: list[Chunk]) -> None:
    """Concept / duty_program / customer_profile / qbr_section_template /
    column_definition / relationship chunks must NEVER appear."""
    block = assemble_always_on_block(chunks)
    # Concept titles like "Entry Number" / "Bill of Lading" should not be there.
    for forbidden in (
        "Entry Number",      # concept
        "MID",               # concept
        "Tariff Stacking",   # duty_program
        "Pacific Coast Apparel",  # customer_profile
        "Column Definitions",     # column_definition
        "Relationships & Joins",  # relationship
        "QBR Structure",          # qbr_section_template
    ):
        assert forbidden not in block, (
            f"Always-on block leaked non-always-on content: {forbidden!r}"
        )


@pytest.mark.unit
def test_block_is_deterministic(chunks: list[Chunk]) -> None:
    """Stable sort key — same input must produce byte-identical output."""
    a = assemble_always_on_block(chunks)
    b = assemble_always_on_block(list(reversed(chunks)))
    assert a == b, "Assembler is not order-invariant — cache will rotate randomly"


@pytest.mark.unit
def test_block_sort_order_is_kind_then_section(chunks: list[Chunk]) -> None:
    """Per the locked sort key (kind, section_id, chunk_id): alphabetical
    section_kind means metrics → quirks → rules."""
    block = assemble_always_on_block(chunks)
    metric_idx = block.find("Effective Duty Rate")
    quirk_idx  = block.find("Section 301 Fields — China-Only")
    rule_idx   = block.find("Date Filtering")
    assert -1 < metric_idx < quirk_idx < rule_idx, (
        f"Expected metric < quirk < rule order. "
        f"Got positions: metric={metric_idx}, quirk={quirk_idx}, rule={rule_idx}"
    )


@pytest.mark.unit
def test_block_strips_chunker_enrichment_prefix(chunks: list[Chunk]) -> None:
    """The chunker prepends DOCUMENT: / SECTION: lines for embedding
    placement. Those add zero value in the prompt and waste cache tokens
    — the assembler must strip them."""
    block = assemble_always_on_block(chunks)
    assert "DOCUMENT:" not in block, "Chunker enrichment leaked into prompt"
    assert "SECTION: §" not in block, "Chunker SECTION prefix leaked into prompt"


@pytest.mark.unit
def test_block_renders_markdown_headers(chunks: list[Chunk]) -> None:
    """Each section opens with '### <doc_title> — <section_title>'."""
    block = assemble_always_on_block(chunks)
    # Spot-check known headers (use em-dash, matching DOC_TITLES + section_title).
    assert "### Duties, Fees & Tariff Programs — Date Filtering" in block
    assert "### Data Dictionary — Section 301 Fields — China-Only" in block
    assert "### Customer Profiles & QBR Metrics — Effective Duty Rate" in block


@pytest.mark.unit
def test_extract_body_strips_prefix() -> None:
    """Unit-test the helper directly with a synthetic enriched chunk."""
    enriched = (
        "DOCUMENT: foo.txt — Foo\n"
        "SECTION: §1 Bar\n"
        "\n"
        "Body line 1\nBody line 2"
    )
    assert _extract_body(enriched) == "Body line 1\nBody line 2"


@pytest.mark.unit
def test_extract_body_passes_through_when_no_prefix() -> None:
    """Defensive: if the chunker stops adding the prefix, fall back to
    the raw text rather than crashing."""
    plain = "No prefix here.\nJust body content."
    assert _extract_body(plain) == plain
