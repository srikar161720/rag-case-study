"""Two-axis eval grading (Fork 46).

Each graded question is scored on two independent axes:

- **Correctness (must pass)** — the answer is numerically right, grounded
  in the expected KB citations, and (for Q9) passes an LLM-as-judge
  rubric. A correctness failure fails the eval test.
- **Architecture (warn-only)** — the agent used the *expected* tool with
  the expected partial args. An architecture miss is logged as a warning
  and recorded in the report, but does NOT fail the test: a question
  answered correctly via an unexpected-but-valid path still passes.

Numeric values are read from the structured ``ChatResponse.tool_calls``
results (never parsed out of prose), so grading is robust to phrasing.
Citations are satisfied if the expected ``chunk_id`` appears in
``knowledge_citations[]`` OR in the always-on block — the universal rules
(``rule_1`` / ``rule_2``) ground every answer via the cached system
prompt and are not "retrieved" (see Fork 28 + the citation merge in
``agent/loop.py``).

The module is import-safe with no real-LLM dependency except
:func:`_run_rubric_judge`, which takes an injectable ``client`` so the
hermetic unit tests can stub OpenAI.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from customs_agent.agent.bootstrap import compute_always_on_chunk_ids
from customs_agent.agent.contracts import ChatResponse
from customs_agent.config import settings

Tolerance = Any  # 0 | None | ["abs", float] | ["rel", float]


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Check:
    """One graded assertion."""

    name: str
    passed: bool
    detail: str = ""


@dataclass
class CorrectnessReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]


@dataclass
class ArchitectureReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def warnings(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]


@dataclass
class QuestionResult:
    question_id: int
    tier: int
    status: str  # "PASS" | "PASS (warn)" | "FAIL"
    correctness: CorrectnessReport
    architecture: ArchitectureReport


# ─────────────────────────────────────────────────────────────────────────────
# Numeric helpers
# ─────────────────────────────────────────────────────────────────────────────


def _to_float(x: Any) -> float:
    """Coerce a tool/answer value to float. Ground-truth Decimals are
    serialized as strings to preserve precision, so strings are expected."""
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, int | float | Decimal):
        return float(x)
    if isinstance(x, str):
        return float(x)
    raise TypeError(f"cannot convert {x!r} ({type(x).__name__}) to float")


def assert_close(actual: Any, expected: Any, tolerance: Tolerance) -> tuple[bool, str]:
    """Compare ``actual`` to ``expected`` under ``tolerance``.

    ``tolerance`` is ``0`` / ``None`` (exact), ``["abs", v]`` (absolute),
    or ``["rel", v]`` (relative). Returns ``(passed, detail)`` — ``detail``
    is empty on pass.
    """
    if actual is None:
        return False, f"value not found in tool results (expected {expected!r})"
    a, e = _to_float(actual), _to_float(expected)
    if not tolerance:  # 0, None, [] → exact
        ok = a == e
        return ok, "" if ok else f"expected {e}, got {a} (exact)"
    kind, value = tolerance
    if kind == "abs":
        ok = abs(a - e) <= value
        return ok, "" if ok else f"|{a} - {e}| = {abs(a - e):.6g} > {value}"
    if kind == "rel":
        ok = (abs(a - e) / e <= value) if e != 0 else (a == 0)
        denom = e if e != 0 else 1
        return ok, "" if ok else f"|{a} - {e}|/{e} = {abs(a - e) / denom:.6g} > {value}"
    return False, f"unknown tolerance kind: {kind!r}"


def _walk(obj: Any, key: str) -> Iterator[Any]:
    """Yield every value stored under ``key`` anywhere in a nested
    dict/list structure (depth-first, dicts before their children)."""
    if isinstance(obj, dict):
        if key in obj:
            yield obj[key]
        for v in obj.values():
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item, key)


def _extract_scalar(
    response: ChatResponse, key: str, prefer_view: str | None = None
) -> Any | None:
    """First value found under ``key`` across all tool-call results.

    Tool results are dicts (or the ``{"value": [...]}`` wrapper the loop
    applies to list-returning tools like ``query_entries``); the
    recursive walk reaches into either shape.

    ``prefer_view`` makes extraction grain-aware: tool calls on that view
    are searched first. This matters for grain-sensitive metrics like
    ``line_count`` — ``COUNT(*)`` is the true tariff-line count only on
    ``entry_lines_v`` (on ``entries_v`` it counts entries), so an agent can
    legitimately emit a misleading ``line_count`` on an entries_v call
    alongside the correct one on entry_lines_v; preferring the line-grain
    view picks the right one regardless of call order.
    """
    if prefer_view is not None:
        for tc in response.tool_calls:
            if tc.view_used == prefer_view:
                for found in _walk(tc.result, key):
                    return found
    for tc in response.tool_calls:
        for found in _walk(tc.result, key):
            return found
    return None


def _find_result_with_key(response: ChatResponse, key: str) -> dict[str, Any] | None:
    """The first tool-call result dict carrying ``key`` at the top level."""
    for tc in response.tool_calls:
        if isinstance(tc.result, dict) and key in tc.result:
            return tc.result
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Correctness checks
# ─────────────────────────────────────────────────────────────────────────────


def _check_refused(question: dict[str, Any], r: ChatResponse) -> Check:
    """Every graded question must be answered, never refused."""
    return Check(
        "refused",
        r.refused is False,
        "" if r.refused is False else f"refused={r.refused} ({r.refusal_category})",
    )


def _check_numeric(question: dict[str, Any], r: ChatResponse) -> list[Check]:
    """Dispatch numeric checks by answer shape (Q7 ranked / Q8 top-5 /
    Q9 QBR / generic scalar+label)."""
    answer = question.get("answer", {})
    tol = question.get("tolerance", {})
    if "ranked" in answer:
        return _check_ranked(answer, tol, r)
    if "top_5" in answer:
        return _check_top_hts(answer, tol, r)
    if "entry_volume_by_month" in answer or "duty_breakdown" in answer:
        return _check_qbr(answer, tol, r)
    return _check_scalar(answer, tol, r)


# Metrics whose COUNT(*) meaning depends on the view's grain. line_count is
# the true tariff-line count only on entry_lines_v (COUNT(*) on entries_v
# counts entries), so extraction prefers the line-grain call.
_GRAIN_PREFERRED_VIEW = {"line_count": "entry_lines_v"}


def _check_scalar(
    answer: dict[str, Any], tol: dict[str, Any], r: ChatResponse
) -> list[Check]:
    checks: list[Check] = []
    # Numeric fields with an explicit tolerance.
    for key, tolerance in tol.items():
        actual = _extract_scalar(r, key, prefer_view=_GRAIN_PREFERRED_VIEW.get(key))
        if actual is None and key == "difference":
            ec = _extract_scalar(r, "entry_count")
            lc = _extract_scalar(
                r, "line_count", prefer_view=_GRAIN_PREFERRED_VIEW.get("line_count")
            )
            if ec is not None and lc is not None:
                actual = _to_float(lc) - _to_float(ec)
        ok, detail = assert_close(actual, answer.get(key), tolerance)
        checks.append(Check(f"numeric:{key}", ok, detail))
    # String LABELS only — true non-numeric identifiers (port code, status).
    # A numeric value serialized as a string in ground_truth (Decimal money)
    # comes back from the tool as a Decimal, not a str, so the
    # ``isinstance(actual, str)`` guard skips it here — it's already graded by
    # the tolerance loop above (or intentionally left as context when it has
    # no tolerance). Knowledge-only fields like Q10's ``date_field`` aren't
    # produced by any tool (actual is None) and are validated via phrases.
    for key, expected in answer.items():
        if isinstance(expected, str):
            actual = _extract_scalar(r, key)
            if isinstance(actual, str):
                checks.append(
                    Check(
                        f"label:{key}",
                        actual == expected,
                        "" if actual == expected else f"got {actual!r}, exp {expected!r}",
                    )
                )
    return checks


def _check_ranked(
    answer: dict[str, Any], tol: dict[str, Any], r: ChatResponse
) -> list[Check]:
    result = _find_result_with_key(r, "ranked")
    if result is None:
        return [Check("numeric:ranked", False, "no tool result carrying 'ranked'")]
    actual_ranked = result["ranked"]
    expected_ranked = answer["ranked"]
    actual_by_cust = {e["customer_code"]: e for e in actual_ranked}

    checks: list[Check] = []
    # Winner (exact) + ranking order (exact).
    got_high = result.get("highest_customer_code")
    exp_high = answer.get("highest_customer_code")
    checks.append(
        Check("label:highest_customer_code", got_high == exp_high,
              "" if got_high == exp_high else f"got {got_high!r}, exp {exp_high!r}")
    )
    actual_order = [e["customer_code"] for e in actual_ranked]
    expected_order = [e["customer_code"] for e in expected_ranked]
    checks.append(
        Check("numeric:ranking_order", actual_order == expected_order,
              "" if actual_order == expected_order else f"got {actual_order}, exp {expected_order}")
    )
    # Each tolerance-keyed metric, per customer.
    for tol_key, tolerance in tol.items():
        for exp_e in expected_ranked:
            cust = exp_e["customer_code"]
            if tol_key not in exp_e:
                continue
            act_e = actual_by_cust.get(cust, {})
            ok, detail = assert_close(act_e.get(tol_key), exp_e[tol_key], tolerance)
            checks.append(Check(f"numeric:{tol_key}[{cust}]", ok, detail))
    return checks


def _check_top_hts(
    answer: dict[str, Any], tol: dict[str, Any], r: ChatResponse
) -> list[Check]:
    result = _find_result_with_key(r, "top_hts")
    if result is None:
        return [Check("numeric:top_hts", False, "no tool result carrying 'top_hts'")]
    actual = result["top_hts"]
    expected = answer["top_5"]
    checks: list[Check] = []
    # Top-N code SET matches (tie-break ordering variance allowed, per Fork 46).
    actual_codes = {e["hts_code"] for e in actual}
    expected_codes = {e["hts_code"] for e in expected}
    checks.append(
        Check("numeric:top_hts_set", actual_codes == expected_codes,
              "" if actual_codes == expected_codes
              else f"got {sorted(actual_codes)}, exp {sorted(expected_codes)}")
    )
    # Each total_duty within tolerance, matched by hts_code.
    tolerance = tol.get("total_duty")
    actual_by_code = {e["hts_code"]: e for e in actual}
    for exp_e in expected:
        act_e = actual_by_code.get(exp_e["hts_code"], {})
        ok, detail = assert_close(act_e.get("total_duty"), exp_e["total_duty"], tolerance)
        checks.append(Check(f"numeric:total_duty[{exp_e['hts_code']}]", ok, detail))
    return checks


def _check_qbr(
    answer: dict[str, Any], tol: dict[str, Any], r: ChatResponse
) -> list[Check]:
    result = _find_result_with_key(r, "duty_breakdown")
    if result is None:
        return [Check("numeric:qbr", False, "no tool result carrying 'duty_breakdown'")]
    checks: list[Check] = []
    # The QBR structured check the tolerance pins is hold_rate_pct; the
    # rubric judge covers the prose-level completeness of the 4 sections.
    if "hold_rate_pct" in tol:
        actual = result.get("hold_summary", {}).get("hold_rate_pct")
        expected = answer.get("hold_summary", {}).get("hold_rate_pct")
        ok, detail = assert_close(actual, expected, tol["hold_rate_pct"])
        checks.append(Check("numeric:hold_rate_pct", ok, detail))
    return checks


def _check_phrases(question: dict[str, Any], r: ChatResponse) -> Check:
    phrases = question.get("expected_phrases", [])
    if not phrases:
        return Check("phrases", True, "none required")
    prose = r.answer.lower()
    missing = [p for p in phrases if p.lower() not in prose]
    return Check("phrases", not missing, "" if not missing else f"missing: {missing}")


def _check_citations(question: dict[str, Any], r: ChatResponse) -> Check:
    expected = set(question.get("expected_citations", []))
    if not expected:
        return Check("citations", True, "none required")
    cited = {c.chunk_id for c in r.knowledge_citations}
    satisfied = cited | compute_always_on_chunk_ids()
    missing = expected - satisfied
    return Check("citations", not missing, "" if not missing else f"missing: {sorted(missing)}")


JUDGE_PROMPT = """You are grading an AI agent's response to a QBR question.

