"""Eval report writer — compact Markdown for the ``eval.yml`` PR comment.

The eval workflow (``.github/workflows/eval.yml``) reads
``tests/eval/REPORT.md`` and posts it as a PR comment, and caches
``tests/eval/.last-result.json`` keyed by a content hash so an unchanged
branch doesn't re-spend LLM dollars. Both artifacts are produced here at
the end of an eval session from the per-question result records the test
modules accumulate.

This is intentionally separate from
``scripts/generate_evaluation_md.py`` (the full, submission-grade
``EVALUATION.md`` deliverable): this report is a quick CI signal, that
one is the canonical static snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STATUS_ICON = {"PASS": "✅", "PASS (warn)": "⚠️", "FAIL": "❌"}


def _summary_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    graded = [r for r in results if r.get("kind") != "out_of_scope"]
    oos = [r for r in results if r.get("kind") == "out_of_scope"]
    return {
        "graded_total": len(graded),
        "graded_pass": sum(1 for r in graded if r["status"].startswith("PASS")),
        "graded_warn": sum(1 for r in graded if r["status"] == "PASS (warn)"),
        "graded_fail": sum(1 for r in graded if r["status"] == "FAIL"),
        "oos_total": len(oos),
        "oos_pass": sum(1 for r in oos if r["status"] == "PASS"),
    }


def build_report_markdown(results: list[dict[str, Any]]) -> str:
    """Render the per-question + out-of-scope results as Markdown."""
    counts = _summary_counts(results)
    lines: list[str] = ["## Eval results (real LLM)", ""]
    lines.append(
        f"**Graded**: {counts['graded_pass']}/{counts['graded_total']} correctness "
        f"({counts['graded_warn']} with architecture warnings, "
        f"{counts['graded_fail']} failing)."
    )
    if counts["oos_total"]:
        lines.append(
            f"**Out-of-scope refusals**: {counts['oos_pass']}/{counts['oos_total']} handled."
        )
    lines.append("")

    graded = sorted(
        (r for r in results if r.get("kind") != "out_of_scope"),
        key=lambda r: r["id"],
    )
    if graded:
        lines += ["| # | Tier | Status | Notes |", "|---|------|--------|-------|"]
        for r in graded:
            icon = _STATUS_ICON.get(r["status"], r["status"])
            notes = "; ".join(r.get("correctness_failures") or r.get("architecture_warnings") or [])
            lines.append(f"| {r['id']} | T{r['tier']} | {icon} {r['status']} | {notes} |")
        lines.append("")

    oos = [r for r in results if r.get("kind") == "out_of_scope"]
    if oos:
        lines += [
            "### Out-of-scope cases",
            "",
            "| Case | Status | Detail |",
            "|------|--------|--------|",
        ]
        for r in oos:
            icon = _STATUS_ICON.get(r["status"], r["status"])
            lines.append(f"| {r['id']} | {icon} {r['status']} | {r.get('detail', '')} |")
        lines.append("")

    return "\n".join(lines)


def write_eval_report(results: list[dict[str, Any]], out_dir: Path) -> None:
    """Write ``REPORT.md`` (PR comment) + ``.last-result.json`` (cache)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "REPORT.md").write_text(build_report_markdown(results))
    (out_dir / ".last-result.json").write_text(json.dumps(results, indent=2, default=str))
