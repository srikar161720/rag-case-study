"""Fixtures for the real-LLM eval suite (Fork 45 Layer 3).

These tests call the REAL agent against the REAL Anthropic + OpenAI APIs
— they cost money and are excluded from ``make test`` (path-scoped to
``tests/unit tests/integration``). They run via ``make eval`` and the
``eval.yml`` workflow.

Safety: the suite SKIPS (never fails) unless real API keys are present
and the RAG index is built. The root ``tests/conftest.py`` seeds
``test-…`` placeholder keys via ``setdefault``; a real run supplies the
keys through the environment (CI secrets / ``export`` per the
EVALUATION.md reproducibility block), which take precedence. Anything
starting with ``test-`` is treated as a placeholder → skip.

Fixtures:

- ``ground_truth`` — parsed ``ground_truth.json`` with a SHA-256 drift
  guard against the source CSV (Fork 43): if the data changed since the
  answer key was generated, fail fast with a regenerate hint.
- ``agent_client`` — session-scoped real :class:`AgentContext` (DuckDB +
  hybrid retriever from artifacts + Anthropic client), exposing
  ``.ask(query) -> ChatResponse``. Booted once so the prompt cache stays
  warm across all questions (Fork 55).
- ``eval_results`` — session accumulator; on teardown writes
  ``REPORT.md`` + ``.last-result.json`` for the workflow.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import pytest

from customs_agent.agent.bootstrap import build_agent_context
from customs_agent.agent.contracts import ChatResponse
from customs_agent.agent.loop import AgentLoopSettings, run_agent
from customs_agent.config import settings
from customs_agent.data.load import CSV_PATH, load_entries
from customs_agent.data.validation import validate_loaded_data
from customs_agent.data.views import create_views
from customs_agent.rag.chunker import parse_chunks
from customs_agent.rag.retriever import HybridRetriever
from tests.ground_truth import OUTPUT_PATH as GROUND_TRUTH_PATH

EVAL_DIR = Path(__file__).resolve().parent

# Mirror main.py's artifact resolution: Docker bakes them at /app; locally
# they live under backend/ (parents[2] of this file = backend/).
_DOCKER_ROOT = Path("/app")
_LOCAL_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_ROOT = _DOCKER_ROOT if (_DOCKER_ROOT / "chroma_db").exists() else _LOCAL_ROOT


def _skip_reason() -> str | None:
    """Why the eval suite can't run here (or None if it can)."""
    if settings.anthropic_api_key.startswith("test-"):
        return "ANTHROPIC_API_KEY is a test placeholder — export a real key to run eval"
    if settings.openai_api_key.startswith("test-"):
        return "OPENAI_API_KEY is a test placeholder — needed for query embeddings + Q9 judge"
    if not (_ARTIFACT_ROOT / "chroma_db").exists() or not (_ARTIFACT_ROOT / "bm25.pkl").exists():
        return f"RAG index artifacts missing under {_ARTIFACT_ROOT} — run `make build-index`"
    return None


def load_ground_truth_questions() -> list[dict[str, Any]]:
    """Question list for parametrization (read at collection time, before
    fixtures run; the SHA drift guard lives in the ``ground_truth``
    fixture, which ``agent_client`` depends on)."""
    return json.loads(GROUND_TRUTH_PATH.read_text())["questions"]


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, Any]:
    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    actual = sha256(CSV_PATH.read_bytes()).hexdigest()
    if gt["dataset_sha256"] != actual:
        pytest.fail(
            "Dataset drifted since the ground truth was generated.\n"
            f"  Fixture SHA: {gt['dataset_sha256'][:12]}…\n"
            f"  Live    SHA: {actual[:12]}…\n"
            "  Regenerate: make ground-truth"
        )
    return gt


@dataclass
class _AgentClient:
    """Thin ``.ask(query)`` wrapper around the real agent loop."""

    ctx: Any
    loop_settings: AgentLoopSettings

    def ask(self, query: str) -> ChatResponse:
        return run_agent(
            self.ctx,
            user_message=query,
            history=[],
            request_id=f"eval-{uuid.uuid4()}",
            settings=self.loop_settings,
        )


@pytest.fixture(scope="session")
def agent_client(ground_truth: dict[str, Any]) -> _AgentClient:
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)

    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)

    import os

    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    retriever = HybridRetriever.from_artifacts(
        chunks=parse_chunks(),
        chroma_path=_ARTIFACT_ROOT / "chroma_db",
        bm25_path=_ARTIFACT_ROOT / "bm25.pkl",
    )
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    ctx = build_agent_context(con, retriever, client)
    loop_settings = AgentLoopSettings(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_iterations=settings.agent_max_iterations,
        max_input_tokens=settings.agent_max_input_tokens_per_turn,
        max_output_tokens=settings.agent_max_output_tokens_per_turn,
        embedding_model=settings.llm_embedding_model,
    )
    return _AgentClient(ctx=ctx, loop_settings=loop_settings)


@pytest.fixture(scope="session")
def eval_results() -> Iterator[list[dict[str, Any]]]:
    """Accumulate per-case result records; write REPORT.md + cache on teardown."""
    results: list[dict[str, Any]] = []
    yield results
    if results:
        from tests.eval._report import write_eval_report

        write_eval_report(results, EVAL_DIR)
