"""Allowlists for ``query_entries`` group-by / aggregations / order-by (Fork 50).

These frozensets are the SQL-injection defense for the general builder
tool. Pydantic ``field_validator`` hooks on ``QueryEntriesInput`` reject
any value not in these sets BEFORE any string interpolation reaches
DuckDB. Combined with parameterized ``?`` placeholders for values (in
:mod:`customs_agent.tools._shared`), this means the agent literally
cannot inject SQL — the worst it can do is produce a validation error.

The lists are intentionally CURATED — not "every column in the view".
The agent only needs grouping / aggregation surfaces that map cleanly
onto the 11 case-study questions plus reasonable extensions. Adding a
new dimension here is a deliberate decision; the boot-time DESCRIBE
auto-generation (per Fork 21, landing on ``feat/agent-loop``) populates
the column-list TEXT in the tool description but does NOT widen these
safety allowlists. The two concerns are kept separate.

Aggregation naming convention:

- ``count_distinct_entries`` → ``COUNT(DISTINCT entry_number)``
- ``count_lines``            → ``COUNT(*)``
- ``sum(<col>)`` / ``avg(<col>)`` / ``min(<col>)`` / ``max(<col>)``
  → corresponding SQL aggregate over the named column.

The builder in ``query_entries.py`` parses each aggregation string,
asserts membership in :data:`ALLOWED_AGGREGATIONS`, then emits the
matching SQL fragment. No regex hacks, no string-format-style
interpolation of user values.

View column inventories (PR #5 Copilot Comment 4 follow-up):

:data:`ENTRIES_V_COLUMNS` and :data:`ENTRY_LINES_V_COLUMNS` mirror the
actual columns produced by ``backend/src/customs_agent/data/views.py``
and are consumed by the ``QueryEntriesInput`` view-compatibility
validator (Fork 21 — rejects e.g. ``view="entries_v"`` with
``country_of_origin_code`` filter, since that column is line-grain
only). The companion :data:`ENTRIES_V_ONLY` / :data:`ENTRY_LINES_V_ONLY`
set differences make the per-view checks cheap.

**These must stay in sync with ``views.py``.** The drift test in
``tests/unit/tools/test_allowlists.py`` runs ``DESCRIBE entries_v`` /
``DESCRIBE entry_lines_v`` on a live in-memory DuckDB and asserts the
constants match — failure means views.py grew or lost a column and
this file needs an update.
"""

# ─────────────────────────────────────────────────────────────────────────────
# GROUP BY allowlist — categorical and temporal dimensions only.
# Fact metrics (entered_value, primary_duty, etc.) are excluded; they
# never make sense as a GROUP BY key.
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_GROUP_BY: frozenset[str] = frozenset({
    # Customer / origin / port
    "customer_code",
    "country_of_origin_code",   # line-grain (entry_lines_v) only
    "port_of_entry_code",
    "port_of_entry_name",
    # Entry / operational
    "entry_type",
    "entry_type_code",
    "carrier",
    "pay_type",
    "on_hold",
    "hold_reason",
    # Period helpers (string form preferred; DATE-typed available too)
    "release_year_month",
    "release_year_quarter",
    "release_month",
    "release_quarter",
    # Line-grain dimensions
    "hts_code",
    "mid",
})


