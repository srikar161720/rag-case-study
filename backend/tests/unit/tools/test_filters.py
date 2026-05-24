"""Tests for the ``EntryFilters`` Pydantic model (Fork 21).

These tests defend the schema-level invalid-argument refusal: invalid
customer / country / port codes must fail at the Anthropic tool-use
boundary, never reach the SQL builder. The agent literally cannot call
a tool with an unknown enum value if these tests stay green.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from customs_agent.tools._filters import (
    CountryCode,
    CustomerCode,
    EntryFilters,
    PortCode,
)

# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_empty_filters_parses() -> None:
    """No fields specified → defaults applied; include_shell=False."""
    f = EntryFilters()
    assert f.include_shell is False
    assert f.customer_code is None
    assert f.country_of_origin_code is None
    assert f.port_of_entry_code is None
    assert f.release_date_from is None
    assert f.release_date_to is None
    assert f.release_year_month is None
    assert f.release_year_quarter is None
    assert f.on_hold is None


@pytest.mark.unit
@pytest.mark.parametrize("code", ["MHF", "PCA", "SAG"])
def test_valid_customer_codes(code: str) -> None:
    assert EntryFilters(customer_code=code).customer_code == code  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize("code", ["CN", "VN", "IN", "ID", "BD", "TW", "KR"])
def test_valid_country_codes(code: str) -> None:
    assert EntryFilters(country_of_origin_code=code).country_of_origin_code == code  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.parametrize("code", ["1001", "1701", "2704", "2809", "5301"])
def test_valid_port_codes(code: str) -> None:
    assert EntryFilters(port_of_entry_code=code).port_of_entry_code == code  # type: ignore[arg-type]


@pytest.mark.unit
def test_valid_period_year_month_pattern() -> None:
    assert EntryFilters(release_year_month="2025-01").release_year_month == "2025-01"


@pytest.mark.unit
def test_valid_period_year_quarter_pattern() -> None:
    assert EntryFilters(release_year_quarter="2025-Q1").release_year_quarter == "2025-Q1"


@pytest.mark.unit
def test_valid_date_range() -> None:
    f = EntryFilters(
        release_date_from=date(2025, 2, 1),
        release_date_to=date(2025, 3, 31),
    )
    assert f.release_date_from == date(2025, 2, 1)
    assert f.release_date_to == date(2025, 3, 31)


# ─────────────────────────────────────────────────────────────────────────────
# Invalid enum values
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_invalid_customer_code_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        EntryFilters(customer_code="MERIDIAN")  # type: ignore[arg-type]
    assert "customer_code" in str(exc.value)


@pytest.mark.unit
def test_invalid_country_code_rejected() -> None:
    with pytest.raises(ValidationError):
        EntryFilters(country_of_origin_code="FR")  # type: ignore[arg-type]


@pytest.mark.unit
def test_invalid_port_code_rejected() -> None:
    with pytest.raises(ValidationError):
        EntryFilters(port_of_entry_code="9999")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Period validators
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["2025-1", "25-01", "2025/01", "January", ""])
def test_invalid_year_month_pattern_rejected(bad: str) -> None:
    """Pattern enforces SHAPE (``YYYY-MM``), not value validity. Out-of-range
    months like ``"2025-13"`` pass the schema and produce zero rows at the
    SQL layer — acceptable per the locked Fork 21 spec."""
    with pytest.raises(ValidationError):
        EntryFilters(release_year_month=bad)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["2025-Q5", "2025-Q0", "2025-1", "2025Q1", "Q1-2025"])
def test_invalid_year_quarter_pattern_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        EntryFilters(release_year_quarter=bad)


@pytest.mark.unit
def test_date_range_from_after_to_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        EntryFilters(
            release_date_from=date(2025, 3, 1),
            release_date_to=date(2025, 2, 1),
        )
    assert "on or before" in str(exc.value)


@pytest.mark.unit
def test_multiple_period_filters_rejected() -> None:
    """A date range and a year_month together would silently AND — reject."""
    with pytest.raises(ValidationError) as exc:
        EntryFilters(
            release_date_from=date(2025, 1, 1),
            release_year_month="2025-01",
        )
    assert "at most one" in str(exc.value).lower()


@pytest.mark.unit
def test_year_month_and_quarter_together_rejected() -> None:
    with pytest.raises(ValidationError):
        EntryFilters(release_year_month="2025-01", release_year_quarter="2025-Q1")


# ─────────────────────────────────────────────────────────────────────────────
# Schema strictness
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_unknown_field_rejected() -> None:
    """extra='forbid' → the agent can't invent new filter names."""
    with pytest.raises(ValidationError) as exc:
        EntryFilters(invented_filter="oops")  # type: ignore[call-arg]
    assert "extra" in str(exc.value).lower() or "invented_filter" in str(exc.value)


@pytest.mark.unit
def test_include_shell_default_is_false() -> None:
    """Fork 20 — shells excluded by default. Defends against accidental flip."""
    assert EntryFilters().include_shell is False


# ─────────────────────────────────────────────────────────────────────────────
# Literal alias sanity (sanity check that the SoT is wired to validation.py)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_literal_aliases_are_canonical_source() -> None:
    """validation.py imports get_args(<alias>); same module here uses the
    raw type. Both must agree on cardinality."""
    from typing import get_args
    assert set(get_args(CustomerCode)) == {"MHF", "PCA", "SAG"}
    assert set(get_args(CountryCode)) == {"CN", "VN", "IN", "ID", "BD", "TW", "KR"}
    assert set(get_args(PortCode)) == {"1001", "1701", "2704", "2809", "5301"}
