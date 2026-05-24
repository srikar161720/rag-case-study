"""Pydantic filter model for tool inputs (Fork 21).

Every domain tool (``effective_duty_rate``, ``total_duty_breakdown``,
``hold_summary``, ``query_entries``, …) accepts a single ``EntryFilters``
argument so the agent has one consistent shape to fill in. The
``Literal`` enums on customer / country / port make invalid argument
values a schema-level failure at Anthropic's tool-use boundary — the
LLM literally cannot emit ``customer_code="Meridian"`` when the type is
``Literal["MHF", "PCA", "SAG"]``, so the tool is never called with
junk.

The data-layer validator (``customs_agent.data.validation``) re-uses
these ``Literal`` aliases via ``typing.get_args`` so the single source
of truth for accepted values is THIS file. A new country code in the
data without an update here fails boot loudly.

Asymmetric enum policy: only dimensions the agent reasons about
per-value get a ``Literal``. Operational dimensions (carrier,
hold_reason, entry_type) stay as free strings — see context/04-
agent-and-tools.md §"Asymmetric enum policy" for the rationale.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Enum aliases (single source of truth — imported by validation.py via
# typing.get_args; do not duplicate values in any other module).
# ─────────────────────────────────────────────────────────────────────────────

CustomerCode = Literal["MHF", "PCA", "SAG"]
CountryCode = Literal["CN", "VN", "IN", "ID", "BD", "TW", "KR"]
PortCode = Literal["1001", "1701", "2704", "2809", "5301"]


class EntryFilters(BaseModel):
    """Common filter shape applied to every tool's WHERE clause.

    All fields are optional except ``include_shell``, which defaults to
    ``False`` (KB Business Rule 5 — shell entries are placeholder
    records and excluded from standard analytics). The agent flips it to
    ``True`` only when the user asks explicitly.

    Period filters: pass at most one of
    ``release_date_from/release_date_to``, ``release_year_month``,
    ``release_year_quarter``. The :py:meth:`_check_period_exclusivity`
    validator rejects combinations.
    """

    customer_code: CustomerCode | None = None
    country_of_origin_code: CountryCode | None = None  # line-grain filter
    port_of_entry_code: PortCode | None = None

    release_date_from: date | None = None
    release_date_to: date | None = None
    release_year_month: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}$"
    )
    release_year_quarter: str | None = Field(
        default=None, pattern=r"^\d{4}-Q[1-4]$"
    )

    on_hold: bool | None = None
    include_shell: bool = False  # Fork 20 default

    # Reject unknown field names: the agent must not invent filters.
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _check_date_range_coherence(self) -> "EntryFilters":
        """Range ``from`` must be ≤ ``to`` when both are set.

        A ``from > to`` filter would silently produce an empty result —
        better to fail at the schema boundary so the agent sees the
        error and corrects.
        """
        if (
            self.release_date_from is not None
            and self.release_date_to is not None
            and self.release_date_from > self.release_date_to
        ):
            raise ValueError(
                f"release_date_from ({self.release_date_from}) must be "
                f"on or before release_date_to ({self.release_date_to})"
            )
        return self

    @model_validator(mode="after")
    def _check_period_exclusivity(self) -> "EntryFilters":
        """At most one period filter shape may be set.

        Allowing both a date range AND a year-month would silently AND
        them and could double-restrict (or worse, contradict each other).
        Reject up front.
        """
        date_range_set = (
            self.release_date_from is not None
            or self.release_date_to is not None
        )
        ym_set = self.release_year_month is not None
        yq_set = self.release_year_quarter is not None
        active = sum([date_range_set, ym_set, yq_set])
        if active > 1:
            raise ValueError(
                "Pass at most one of: release_date_from/release_date_to, "
                "release_year_month, release_year_quarter"
            )
        return self
