"""Hermetic unit tests for the eval grader (Fork 46).

Exercises ``tests/eval/_grading.py`` against synthetic ``ChatResponse``
objects — no real LLM, no DuckDB, no index — so the grading LOGIC is
verified in the fast ``make test`` path, independent of the costly
real-LLM eval. The Q9 LLM-as-judge is tested with a stubbed OpenAI
client.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from customs_agent.agent.contracts import (
    ChatResponse,
    Citation,
    ResponseMeta,
    ToolCallTrace,
)
from tests.eval._grading import (
    _check_architecture,
    _check_citations,
    _check_numeric,
    _extract_scalar,
    _run_rubric_judge,
    _to_float,
    assert_close,
    grade_question,
)

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic response builders
# ─────────────────────────────────────────────────────────────────────────────


def _meta() -> ResponseMeta:
    return ResponseMeta(
        request_id="r",
        prompt_version="1.2.0",
        model="claude-sonnet-4-6",
        embedding_model="text-embedding-3-small",
        temperature=0.0,
        iterations_used=1,
    )


def _tool(
    name: str,
    result: dict[str, Any],
    args: dict[str, Any] | None = None,
    id: int = 1,
    view_used: str | None = None,
) -> ToolCallTrace:
    return ToolCallTrace(
        id=id,
        name=name,
        args=args or {},
        result=result,
        view_used=view_used,  # type: ignore[arg-type]
        shell_entries_excluded=0,
        rows_inspected=1,
        latency_ms=1,
    )


def _cit(chunk_id: str, id: int = 1) -> Citation:
    return Citation(id=id, doc="d.txt", section="§x", chunk_id=chunk_id, snippet="s")


def _resp(
    answer: str = "",
    tool_calls: list[ToolCallTrace] | None = None,
    citations: list[Citation] | None = None,
    refused: bool = False,
    refusal_category: str | None = None,
) -> ChatResponse:
    return ChatResponse(
        answer=answer,
        knowledge_citations=citations or [],
        tool_calls=tool_calls or [],
        refused=refused,
        refusal_category=refusal_category,  # type: ignore[arg-type]
        meta=_meta(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# assert_close + _to_float
# ─────────────────────────────────────────────────────────────────────────────


def test_to_float_handles_str_decimal_int() -> None:
    assert _to_float("59949493.45") == pytest.approx(59949493.45)
    assert _to_float(Decimal("31.67")) == pytest.approx(31.67)
    assert _to_float(255) == 255.0


def test_assert_close_exact() -> None:
    assert assert_close(65, 65, 0)[0] is True
    assert assert_close(64, 65, 0)[0] is False


def test_assert_close_abs() -> None:
    assert assert_close("59949493.45", "59949493.45", ["abs", 0.01])[0] is True
    assert assert_close(100.0, 100.005, ["abs", 0.01])[0] is True
    assert assert_close(100.0, 100.5, ["abs", 0.01])[0] is False


def test_assert_close_rel() -> None:
    assert assert_close(31.075, 31.1, ["rel", 0.001])[0] is True
    assert assert_close(31.075, 40.0, ["rel", 0.001])[0] is False


def test_assert_close_none_actual_fails() -> None:
    ok, detail = assert_close(None, 65, 0)
    assert ok is False
    assert "not found" in detail


# ─────────────────────────────────────────────────────────────────────────────
# _extract_scalar — nested + query_entries {"value": [...]} wrapper
# ─────────────────────────────────────────────────────────────────────────────


def test_extract_scalar_from_value_wrapper() -> None:
    r = _resp(tool_calls=[_tool("query_entries", {"value": [{"entry_count": 65}]})])
    assert _extract_scalar(r, "entry_count") == 65


def test_extract_scalar_from_dict_result() -> None:
    r = _resp(tool_calls=[_tool("total_duty_breakdown", {"section_301": "3207636.70"})])
    assert _extract_scalar(r, "section_301") == "3207636.70"


def test_extract_scalar_missing_returns_none() -> None:
    r = _resp(tool_calls=[_tool("hold_summary", {"hold_rate_pct": 19.67})])
    assert _extract_scalar(r, "nonexistent") is None


def test_extract_scalar_searches_multiple_tool_calls() -> None:
    r = _resp(
        tool_calls=[
            _tool("query_entries", {"value": [{"entry_count": 68}]}, id=1),
            _tool("query_entries", {"value": [{"line_count": 232}]}, id=2),
        ]
    )
    assert _extract_scalar(r, "entry_count") == 68
    assert _extract_scalar(r, "line_count") == 232


def test_extract_scalar_prefers_view() -> None:
    """When the same key appears on two views, prefer_view picks the right one
    regardless of call order (the Q11 line_count case)."""
    r = _resp(
        tool_calls=[
            _tool("query_entries", {"value": [{"line_count": 68}]}, id=1, view_used="entries_v"),
            _tool(
                "query_entries", {"value": [{"line_count": 232}]}, id=2, view_used="entry_lines_v"
            ),
        ]
    )
    assert _extract_scalar(r, "line_count") == 68  # first-match grabs entries_v
    assert _extract_scalar(r, "line_count", prefer_view="entry_lines_v") == 232


# ─────────────────────────────────────────────────────────────────────────────
# _check_numeric — scalar (Q1/Q3/Q11 shapes)
# ─────────────────────────────────────────────────────────────────────────────


def test_numeric_scalar_pass() -> None:
    q = {"answer": {"entry_count": 65}, "tolerance": {"entry_count": 0}}
    r = _resp(tool_calls=[_tool("query_entries", {"value": [{"entry_count": 65}]})])
    checks = _check_numeric(q, r)
    assert all(c.passed for c in checks)


def test_numeric_scalar_fail_on_wrong_value() -> None:
    q = {"answer": {"entry_count": 65}, "tolerance": {"entry_count": 0}}
    r = _resp(tool_calls=[_tool("query_entries", {"value": [{"entry_count": 99}]})])
    checks = _check_numeric(q, r)
    assert not all(c.passed for c in checks)


def test_numeric_string_label_checked_when_present() -> None:
    q = {
        "answer": {"port_of_entry_code": "1701", "entry_count": 255},
        "tolerance": {"entry_count": 0},
    }
    r = _resp(
        tool_calls=[
            _tool("query_entries", {"value": [{"port_of_entry_code": "1701", "entry_count": 255}]})
        ]
    )
    checks = _check_numeric(q, r)
    names = {c.name for c in checks}
    assert "label:port_of_entry_code" in names
    assert all(c.passed for c in checks)


def test_numeric_difference_derived_from_counts() -> None:
    q = {
        "answer": {"entry_count": 68, "line_count": 232, "difference": 164},
        "tolerance": {"entry_count": 0, "line_count": 0, "difference": 0},
    }
    r = _resp(
        tool_calls=[
            _tool("query_entries", {"value": [{"entry_count": 68}]}, id=1),
            _tool("query_entries", {"value": [{"line_count": 232}]}, id=2),
        ]
    )
    checks = _check_numeric(q, r)
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_money_decimal_vs_serialized_str_passes() -> None:
    """Regression (Q2/Q4): ground_truth serializes Decimals as strings while
    the tool returns Decimals. The tolerance loop compares them numerically
    (pass); the label loop must NOT also compare Decimal == str (which always
    fails). Only a numeric check should appear — no spurious label check."""
    q = {
        "answer": {"total_entered_value": "59949493.45"},
        "tolerance": {"total_entered_value": ["abs", 0.01]},
    }
    r = _resp(
        tool_calls=[
            _tool("query_entries", {"value": [{"total_entered_value": Decimal("59949493.45")}]})
        ]
    )
    checks = _check_numeric(q, r)
    assert all(c.passed for c in checks), [(c.name, c.detail) for c in checks if not c.passed]
    assert not any(c.name == "label:total_entered_value" for c in checks)


def test_money_field_without_tolerance_not_label_checked() -> None:
    """Regression (Q5): context money fields with no tolerance are reference
    only — they must not be spuriously label-checked (Decimal == str)."""
    q = {
        "answer": {"rate_pct": 31.075, "total_duty": "6430022.48"},
        "tolerance": {"rate_pct": ["rel", 0.001]},
    }
    r = _resp(
        tool_calls=[
            _tool("effective_duty_rate", {"rate_pct": 31.075, "total_duty": Decimal("6430022.48")})
        ]
    )
    checks = _check_numeric(q, r)
    assert all(c.passed for c in checks), [(c.name, c.detail) for c in checks if not c.passed]
    assert not any(c.name == "label:total_duty" for c in checks)


def test_line_count_prefers_entry_lines_v() -> None:
    """Regression (Q11): the agent's redundant count_lines on entries_v (68)
    must not shadow the real entry_lines_v line_count (232); difference must
    derive from the line-grain value."""
    q = {
        "answer": {"entry_count": 68, "line_count": 232, "difference": 164},
        "tolerance": {"entry_count": 0, "line_count": 0, "difference": 0},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "query_entries",
                {"value": [{"entry_count": 68, "line_count": 68}]},
                id=1,
                view_used="entries_v",
            ),
            _tool(
                "query_entries",
                {"value": [{"entry_count": 68, "line_count": 232}]},
                id=2,
                view_used="entry_lines_v",
            ),
        ]
    )
    checks = _check_numeric(q, r)
    assert all(c.passed for c in checks), [(c.name, c.detail) for c in checks if not c.passed]


# ─────────────────────────────────────────────────────────────────────────────
# _check_numeric — nested (Q7 ranked / Q8 top-5 / Q9 QBR)
# ─────────────────────────────────────────────────────────────────────────────


def test_numeric_ranked_q7() -> None:
    q = {
        "answer": {
            "ranked": [
                {"customer_code": "MHF", "ieepa_pct": 73.2626},
                {"customer_code": "SAG", "ieepa_pct": 59.212},
            ],
            "highest_customer_code": "MHF",
        },
        "tolerance": {"ieepa_pct": ["rel", 0.001]},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "compare_customers",
                {
                    "ranked": [
                        {"customer_code": "MHF", "ieepa_pct": 73.2626},
                        {"customer_code": "SAG", "ieepa_pct": 59.212},
                    ],
                    "highest_customer_code": "MHF",
                },
            )
        ]
    )
    checks = _check_numeric(q, r)
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]


def test_numeric_ranked_q7_wrong_winner_fails() -> None:
    q = {
        "answer": {
            "ranked": [{"customer_code": "MHF", "ieepa_pct": 73.2626}],
            "highest_customer_code": "MHF",
        },
        "tolerance": {"ieepa_pct": ["rel", 0.001]},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "compare_customers",
                {
                    "ranked": [{"customer_code": "SAG", "ieepa_pct": 73.2626}],
                    "highest_customer_code": "SAG",
                },
            )
        ]
    )
    assert not all(c.passed for c in _check_numeric(q, r))


def test_numeric_top_hts_q8_set_match() -> None:
    q = {
        "answer": {
            "top_5": [
                {"hts_code": "6104.63.2006", "total_duty": "3580203.63"},
                {"hts_code": "6204.62.4011", "total_duty": "2706034.35"},
            ]
        },
        "tolerance": {"total_duty": ["abs", 0.01]},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "top_hts_by_duty",
                {
                    "top_hts": [
                        {"hts_code": "6204.62.4011", "total_duty": "2706034.35"},
                        {"hts_code": "6104.63.2006", "total_duty": "3580203.63"},
                    ]
                },
            )
        ]
    )
    # Set match tolerates ordering variance.
    assert all(c.passed for c in _check_numeric(q, r))


def test_numeric_qbr_q9_hold_rate() -> None:
    q = {
        "answer": {
            "entry_volume_by_month": [{"month": "2025-01", "count": 66}],
            "duty_breakdown": {"total": "24423168.23"},
            "hold_summary": {"hold_rate_pct": 19.598},
        },
        "tolerance": {"hold_rate_pct": ["abs", 0.01]},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "qbr_summary",
                {
                    "duty_breakdown": {"total": "24423168.23"},
                    "hold_summary": {"hold_rate_pct": 19.6},
                },
            )
        ]
    )
    assert all(c.passed for c in _check_numeric(q, r))


# ─────────────────────────────────────────────────────────────────────────────
# _check_citations — always-on acceptance
# ─────────────────────────────────────────────────────────────────────────────


def test_citations_satisfied_by_knowledge_citations() -> None:
    q = {"expected_citations": ["hts_format_xxxx_xx_xxxx"]}
    r = _resp(citations=[_cit("hts_format_xxxx_xx_xxxx")])
    assert _check_citations(q, r).passed


def test_citations_satisfied_by_always_on() -> None:
    """rule_1 is always-on — not in knowledge_citations but still satisfied."""
    q = {"expected_citations": ["rule_1_date_filtering"]}
    r = _resp(citations=[])  # not cited, but always-on
    assert _check_citations(q, r).passed


def test_citations_missing_non_always_on_fails() -> None:
    q = {"expected_citations": ["qbr_structure"]}  # not always-on, not cited
    r = _resp(citations=[_cit("hts_format_xxxx_xx_xxxx")])
    assert not _check_citations(q, r).passed


# ─────────────────────────────────────────────────────────────────────────────
# _check_architecture
# ─────────────────────────────────────────────────────────────────────────────


def test_architecture_tool_and_args_subset_pass() -> None:
    q = {
        "expected_tool_name": "query_entries",
        "expected_tool_args_partial": {"filters": {"customer_code": "PCA"}},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "query_entries",
                {"value": []},
                args={"filters": {"customer_code": "PCA", "release_year_month": "2025-01"}},
            )
        ]
    )
    assert _check_architecture(q, r).all_pass


def test_architecture_args_mismatch_warns() -> None:
    q = {
        "expected_tool_name": "query_entries",
        "expected_tool_args_partial": {"filters": {"customer_code": "PCA"}},
    }
    r = _resp(
        tool_calls=[
            _tool("query_entries", {"value": []}, args={"filters": {"customer_code": "SAG"}})
        ]
    )
    assert not _check_architecture(q, r).all_pass


def test_architecture_q10_no_tool_is_acceptable() -> None:
    """lookup_knowledge OR no tool call both satisfy Q10 architecture."""
    q = {"expected_tool_name": "lookup_knowledge", "expected_tool_args_partial": {}}
    r = _resp(tool_calls=[])
    assert _check_architecture(q, r).all_pass


# ─────────────────────────────────────────────────────────────────────────────
# _run_rubric_judge — stubbed OpenAI client
# ─────────────────────────────────────────────────────────────────────────────


class _FakeOpenAI:
    """Minimal OpenAI stand-in returning canned JSON content."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.kwargs: dict[str, Any] = {}
        outer = self

        class _Completions:
            def create(self_inner, **kwargs: Any) -> Any:
                outer.kwargs = kwargs
                msg = type("M", (), {"content": outer._content})()
                choice = type("C", (), {"message": msg})()
                return type("R", (), {"choices": [choice]})()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