# ─────────────────────────────────────────────────────────────────────────────
# AGGREGATIONS allowlist — count aliases + sum/avg/min/max of numerics.
# Names track actual column identifiers in entries_v / entry_lines_v.
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_AGGREGATIONS: frozenset[str] = frozenset({
    # Counts
    "count_distinct_entries",
    "count_lines",
    # SUM — financial rollups (entries_v has "total_*" prefixes; line-grain
    # uses the raw column names).
    "sum(total_entered_value)",
    "sum(entered_value)",
    "sum(total_primary_duty)",
    "sum(primary_duty)",
    "sum(total_section_301_duty)",
    "sum(section_301_duty)",
    "sum(total_ieepa_duty)",
    "sum(ieepa_duty)",
    "sum(total_mpf_capped)",
    "sum(total_mpf_raw)",
    "sum(mpf)",
    "sum(total_hmf)",
    "sum(hmf)",
    "sum(total_duty_taxes_fees_correct)",
    "sum(total_duty_taxes_fees_line_sum)",
    "sum(total_duty_taxes_fees)",
    "sum(units)",
    # AVG — per-entry / per-line averages worth surfacing
    "avg(total_entered_value)",
    "avg(entered_value)",
    "avg(total_duty_taxes_fees_correct)",
    "avg(line_count)",
    "avg(duty_rate_pct)",
    # MIN / MAX — used for date ranges and outlier inspection
    "min(release_date)",
    "max(release_date)",
    "min(total_duty_taxes_fees_correct)",
    "max(total_duty_taxes_fees_correct)",
    "min(entered_value)",
    "max(entered_value)",
})


# ─────────────────────────────────────────────────────────────────────────────
# ORDER BY allowlist — anything you can group by, plus any aggregation
# alias (you can ORDER BY a SELECT alias in DuckDB).
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_ORDER_BY: frozenset[str] = (
    ALLOWED_GROUP_BY | ALLOWED_AGGREGATIONS
)


# ─────────────────────────────────────────────────────────────────────────────
# View column inventories (PR #5 Copilot Comment 4 follow-up).
# Must stay in sync with views.py; the drift test in
# tests/unit/tools/test_allowlists.py fails loudly on mismatch.
# ─────────────────────────────────────────────────────────────────────────────

ENTRIES_V_COLUMNS: frozenset[str] = frozenset({
    "carrier",
    "customer_code",
    "customer_name",
    "distinct_origin_count",
    "entry_filed_date",
    "entry_number",
    "entry_type",
    "entry_type_code",
    "hold_reason",
    "is_shell",
    "line_count",
    "on_hold",
    "origin_country_codes",
    "pay_type",
    "port_of_entry",
    "port_of_entry_code",
    "port_of_entry_name",
    "release_date",
    "release_month",
    "release_quarter",
    "release_year_month",
    "release_year_quarter",
    "summary_date",
    "total_duty_taxes_fees_correct",
    "total_duty_taxes_fees_line_sum",
    "total_entered_value",
    "total_hmf",
    "total_ieepa_duty",
    "total_mpf_capped",
    "total_mpf_raw",
    "total_primary_duty",
    "total_section_301_duty",
})

ENTRY_LINES_V_COLUMNS: frozenset[str] = frozenset({
    "bill_of_lading",
    "broker_reference",
    "carrier",
    "container_number",
    "country_of_origin",
    "country_of_origin_code",
    "customer_code",
    "customer_name",
    "duty_rate_pct",
    "entered_value",
    "entry_filed_date",
    "entry_number",
    "entry_type",
    "entry_type_code",
    "hmf",
    "hold_reason",
    "hts_code",
    "hts_description",
    "ieepa_code",
    "ieepa_duty",
    "invoice_tariff_line",
    "is_china_origin",
    "is_shell",
    "mid",
    "mode_of_transport",
    "mpf",
    "on_hold",
    "pay_type",
    "port_of_entry",
    "port_of_entry_code",
    "port_of_entry_name",
    "port_of_lading",
    "primary_duty",
    "release_date",
    "release_month",
    "release_quarter",
    "release_year_month",
    "release_year_quarter",
    "section_301_code",
    "section_301_duty",
    "summary_date",
    "total_duty_taxes_fees",
    "units",
    "uom",
})

# Pre-computed differences (read once at module import) — the validator
# uses these for membership checks rather than re-deriving on each call.
ENTRIES_V_ONLY: frozenset[str] = ENTRIES_V_COLUMNS - ENTRY_LINES_V_COLUMNS
ENTRY_LINES_V_ONLY: frozenset[str] = ENTRY_LINES_V_COLUMNS - ENTRIES_V_COLUMNS