QUESTION:
{question}

EXPECTED COMPONENTS:
1. entry_volume_by_month: monthly entry counts for Jan, Feb, Mar 2025
2. duty_breakdown_by_program: primary, Section 301, IEEPA, MPF, HMF totals
3. top_countries: sourcing countries listed
4. hold_rate: hold rate stated as a percentage

AGENT'S RESPONSE:
{response_prose}

For each component, score 1 (clearly present) or 0 (missing/unclear).
Return JSON ONLY (no commentary):
{{"entry_volume_by_month": 0 or 1, "duty_breakdown_by_program": 0 or 1, \
"top_countries": 0 or 1, "hold_rate": 0 or 1}}
"""


def _run_rubric_judge(
    question: dict[str, Any], r: ChatResponse, *, client: Any | None = None
) -> Check:
    """LLM-as-judge for Q9 (Fork 8). ``client`` is injectable so the
    hermetic unit tests can stub OpenAI; production passes a real client."""
    rubric = question["rubric"]
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=rubric.get("judge_model", settings.llm_judge_model),
        temperature=rubric.get("temperature", 0),
        seed=rubric.get("seed", settings.llm_seed),
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=question["query"], response_prose=r.answer
                ),
            }
        ],
        response_format={"type": "json_object"},
    )
    scores = json.loads(resp.choices[0].message.content)
    total = sum(int(v) for v in scores.values())
    threshold = rubric.get("pass_threshold", 3)
    return Check(
        "rubric",
        total >= threshold,
        f"{total}/{len(scores)} (need {threshold}); scores={scores}",
    )


def _check_correctness(
    question: dict[str, Any], r: ChatResponse, *, judge_client: Any | None = None
) -> CorrectnessReport:
    checks = [_check_refused(question, r)]
    checks.extend(_check_numeric(question, r))
    checks.append(_check_phrases(question, r))
    checks.append(_check_citations(question, r))
    if question.get("rubric"):
        checks.append(_run_rubric_judge(question, r, client=judge_client))
    return CorrectnessReport(checks=checks)


# ─────────────────────────────────────────────────────────────────────────────
# Architecture checks (warn-only)
# ─────────────────────────────────────────────────────────────────────────────


def _is_subset(partial: Any, actual: Any) -> bool:
    """True if ``partial`` is a recursive subset of ``actual`` (every key
    present with a matching — recursively-subset — value)."""
    if isinstance(partial, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and _is_subset(v, actual[k]) for k, v in partial.items())
    return partial == actual


def _check_architecture(question: dict[str, Any], r: ChatResponse) -> ArchitectureReport:
    expected_tool = question.get("expected_tool_name")
    if not expected_tool:
        return ArchitectureReport(checks=[])
    called = [tc.name for tc in r.tool_calls]
    checks: list[Check] = []

    # Q10 (knowledge): lookup_knowledge OR no tool call are both acceptable.
    no_tool_ok = expected_tool == "lookup_knowledge" and not called
    tool_called = (expected_tool in called) or no_tool_ok
    checks.append(
        Check("arch:tool_called", tool_called,
              "" if tool_called else f"expected {expected_tool}, called {called}")
    )

    partial = question.get("expected_tool_args_partial", {})
    if partial and not no_tool_ok:
        matching = [tc for tc in r.tool_calls if tc.name == expected_tool]
        ok = any(_is_subset(partial, tc.args) for tc in matching)
        checks.append(
            Check("arch:args_partial", ok,
                  "" if ok else f"{partial} not ⊆ any {expected_tool} call args")
        )
    return ArchitectureReport(checks=checks)


# ─────────────────────────────────────────────────────────────────────────────
# Top-level entry point
# ─────────────────────────────────────────────────────────────────────────────


def grade_question(
    question: dict[str, Any], r: ChatResponse, *, judge_client: Any | None = None
) -> QuestionResult:
    """Grade one question on both axes. Status is ``FAIL`` on any
    correctness miss, ``PASS (warn)`` on an architecture-only miss,
    else ``PASS``."""
    correctness = _check_correctness(question, r, judge_client=judge_client)
    architecture = _check_architecture(question, r)
    if not correctness.all_pass:
        status = "FAIL"
    elif not architecture.all_pass:
        status = "PASS (warn)"
    else:
        status = "PASS"
    return QuestionResult(
        question_id=question["id"],
        tier=question["tier"],
        status=status,
        correctness=correctness,
        architecture=architecture,
    )