_RUBRIC_Q = {
    "query": "Generate a QBR for SAG Q1 2025.",
    "rubric": {
        "judge_model": "gpt-4o-mini",
        "temperature": 0,
        "seed": 42,
        "components": [
            "entry_volume_by_month",
            "duty_breakdown_by_program",
            "top_countries",
            "hold_rate",
        ],
        "pass_threshold": 3,
    },
}


def test_rubric_judge_passes_at_full_score() -> None:
    client = _FakeOpenAI(
        '{"entry_volume_by_month": 1, "duty_breakdown_by_program": 1, '
        '"top_countries": 1, "hold_rate": 1}'
    )
    check = _run_rubric_judge(_RUBRIC_Q, _resp(answer="QBR..."), client=client)
    assert check.passed
    # Judge invoked with the rubric's model + seed.
    assert client.kwargs["model"] == "gpt-4o-mini"
    assert client.kwargs["seed"] == 42


def test_rubric_judge_fails_below_threshold() -> None:
    client = _FakeOpenAI(
        '{"entry_volume_by_month": 1, "duty_breakdown_by_program": 1, '
        '"top_countries": 0, "hold_rate": 0}'
    )
    check = _run_rubric_judge(_RUBRIC_Q, _resp(answer="partial"), client=client)
    assert not check.passed


