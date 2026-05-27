"""Tests for the refusal marker detector (Fork 25).

Pins the contract for the hidden-marker mechanism this branch
introduces: ``<!-- refusal:<category> -->`` at the start of LLM output
maps to ``(category, stripped_prose)``; absence maps to
``(None, prose)``; unknown categories are logged and treated as
no-refusal (safer than silently classifying as something specific).
"""

import pytest
import structlog

from customs_agent.agent.refusal import (
    REFUSAL_MARKER_RE,
    VALID_CATEGORIES,
    detect_refusal,
)

# ─────────────────────────────────────────────────────────────────────────────
# Sanity: the 5 categories match the contracts.RefusalCategory Literal
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_valid_categories_match_spec() -> None:
    assert VALID_CATEGORIES == frozenset({
        "off_domain", "out_of_range", "unmapped", "meta", "adversarial",
    })


# ─────────────────────────────────────────────────────────────────────────────
# Detection: each of the 5 categories round-trips
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("category", [
    "off_domain", "out_of_range", "unmapped", "meta", "adversarial",
])
def test_each_category_detected(category: str) -> None:
    prose = f"<!-- refusal:{category} -->\nI can't help with that."
    detected, stripped = detect_refusal(prose)
    assert detected == category
    assert stripped == "I can't help with that."


# ─────────────────────────────────────────────────────────────────────────────
# No-marker path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_no_marker_returns_none_and_unchanged_prose() -> None:
    """Common path: the LLM answered a normal question."""
    prose = "PCA filed 25 entries in January 2025 [1]."
    detected, stripped = detect_refusal(prose)
    assert detected is None
    assert stripped == prose


@pytest.mark.unit
def test_marker_in_middle_of_prose_not_detected() -> None:
    """Marker must be at the START; mid-prose mentions are not a refusal."""
    prose = "The agent might emit <!-- refusal:off_domain --> mid-response."
    detected, stripped = detect_refusal(prose)
    assert detected is None
    assert stripped == prose


# ─────────────────────────────────────────────────────────────────────────────
# Whitespace + case tolerance
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_leading_whitespace_tolerated() -> None:
    """LLMs sometimes emit a leading newline; the regex tolerates it."""
    prose = "  \n<!-- refusal:off_domain -->\nDeclined."
    detected, stripped = detect_refusal(prose)
    assert detected == "off_domain"
    assert stripped == "Declined."


@pytest.mark.unit
def test_marker_internal_whitespace_tolerated() -> None:
    """Whitespace inside the marker (around colons) doesn't break detection."""
    prose = "<!--  refusal : off_domain  -->\nDeclined."
    detected, _stripped = detect_refusal(prose)
    assert detected == "off_domain"


@pytest.mark.unit
def test_case_insensitive_marker_word() -> None:
    """The 'refusal' literal in the marker is case-insensitive — defends
    against LLM capitalizing it."""
    prose = "<!-- Refusal:off_domain -->\nDeclined."
    detected, _stripped = detect_refusal(prose)
    assert detected == "off_domain"


# ─────────────────────────────────────────────────────────────────────────────
# Unknown category — logged, treated as no-refusal
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_unknown_category_logged_and_returns_none() -> None:
    """Defends against the LLM emitting `<!-- refusal:typo -->`. We don't
    know what the agent meant, so we don't silently set refused=true to a
    fabricated category — we log and let the response pass through."""
    prose = "<!-- refusal:typo -->\nSomething."
    with structlog.testing.capture_logs() as logs:
        detected, stripped = detect_refusal(prose)
    assert detected is None
    assert stripped == prose  # unchanged (marker left in so ops can see it)
    events = [r for r in logs if r["event"] == "agent.unknown_refusal_category"]
    assert len(events) == 1
    assert events[0]["category"] == "typo"


@pytest.mark.unit
def test_no_log_on_valid_category() -> None:
    """Don't pollute logs on the normal refusal path."""
    prose = "<!-- refusal:off_domain -->\nDeclined."
    with structlog.testing.capture_logs() as logs:
        detect_refusal(prose)
    events = [r for r in logs if r["event"] == "agent.unknown_refusal_category"]
    assert events == []


@pytest.mark.unit
def test_regex_pattern_exposed_for_reuse() -> None:
    """The module exports REFUSAL_MARKER_RE so other code (logging filters,
    tests) can reuse the pattern."""
    assert REFUSAL_MARKER_RE.match("<!-- refusal:off_domain -->\n")
