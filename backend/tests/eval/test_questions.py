"""Real-LLM eval over the 11 graded questions (Fork 45 Layer 3 + Fork 46).

Parametrized over ``ground_truth.json``. Correctness must pass (hard
assert); architecture mismatches are warn-only (logged + recorded for the
report). Skips cleanly without real API keys + a built index (see
``conftest._skip_reason``).
"""

from __future__ import annotations

import warnings

import pytest

from tests.eval._grading import grade_question
from tests.eval.conftest import load_ground_truth_questions

pytestmark = pytest.mark.eval


@pytest.mark.parametrize(
    "question", load_ground_truth_questions(), ids=lambda q: f"Q{q['id']}"
)
def test_question(question, agent_client, eval_results) -> None:
    response = agent_client.ask(question["query"])
    result = grade_question(question, response)

    eval_results.append(
        {
            "id": result.question_id,
            "tier": result.tier,
            "status": result.status,
            "query": question["query"],
            "correctness_failures": result.correctness.failures,
            "architecture_warnings": result.architecture.warnings,
            "latency_ms": response.meta.total_latency_ms,
            "input_tokens": response.meta.input_tokens,
            "cached_input_tokens": response.meta.cached_input_tokens,
            "output_tokens": response.meta.output_tokens,
        }
    )

    # Architecture is warn-only — surface it without failing the test.
    if not result.architecture.all_pass:
        warnings.warn(
            f"Q{question['id']} architecture: {result.architecture.warnings}",
            stacklevel=2,
        )

    assert result.correctness.all_pass, (
        f"Q{question['id']} correctness failed:\n"
        + "\n".join(f"  - {f}" for f in result.correctness.failures)
    )
