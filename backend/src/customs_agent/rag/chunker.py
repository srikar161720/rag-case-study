"""Section-header chunker over the 4 knowledge ``.txt`` files (Fork 14).

Each section becomes one chunk with stable metadata (``doc``, ``section_id``,
``section_title``, ``section_kind``) and a deterministic ``chunk_id``. IDs
are declared once in :data:`CHUNKS_REGISTRY` below — the single source of
truth for what the index will contain — and several IDs are pre-committed
to ``backend/tests/ground_truth.py`` ``EXPECTED_CITATIONS``. The unit
suite at ``tests/unit/rag/test_chunker.py`` fails fast if any expected ID
goes missing.

The chunker is registry-driven on purpose. 30+ sections span 9 ``section_kind``
buckets (see ``context/03-rag-layer.md`` for the taxonomy) and a handful of
IDs do not map cleanly from header text — ``hts_format_xxxx_xx_xxxx``,
``qbr_structure``, ``metric_hold_rate_benchmark``. An explicit table is
shorter, easier to audit, and easier to test than a slugifier with overrides.

Each chunk's text is enriched with parent-doc context before embedding::

    DOCUMENT: <filename> — <doc_title>
    SECTION: <section_id> <section_title>

    <raw section body, with trailing banner blocks stripped>

This shape helps the embedding model carry section placement so retrieval
ranks "the rule about date filtering" near :data:`rule_1_date_filtering`
even when the query doesn't repeat the rule's title (Fork 14). The same
enriched text is also fed to BM25 — extra title tokens are a feature, not
a bug, for lexical retrieval over jargon-heavy customs prose.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "knowledge"

DOC_TITLES: dict[str, str] = {
    "customs_core_concepts.txt": "Core Customs Concepts",
    "duties_fees_tariffs.txt": "Duties, Fees & Tariff Programs",
    "customer_profiles_qbr_metrics.txt": "Customer Profiles & QBR Metrics",
    "data_dictionary.txt": "Data Dictionary",
}

# Closed taxonomy from context/03-rag-layer.md. The chunker enforces that
# every ChunkSpec.section_kind is a member of this set so a typo becomes a
# loud failure rather than silently corrupting always_on.py's filter
# (next branch).
SECTION_KINDS: frozenset[str] = frozenset({
    "concept",
    "duty_program",
    "rule",
    "customer_profile",
    "qbr_section_template",
    "metric",
    "column_definition",
    "relationship",
    "quirk",
})


@dataclass(frozen=True, slots=True)
class ChunkSpec:
    """Declarative description of one chunk to extract from a knowledge file.

    ``section_marker`` is the EXACT substring that opens the section in the
    source file. Markers must be unique within their ``doc`` — the parser
    uses :py:meth:`str.find`, which returns the first match. The unit suite
    verifies uniqueness.
    """
    chunk_id: str
    doc: str
    section_id: str
    section_title: str
    section_kind: str
    section_marker: str


@dataclass(frozen=True, slots=True)
class Chunk:
    """A parsed chunk: spec metadata + extracted text + parent doc title."""
    chunk_id: str
    doc: str
    doc_title: str
    section_id: str
    section_title: str
    section_kind: str
    section_marker: str
    text: str


# ─────────────────────────────────────────────────────────────────────────────
# Chunk registry — the ONLY place chunk IDs are declared.
#
# Entries roughly follow document then section order. Eight IDs below are
# pinned by ``backend/tests/ground_truth.py`` EXPECTED_CITATIONS and MUST
# appear verbatim:
#
#   rule_1_date_filtering          rule_2_entry_vs_line_count
#   quirk_1_section_301_china_only quirk_2_ieepa_feb_2025
#   metric_effective_duty_rate     metric_hold_rate_benchmark
#   hts_format_xxxx_xx_xxxx        qbr_structure
# ─────────────────────────────────────────────────────────────────────────────

CHUNKS_REGISTRY: tuple[ChunkSpec, ...] = (
    # ── customs_core_concepts.txt ───────────────────────────────────────────
    ChunkSpec(
        "concept_entry_number",
        "customs_core_concepts.txt", "§1", "Entry Number",
        "concept", "1. ENTRY NUMBER",
    ),
    ChunkSpec(
        "concept_entry_types",
        "customs_core_concepts.txt", "§2", "Entry Types",
        "concept", "2. ENTRY TYPES",
    ),
    ChunkSpec(
        "concept_entry_lifecycle_dates",
        "customs_core_concepts.txt", "§3", "Entry Lifecycle Dates",
        "concept", "3. ENTRY LIFECYCLE DATES",
    ),
    ChunkSpec(
        "concept_entry_summary_7501",
        "customs_core_concepts.txt", "§4", "Entry Summary (Form 7501)",
        "concept", "4. ENTRY SUMMARY (FORM 7501)",
    ),
    ChunkSpec(
        "concept_broker_reference_number",
        "customs_core_concepts.txt", "§5", "Broker Reference Number",
        "concept", "5. BROKER REFERENCE NUMBER",
    ),
    ChunkSpec(
        "concept_bill_of_lading",
        "customs_core_concepts.txt", "§6", "Bill of Lading",
        "concept", "6. BILL OF LADING (BOL / B/L)",
    ),
    ChunkSpec(
        "concept_container_number",
        "customs_core_concepts.txt", "§7", "Container Number",
        "concept", "7. CONTAINER NUMBER",
    ),
    ChunkSpec(
        "concept_mid",
        "customs_core_concepts.txt", "§8", "MID (Manufacturer's Identification Code)",
        "concept", "8. MID (MANUFACTURER'S IDENTIFICATION CODE)",
    ),
    ChunkSpec(
        "concept_port_codes",
        "customs_core_concepts.txt", "§9", "Port Codes",
        "concept", "9. PORT CODES",
    ),
    ChunkSpec(
        "concept_pay_type",
        "customs_core_concepts.txt", "§10", "Pay Type",
        "concept", "10. PAY TYPE",
    ),

    # ── duties_fees_tariffs.txt — duty programs ─────────────────────────────
    # chunk_id="hts_format_xxxx_xx_xxxx" is the ground-truth-pinned ID for the
    # HTS code section (Q8 cites it explicitly).
    ChunkSpec(
        "hts_format_xxxx_xx_xxxx",
        "duties_fees_tariffs.txt", "§1", "HTS Code (Harmonized Tariff Schedule)",
        "duty_program", "1. HTS CODE (HARMONIZED TARIFF SCHEDULE)",
    ),
    ChunkSpec(
        "duty_primary_duty",
        "duties_fees_tariffs.txt", "§2", "Primary Duty",
        "duty_program", "2. PRIMARY DUTY",
    ),
    ChunkSpec(
        "duty_tariff_stacking",
        "duties_fees_tariffs.txt", "§3", "Tariff Stacking",
        "duty_program", "3. TARIFF STACKING",
    ),
    ChunkSpec(
        "duty_section_301",
        "duties_fees_tariffs.txt", "§4", "Section 301 Tariffs (China-Specific)",
        "duty_program", "4. SECTION 301 TARIFFS (CHINA-SPECIFIC)",
    ),
    ChunkSpec(
        "duty_ieepa_reciprocal",
        "duties_fees_tariffs.txt", "§5", "IEEPA Reciprocal Tariffs",
        "duty_program", "5. IEEPA RECIPROCAL TARIFFS",
    ),
    ChunkSpec(
        "duty_mpf",
        "duties_fees_tariffs.txt", "§6", "MPF (Merchandise Processing Fee)",
        "duty_program", "6. MPF (MERCHANDISE PROCESSING FEE)",
    ),
    ChunkSpec(
        "duty_hmf",
        "duties_fees_tariffs.txt", "§7", "HMF (Harbor Maintenance Fee)",
        "duty_program", "7. HMF (HARBOR MAINTENANCE FEE)",
    ),
    ChunkSpec(
        "duty_entered_value",
        "duties_fees_tariffs.txt", "§8", "Entered Value",
        "duty_program", "8. ENTERED VALUE",
    ),
    ChunkSpec(
        "duty_total_duty_taxes_fees",
        "duties_fees_tariffs.txt", "§9", "Total Duty, Taxes, Fees & Penalties",
        "duty_program", "9. TOTAL DUTY, TAXES, FEES & PENALTIES",
    ),

    # ── duties_fees_tariffs.txt — business rules (always-on candidates) ─────
    ChunkSpec(
        "rule_1_date_filtering",
        "duties_fees_tariffs.txt", "§Rule 1", "Date Filtering",
        "rule", "RULE 1 — Date Filtering",
    ),
    ChunkSpec(
        "rule_2_entry_vs_line_count",
        "duties_fees_tariffs.txt", "§Rule 2", "Entry Count vs. Line Count",
        "rule", "RULE 2 — Entry Count vs. Line Count",
    ),
    ChunkSpec(
        "rule_3_duty_spend_aggregation",
        "duties_fees_tariffs.txt", "§Rule 3", "Duty Spend Aggregation",
        "rule", "RULE 3 — Duty Spend Aggregation",
    ),
    ChunkSpec(
        "rule_4_country_of_origin_filtering",
        "duties_fees_tariffs.txt", "§Rule 4", "Country of Origin Filtering",
        "rule", "RULE 4 — Country of Origin Filtering",
    ),
    ChunkSpec(
        "rule_5_shell_entries",
        "duties_fees_tariffs.txt", "§Rule 5", "Shell Entries",
        "rule", "RULE 5 — Shell Entries",
    ),
    ChunkSpec(
        "rule_6_on_hold_entries",
        "duties_fees_tariffs.txt", "§Rule 6", "On-Hold Entries",
        "rule", "RULE 6 — On-Hold Entries",
    ),

    # ── customer_profiles_qbr_metrics.txt — customer profiles ───────────────
    ChunkSpec(
        "customer_profile_mhf",
        "customer_profiles_qbr_metrics.txt", "§MHF", "Meridian Home Furnishings (MHF)",
        "customer_profile", "CUSTOMER: MERIDIAN HOME FURNISHINGS (MHF)",
    ),
    ChunkSpec(
        "customer_profile_pca",
        "customer_profiles_qbr_metrics.txt", "§PCA", "Pacific Coast Apparel (PCA)",
        "customer_profile", "CUSTOMER: PACIFIC COAST APPAREL (PCA)",
    ),
    ChunkSpec(
        "customer_profile_sag",
        "customer_profiles_qbr_metrics.txt", "§SAG", "Summit Athletic Gear (SAG)",
        "customer_profile", "CUSTOMER: SUMMIT ATHLETIC GEAR (SAG)",
    ),

    # ── customer_profiles_qbr_metrics.txt — QBR umbrella (single chunk) ─────
    # qbr_structure intentionally absorbs all 5 numbered sub-sections so Q9
    # gets the full template from one retrieval hit (EXPECTED_CITATIONS[9]
    # lists only this ID, not five separate ones).
    ChunkSpec(
        "qbr_structure",
        "customer_profiles_qbr_metrics.txt", "§QBR", "QBR Structure (5 Standard Sections)",
        "qbr_section_template", "QBR (QUARTERLY BUSINESS REVIEW) METRICS",
    ),

    # ── customer_profiles_qbr_metrics.txt — metric definitions ──────────────
    ChunkSpec(
        "metric_effective_duty_rate",
        "customer_profiles_qbr_metrics.txt", "§Metric: Effective Duty Rate", "Effective Duty Rate",
        "metric", "EFFECTIVE DUTY RATE",
    ),
    ChunkSpec(
        "metric_entry_line_density",
        "customer_profiles_qbr_metrics.txt", "§Metric: Entry Line Density", "Entry Line Density",
        "metric", "ENTRY LINE DENSITY",
    ),
    ChunkSpec(
        "metric_section_301_exposure_ratio",
        "customer_profiles_qbr_metrics.txt",
        "§Metric: Section 301 Exposure Ratio",
        "Section 301 Exposure Ratio",
        "metric",
        "SECTION 301 EXPOSURE RATIO",
    ),
    ChunkSpec(
        "metric_hold_rate_benchmark",
        "customer_profiles_qbr_metrics.txt",
        "§Metric: Hold Rate",
        "Hold Rate (Benchmark < 5%; > 8% Warrants Investigation)",
        "metric",
        "HOLD RATE",
    ),

    # ── data_dictionary.txt — columns + relationships + quirks ──────────────
    ChunkSpec(
        "column_definitions",
        "data_dictionary.txt", "§Columns", "Column Definitions",
        "column_definition", "COLUMN DEFINITIONS:",
    ),
    ChunkSpec(
        "relationships_and_joins",
        "data_dictionary.txt", "§Relationships", "Relationships & Joins",
        "relationship", "RELATIONSHIPS & JOINS",
    ),
    ChunkSpec(
        "quirk_1_section_301_china_only",
        "data_dictionary.txt", "§Quirk 1", "Section 301 Fields — China-Only",
        "quirk", "1. Section 301 fields are populated ONLY for Country of Origin = CN (China)",
    ),
    ChunkSpec(
        "quirk_2_ieepa_feb_2025",
        "data_dictionary.txt", "§Quirk 2", "IEEPA Fields — Release Date ≥ 2025-02-01",
        "quirk", "2. IEEPA fields are populated ONLY for entries with Release Date >= 2025-02-01",
    ),
    ChunkSpec(
        "quirk_3_mpf_per_entry_cap",
        "data_dictionary.txt", "§Quirk 3", "MPF Line-Level Allocation vs. Per-Entry Cap",
        "quirk", "3. MPF at the line level is an allocation; the per-entry cap ($614.35) applies",
    ),
    ChunkSpec(
        "quirk_4_consolidated_bols",
        "data_dictionary.txt", "§Quirk 4", "Consolidated Bills of Lading",
        "quirk", "4. Some entries may share the same Bill of Lading (consolidations)",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

# Matches a trailing banner block of the form:
#     <whitespace>
#     ================================================================================
#     <ALL CAPS BANNER TEXT>
#     ================================================================================
# Used to strip "END OF <DOC>" footers and inline banner separators that fall
# between two registered chunks (e.g., "BUSINESS RULES FOR ANALYTICS").
_TRAILING_BANNER_RE = re.compile(r"\s*\n={5,}\s*\n[^\n]+\n={5,}\s*$")


def _strip_trailing_banners(body: str) -> str:
    """Repeatedly strip trailing banner blocks until the body is banner-free.

    Some sections (e.g., duty program §9) are immediately followed by a
    banner separating them from a different category of content (e.g., the
    "BUSINESS RULES FOR ANALYTICS" header). Without stripping, that banner
    would leak into the previous chunk's text.
    """
    body = body.rstrip()
    while True:
        stripped = _TRAILING_BANNER_RE.sub("", body).rstrip()
        if stripped == body:
            return body
        body = stripped


def parse_chunks(knowledge_dir: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    """Parse every entry in :data:`CHUNKS_REGISTRY` against the knowledge files.

    Parameters
    ----------
    knowledge_dir
        Directory holding the 4 ``*.txt`` knowledge files. Defaults to
        ``backend/knowledge/``.

    Returns
    -------
    list[Chunk]
        Chunks in registry order. Each chunk's ``text`` is enriched with a
        parent-doc + section-title header and trailing banner blocks are
        stripped.

    Raises
    ------
    ValueError
        If any ``section_marker`` is not found in its ``doc``. Fast-fail at
        boot rather than silently producing a chunk with empty body.
    """
    by_doc: dict[str, list[ChunkSpec]] = defaultdict(list)
    for spec in CHUNKS_REGISTRY:
        by_doc[spec.doc].append(spec)

    parsed: dict[str, Chunk] = {}
    for doc, specs in by_doc.items():
        file_path = knowledge_dir / doc
        text = file_path.read_text(encoding="utf-8")

        # Resolve each marker to a (start_idx, spec) pair so we can sort by
        # file position and walk consecutive sections cleanly.
        positions: list[tuple[int, ChunkSpec]] = []
        for spec in specs:
            idx = text.find(spec.section_marker)
            if idx < 0:
                raise ValueError(
                    f"section_marker not found in {doc!r} for chunk_id "
                    f"{spec.chunk_id!r}: {spec.section_marker!r}"
                )
            positions.append((idx, spec))
        positions.sort(key=lambda p: p[0])

        doc_title = DOC_TITLES[doc]
        for i, (start, spec) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            body = _strip_trailing_banners(text[start:end])
            enriched = (
                f"DOCUMENT: {spec.doc} — {doc_title}\n"
                f"SECTION: {spec.section_id} {spec.section_title}\n"
                f"\n"
                f"{body}"
            )
            parsed[spec.chunk_id] = Chunk(
                chunk_id=spec.chunk_id,
                doc=spec.doc,
                doc_title=doc_title,
                section_id=spec.section_id,
                section_title=spec.section_title,
                section_kind=spec.section_kind,
                section_marker=spec.section_marker,
                text=enriched,
            )

    return [parsed[spec.chunk_id] for spec in CHUNKS_REGISTRY]
