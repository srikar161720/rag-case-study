"""Hermetic unit tests for the EVALUATION.md generator (G5).

Verifies the pure markdown-assembly functions in
``scripts/generate_evaluation_md.py`` against synthetic graded records —
no network, no real LLM. Critically, asserts the run-metadata table emits
the ``PROMPT_VERSION`` row in the exact backtick format the ci.yml
``evaluation-freshness`` grep depends on.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from customs_agent.agent.contracts import (
    ChatResponse,
    Citation,
    ResponseMeta,
    ToolCallTrace,
)
from customs_agent.agent.prompt import PROMPT_VERSION
from scripts.generate_evaluation_md import (
    build_evaluation_md,
    build_per_question_table,
    build_run_metadata,
    build_summary,
)
from tests.eval._grading import grade_question

pytestmark = pytest.mark.unit


def _meta(
    latency: int = 1400, in_tok: int = 4521, cached: int = 3502, out_tok: int = 320
) -> ResponseMeta:
    return ResponseMeta(
        request_id="r",
        prompt_version=PROMPT_VERSION,
        model="claude-sonnet-4-6",
        embedding_model="text-embedding-3-small",
        temperature=0.0,
        iterations_used=2,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cached_input_tokens=cached,
        total_latency_ms=latency,
    )


def _tool(name: str, result: dict[str, Any], args: dict[str, Any] | None = None) -> ToolCallTrace:
    return ToolCallTrace(
        id=2,
        name=name,
        args=args or {},
        result=result,
        sql_executed="SELECT COUNT(*) FROM entries_v WHERE customer_code = ?",
        shell_entries_excluded=0,
        rows_inspected=65,
        latency_ms=12,
    )


def _record(qid: int = 1) -> dict[str, Any]:
    question = {
        "id": qid,
        "tier": 1,
        "query": "How many entries for PCA in January 2025?",
        "answer": {"entry_count": 65},
        "tolerance": {"entry_count": 0},
        "expected_phrases": [],
        "expected_citations": ["rule_1_date_filtering"],
        "expected_tool_name": "query_entries",
        "expected_tool_args_partial": {"filters": {"customer_code": "PCA"}},
    }
    response = ChatResponse(
        answer="Pacific Coast Apparel filed **65 entries** in January 2025 [1].",
        knowledge_citations=[
            Citation(
                id=1, doc="d.txt", section="§Rule 1", chunk_id="rule_1_date_filtering", snippet="s"
            )
        ],
        tool_calls=[
            _tool(
                "query_entries",
                {"value": [{"entry_count": 65}]},
                args={"filters": {"customer_code": "PCA", "release_year_month": "2025-01"}},
            )
        ],
        refused=False,
        meta=_meta(),
    )
    result = grade_question(question, response)
    return {"question": question, "response": response, "result": result}


_GT = {"dataset_sha256": "abc123def456"}
_MANIFEST = {"built_at": "2026-06-06T00:00:00Z"}


def test_run_metadata_prompt_version_matches_freshness_grep() -> None:
    """The ci.yml evaluation-freshness check greps the version with
    ``\\`PROMPT_VERSION\\`[^\\`]*\\`\\K[^\\`]+`` — assert that pattern extracts
    the live PROMPT_VERSION from the generated table."""
    md = build_run_metadata(
        _GT, _MANIFEST, "https://b.fly.dev", "https://f.vercel.app", "2026-06-06T00:00:00Z"
    )
    match = re.search(r"`PROMPT_VERSION`[^`]*`([^`]+)`", md)
    assert match is not None
    assert match.group(1) == PROMPT_VERSION


def test_run_metadata_includes_models_and_sha() -> None:
    md = build_run_metadata(_GT, _MANIFEST, "https://b.fly.dev", "", "2026-06-06T00:00:00Z")
    assert "claude-sonnet-4-6" in md
    assert "gpt-4o-mini" in md
    assert "abc123def456" in md
    assert "https://b.fly.dev" in md


def test_summary_counts_pass_and_cache() -> None:
    records = [_record(1), _record(2)]
    md = build_summary(records)
    assert "Questions evaluated | 2/2" in md
    # Both synthetic records pass correctness; cache % = 3502/4521 ≈ 77%.
    assert "77%" in md


def test_per_question_table_has_a_row_per_record() -> None:
    md = build_per_question_table([_record(1), _record(2)])
    assert "| 1 | T1 |" in md
    assert "| 2 | T1 |" in md
    assert "`query_entries`" in md


def test_full_document_assembles_all_sections() -> None:
    md = build_evaluation_md(
        [_record(1)],
        _GT,
        _MANIFEST,
        "https://b.fly.dev",
        "https://f.vercel.app",
        "2026-06-06T00:00:00Z",
    )
    for heading in (
        "# EVALUATION.md",
        "## Run Metadata",
        "## Summary",
        "## Per-Question Results",
        "## Detailed Results",
        "## Self-Assessment",
    ):
        assert heading in md
    # Detailed section quotes the agent's answer + shows the SQL excerpt.
    assert "Pacific Coast Apparel filed" in md
    assert "passed all 1 questions" in md
