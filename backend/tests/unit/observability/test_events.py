"""Unit tests for the event-name taxonomy (Fork 52).

These guard the observability *contract*: the string values are what
``fly logs | jq 'select(.event == "...")'`` filters key off, so a typo or
an accidental rename is a breaking change. The rename of
``agent.iteration_limit_hit`` → ``agent.iteration_limit`` (reconciliation
to the canonical taxonomy table) is pinned explicitly.
"""

import re

import pytest

from customs_agent.observability.events import Events


def _event_values() -> dict[str, str]:
    """All public string constants declared on :class:`Events`."""
    return {
        name: value
        for name, value in vars(Events).items()
        if not name.startswith("_") and isinstance(value, str)
    }


@pytest.mark.unit
def test_canonical_values_are_exact() -> None:
    """Spot-check a representative constant from each domain, including the
    reconciled iteration-limit name."""
    assert Events.REQUEST_RECEIVED == "request.received"
    assert Events.REQUEST_COMPLETED == "request.completed"
    assert Events.REQUEST_FAILED == "request.failed"
    assert Events.AUTH_INVALID_KEY == "auth.invalid_key"
    assert Events.RATELIMIT_HIT == "ratelimit.hit"
    assert Events.CORS_PREFLIGHT_REJECTED == "cors.preflight_rejected"
    assert Events.AGENT_REFUSAL == "agent.refusal"
    assert Events.SQL_SAFETY_INVALID_COLUMN_NAME == "sql_safety.invalid_column_name"
    assert Events.DATA_VALIDATION_COMPLETE == "data.validation.complete"


@pytest.mark.unit
def test_iteration_limit_reconciled_to_spec_name() -> None:
    """Regression: the originally-shipped ``agent.iteration_limit_hit`` was
    renamed to the canonical ``agent.iteration_limit`` (no ``_hit``)."""
    assert Events.AGENT_ITERATION_LIMIT == "agent.iteration_limit"


@pytest.mark.unit
def test_all_event_values_are_unique() -> None:
    """No two constants may share a value — a duplicate would silently
    merge two distinct event streams under one name."""
    values = list(_event_values().values())
    assert len(values) == len(set(values))


@pytest.mark.unit
def test_all_event_names_follow_dotted_convention() -> None:
    """Every value is lowercase ``<domain>.<verb>`` with at least one dot.
    Segments may contain underscores (e.g. ``sql_safety.invalid_column_name``)."""
    pattern = re.compile(r"^[a-z_]+(?:\.[a-z_]+)+$")
    for name, value in _event_values().items():
        assert pattern.match(value), f"{name}={value!r} breaks the naming convention"
