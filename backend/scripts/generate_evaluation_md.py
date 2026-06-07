"""EVALUATION.md generator (G5 + Fork 43 + Fork 46).

Runs each of the 11 graded questions against the **deployed** backend
(``BACKEND_URL``), grades the responses with the same two-axis grader the
eval suite uses (``tests/eval/_grading.py``, including the Q9 LLM-as-judge),
and emits the canonical ``EVALUATION.md`` snapshot to **stdout**.

Invocation (user-only — Claude must never run this; it overwrites a
committed deliverable):

    cd backend && uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md

Required environment (see ``backend/.env.example``):

- ``BACKEND_URL``      — deployed backend, e.g. https://customs-agent-backend.fly.dev
- ``BACKEND_API_KEY``  — forwarded as ``X-API-Key`` to ``/chat``
- ``OPENAI_API_KEY``   — the Q9 rubric judge (gpt-4o-mini)
- ``ANTHROPIC_API_KEY``— required by the Settings singleton at import (the
  deployed backend does the actual Anthropic calls)
- ``FRONTEND_URL``     — optional; shown in the run-metadata table

The markdown-assembly functions are pure (no network) so they are unit
tested in ``tests/unit/eval/test_generate_evaluation_md.py``; only
:func:`main` performs I/O.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from customs_agent.agent.contracts import ChatResponse
from customs_agent.agent.prompt import PROMPT_VERSION
from customs_agent.config import MANIFEST_PATH, settings
from tests.eval._grading import QuestionResult, grade_question
from tests.ground_truth import OUTPUT_PATH as GROUND_TRUTH_PATH

_STATUS_ICON = {"PASS": "✅", "PASS (warn)": "⚠️", "FAIL": "❌", "ERROR": "🛑"}


# ─────────────────────────────────────────────────────────────────────────────
# I/O (the only impure part)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_answer(
    client: httpx.Client, backend_url: str, api_key: str, query: str
) -> ChatResponse:
    """POST one question to the deployed ``/chat`` and parse the sidecar."""
    resp = client.post(
        f"{backend_url}/chat",
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        json={"messages": [{"role": "user", "content": query}]},
    )
    resp.raise_for_status()
    return ChatResponse.model_validate(resp.json())


def _load_manifest() -> dict[str, Any]:
    try:
        return json.loads(Path(MANIFEST_PATH).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Pure markdown assembly
# ─────────────────────────────────────────────────────────────────────────────


def _rubric_score(result: QuestionResult) -> str | None:
    """Pull the 'rubric N/M' detail from a graded result, if present."""
    for check in result.correctness.checks:
        if check.name == "rubric":
            return check.detail.split(";")[0].strip()
    return None


def build_run_metadata(
    gt: dict[str, Any],
    manifest: dict[str, Any],
    backend_url: str,
    frontend_url: str,
    generated_at: str,
) -> str:
    rows = [
        ("`PROMPT_VERSION` (Fork 27)", f"`{PROMPT_VERSION}`"),
        ("Main agent model", f"`{settings.llm_model}`"),
        ("Eval judge model (Q9 rubric)", f"`{settings.llm_judge_model}`"),
        ("Embedding model", f"`{settings.llm_embedding_model}`"),
        ("Temperature", f"`{settings.llm_temperature}`"),
        ("Seed (OpenAI judge)", f"`{settings.llm_seed}`"),
        ("Dataset SHA-256", f"`{gt.get('dataset_sha256', 'unknown')}`"),
        ("Index built at", f"`{manifest.get('built_at', 'unknown')}`"),
        ("Backend deployed URL", backend_url or "—"),
        ("Frontend deployed URL", frontend_url or "—"),
    ]
    lines = [
        f"> **Snapshot generated**: {generated_at}",
        "> **Regenerate**: `make eval-md` "
        "(`cd backend && uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md`)",
        "",
        "## Run Metadata",
        "",
        "| Field | Value |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def build_summary(records: list[dict[str, Any]]) -> str:
    results: list[QuestionResult] = [r["result"] for r in records]
    responses: list[ChatResponse] = [r["response"] for r in records]
    n = len(results)
    correctness_pass = sum(1 for r in results if r.status != "FAIL" and r.status != "ERROR")
    arch_pass = sum(1 for r in results if r.status == "PASS")
    warn = sum(1 for r in results if r.status == "PASS (warn)")

    latencies = [resp.meta.total_latency_ms for resp in responses if resp.meta.total_latency_ms]
    total_in = sum(resp.meta.input_tokens for resp in responses)
    total_cached = sum(resp.meta.cached_input_tokens for resp in responses)
    cache_pct = f"{100.0 * total_cached / total_in:.0f}%" if total_in else "n/a"
    median_ms = f"{statistics.median(latencies):.0f} ms" if latencies else "n/a"
    p95_ms = (
        f"{statistics.quantiles(latencies, n=20)[-1]:.0f} ms" if len(latencies) >= 2 else "n/a"
    )

    rubric = next((s for r in results if (s := _rubric_score(r))), "n/a")

    rows = [
        ("Questions evaluated", f"{n}/{n}"),
        ("**Correctness** passes (Fork 46)", str(correctness_pass)),
        ("**Architecture** passes (no warnings)", str(arch_pass)),
        ("Correctness passes with architecture warning", str(warn)),
        ("Q9 rubric score", rubric),
        ("Median question latency", median_ms),
        ("p95 question latency", p95_ms),
        ("Cached input tokens % (across run)", cache_pct),
        ("Estimated cost", "n/a (pricing module lands with Langfuse, G11)"),
    ]
    lines = ["## Summary", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def build_per_question_table(records: list[dict[str, Any]]) -> str:
    lines = [
        "## Per-Question Results",
        "",
        "| # | Tier | Question | Status | Tool |",
        "|---|------|----------|--------|------|",
    ]
    for rec in records:
        q, result, resp = rec["question"], rec["result"], rec["response"]
        icon = _STATUS_ICON.get(result.status, result.status)
        tools = ", ".join(f"`{tc.name}`" for tc in resp.tool_calls) or "—"
        query = q["query"].replace("|", "\\|")
        query = query if len(query) <= 70 else query[:67] + "…"
        lines.append(
            f"| {q['id']} | T{q['tier']} | {query} | {icon} {result.status} | {tools} |"
        )
    return "\n".join(lines)


def build_detailed_results(records: list[dict[str, Any]]) -> str:
    lines = ["## Detailed Results", ""]
    for rec in records:
        q, result, resp = rec["question"], rec["result"], rec["response"]
        icon = _STATUS_ICON.get(result.status, result.status)
        lines.append(f"### Q{q['id']} (Tier {q['tier']}, {icon} {result.status})")
        lines.append("")
        lines.append(f"**Question**: {q['query']}")
        lines.append("")
        lines.append(f"**Expected**: `{json.dumps(q.get('answer', {}), default=str)}`")
        lines.append("")
        answer = resp.answer.strip()
        answer = answer if len(answer) <= 600 else answer[:597] + "…"
        lines.append("**Agent's answer**:")
        lines.append("")
        lines.append("\n".join(f"> {ln}" if ln else ">" for ln in answer.splitlines()))
        lines.append("")
        if result.correctness.failures:
            lines.append("**Correctness failures**:")
            lines += [f"- {f}" for f in result.correctness.failures]
            lines.append("")
        if result.architecture.warnings:
            lines.append("**Architecture warnings**:")
            lines += [f"- {w}" for w in result.architecture.warnings]
            lines.append("")
        cites = ", ".join(f"`{c.chunk_id}`" for c in resp.knowledge_citations) or "—"
        lines.append(f"**Citations**: {cites}")
        lines.append("")
        if resp.tool_calls:
            lines.append("**Tool calls**:")
            for tc in resp.tool_calls:
                sql = (tc.sql_executed or "").strip().replace("\n", " ")
                sql = (sql[:120] + "…") if len(sql) > 120 else sql
                detail = f" · `{sql}`" if sql else ""
                lines.append(f"- `{tc.name}`{detail}")
            lines.append("")
        m = resp.meta
        lines.append(
            f"**Performance**: {m.total_latency_ms} ms · {m.input_tokens} in "
            f"({m.cached_input_tokens} cached) · {m.output_tokens} out"
        )
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def build_self_assessment(records: list[dict[str, Any]]) -> str:
    results: list[QuestionResult] = [r["result"] for r in records]
    fails = [r for r in results if r.status in ("FAIL", "ERROR")]
    warns = [r for r in results if r.status == "PASS (warn)"]
    lines = ["## Self-Assessment", ""]
    if not fails:
        lines.append(
            f"The agent passed all {len(results)} questions on the correctness axis."
        )
    else:
        ids = ", ".join(f"Q{r.question_id}" for r in fails)
        lines.append(f"{len(fails)} question(s) failed on correctness: {ids}.")
    if warns:
        ids = ", ".join(f"Q{r.question_id}" for r in warns)
        lines.append("")
        lines.append(
            f"{len(warns)} question(s) passed correctness with an architecture "
            f"warning (a valid but unexpected tool path): {ids}."
        )
    lines.append("")
    lines.append(
        "Architecture checks are advisory (Fork 46): a question answered "
        "correctly via an unexpected-but-valid path still passes. See the "
        "README \"Future work\" section for improvements."
    )
    return "\n".join(lines)


def build_evaluation_md(
    records: list[dict[str, Any]],
    gt: dict[str, Any],
    manifest: dict[str, Any],
    backend_url: str,
    frontend_url: str,
    generated_at: str,
) -> str:
    """Assemble the full EVALUATION.md from graded records (pure)."""
    sections = [
        "# EVALUATION.md",
        "",
        build_run_metadata(gt, manifest, backend_url, frontend_url, generated_at),
        "",
        build_summary(records),
        "",
        build_per_question_table(records),
        "",
        build_detailed_results(records),
        build_self_assessment(records),
        "",
    ]
    return "\n".join(sections) + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    backend_url = os.environ.get("BACKEND_URL", "").rstrip("/")
    api_key = os.environ.get("BACKEND_API_KEY", "")
    frontend_url = os.environ.get("FRONTEND_URL", "")
    if not backend_url or not api_key:
        print(
            "ERROR: set BACKEND_URL and BACKEND_API_KEY in the environment.\n"
            "  See backend/.env.example and the EVALUATION.md reproducibility block.",
            file=sys.stderr,
        )
        return 1

    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    manifest = _load_manifest()

    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(120.0)) as client:
        for q in gt["questions"]:
            print(f"  Q{q['id']}…", file=sys.stderr)
            resp = _fetch_answer(client, backend_url, api_key, q["query"])
            try:
                result = grade_question(q, resp)
            except Exception as exc:  # judge/network hiccup shouldn't lose the file
                from tests.eval._grading import (
                    ArchitectureReport,
                    Check,
                    CorrectnessReport,
                )

                result = QuestionResult(
                    question_id=q["id"],
                    tier=q["tier"],
                    status="ERROR",
                    correctness=CorrectnessReport(checks=[Check("grading", False, str(exc))]),
                    architecture=ArchitectureReport(checks=[]),
                )
            records.append({"question": q, "response": resp, "result": result})

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(build_evaluation_md(records, gt, manifest, backend_url, frontend_url, generated_at))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
