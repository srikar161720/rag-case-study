"""Tests for the citation marker validator (Fork 28).

Pins the contract: orphan markers are stripped silently with a
structlog warning; valid markers pass through unchanged. The shared
ID space (citations + tool_calls) is exercised explicitly so future
ID-assignment changes in the agent loop can't silently break the
"either array can satisfy a marker" invariant.
"""

from dataclasses import dataclass

import pytest
import structlog

from customs_agent.agent.validator import MARKER_RE, validate_markers


@dataclass
class _StubWithId:
    """Minimal _HasId-satisfying stub for tests; mirrors the Citation +
    ToolCallTrace shape without dragging in their full Pydantic surface."""

    id: int


# ─────────────────────────────────────────────────────────────────────────────
# Regex sanity
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_marker_re_matches_single_digit() -> None:
    assert MARKER_RE.findall("see [1] for context") == ["1"]


@pytest.mark.unit
def test_marker_re_matches_multi_digit() -> None:
    assert MARKER_RE.findall("[42] and [123]") == ["42", "123"]


@pytest.mark.unit
def test_marker_re_does_not_match_non_numeric() -> None:
    assert MARKER_RE.findall("[abc] [x1y]") == []


# ─────────────────────────────────────────────────────────────────────────────
# validate_markers — happy path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_valid_markers_pass_through_unchanged() -> None:
    """When every [N] in prose maps to a real citation/tool_call ID, the
    function returns the prose byte-for-byte."""
    prose = "PCA filed 25 entries in January [1], per Rule 1 [2]."
    citations = [_StubWithId(id=1)]
    tool_calls = [_StubWithId(id=2)]
    assert validate_markers(prose, citations, tool_calls) == prose


@pytest.mark.unit
def test_empty_prose_returns_empty() -> None:
    assert validate_markers("", [], []) == ""


@pytest.mark.unit
def test_no_markers_in_prose() -> None:
    """Prose without any [N] markers is trivially valid — passes through."""
    prose = "The answer is 25 entries based on Rule 1."
    assert validate_markers(prose, [_StubWithId(id=1)], []) == prose


# ─────────────────────────────────────────────────────────────────────────────
# validate_markers — orphan stripping
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_single_orphan_marker_stripped() -> None:
    """[99] when only [1] is valid → orphan [99] gone, [1] kept."""
    prose = "See [1] and [99] for details."
    result = validate_markers(prose, [_StubWithId(id=1)], [])
    assert result == "See [1] and  for details."


@pytest.mark.unit
def test_multiple_orphans_all_stripped() -> None:
    prose = "Refs [99] [100] [101] are all invalid; [1] is valid."
    result = validate_markers(prose, [_StubWithId(id=1)], [])
    assert "[99]" not in result
    assert "[100]" not in result
    assert "[101]" not in result
    assert "[1]" in result


@pytest.mark.unit
def test_orphan_logged_with_invalid_and_valid_ids() -> None:
    """ops needs to see WHICH IDs were hallucinated AND which were valid
    so the model's confusion is debuggable."""
    prose = "Refs [99] and [1]"
    with structlog.testing.capture_logs() as logs:
        validate_markers(prose, [_StubWithId(id=1)], [_StubWithId(id=2)])
    events = [r for r in logs if r["event"] == "agent.hallucinated_citation"]
    assert len(events) == 1
    assert events[0]["invalid_ids"] == [99]
    assert events[0]["valid_ids"] == [1, 2]


@pytest.mark.unit
def test_no_warning_when_all_markers_valid() -> None:
    """Don't pollute logs with WARNINGs on the happy path."""
    prose = "Refs [1] and [2]"
    with structlog.testing.capture_logs() as logs:
        validate_markers(prose, [_StubWithId(id=1)], [_StubWithId(id=2)])
    events = [r for r in logs if r["event"] == "agent.hallucinated_citation"]
    assert events == []


# ─────────────────────────────────────────────────────────────────────────────
# Shared ID space — citations + tool_calls
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_marker_satisfied_by_tool_call_id() -> None:
    """[2] is valid if a tool_call has id=2, even if no citation has id=2."""
    prose = "Computation [2] confirms the answer."
    result = validate_markers(prose, [_StubWithId(id=1)], [_StubWithId(id=2)])
    assert result == prose


@pytest.mark.unit
def test_marker_satisfied_by_citation_id() -> None:
    """Symmetric: [1] valid if it's a citation ID, no tool_call needed."""
    prose = "Per the rule [1]."
    result = validate_markers(prose, [_StubWithId(id=1)], [])
    assert result == prose


@pytest.mark.unit
def test_marker_invalid_when_neither_has_id() -> None:
    """[5] orphan when citations have [1,2] and tool_calls have [3,4]."""
    prose = "Bogus [5]."
    result = validate_markers(
        prose,
        [_StubWithId(id=1), _StubWithId(id=2)],
        [_StubWithId(id=3), _StubWithId(id=4)],
    )
    assert "[5]" not in result