# ─────────────────────────────────────────────────────────────────────────────
# grade_question — end-to-end status
# ─────────────────────────────────────────────────────────────────────────────


def test_grade_question_pass() -> None:
    q = {
        "id": 1,
        "tier": 1,
        "answer": {"entry_count": 65},
        "tolerance": {"entry_count": 0},
        "expected_phrases": [],
        "expected_citations": ["rule_1_date_filtering"],
        "expected_tool_name": "query_entries",
        "expected_tool_args_partial": {"filters": {"customer_code": "PCA"}},
    }
    r = _resp(
        tool_calls=[
            _tool(
                "query_entries",
                {"value": [{"entry_count": 65}]},
                args={"filters": {"customer_code": "PCA"}},
            )
        ],
    )
    result = grade_question(q, r)
    assert result.status == "PASS"


def test_grade_question_pass_warn_on_architecture_miss() -> None:
    q = {
        "id": 1,
        "tier": 1,
        "answer": {"entry_count": 65},
        "tolerance": {"entry_count": 0},
        "expected_tool_name": "query_entries",
        "expected_tool_args_partial": {"filters": {"customer_code": "PCA"}},
    }
    # Correct number, but wrong tool args → correctness passes, architecture warns.
    r = _resp(
        tool_calls=[
            _tool(
                "query_entries",
                {"value": [{"entry_count": 65}]},
                args={"filters": {"customer_code": "SAG"}},
            )
        ],
    )
    result = grade_question(q, r)
    assert result.status == "PASS (warn)"


def test_grade_question_fail_on_wrong_number() -> None:
    q = {
        "id": 1,
        "tier": 1,
        "answer": {"entry_count": 65},
        "tolerance": {"entry_count": 0},
        "expected_tool_name": "query_entries",
    }
    r = _resp(tool_calls=[_tool("query_entries", {"value": [{"entry_count": 1}]})])
    result = grade_question(q, r)
    assert result.status == "FAIL"
