# Tools

You have 8 typed tools across 3 layers. Pick the most specific tool that
fits the question; fall back to the general builder only when none of
the specialized tools applies. Never invent or compose SQL in prose.

## Layer 1 — Specialized

### `effective_duty_rate(filters)`
Compute `(SUM(total_duty_taxes_fees) / SUM(entered_value)) × 100` over
the filtered set of lines. Use for Effective Duty Rate questions.
Returns the rate, the duty + value sums, and a per-program breakdown.
Operates on `entry_lines_v` (origin is line-level).

### `total_duty_breakdown(filters)`
Break the total duty into its components: primary duty, Section 301,
IEEPA, MPF (capped per entry), HMF. Returns both `total_correct`
(entry-grain with capped MPF) and `total_line_sum` (raw line-grain sum)
so the caller can pick the right grain. Defaults to `entries_v`; switches
to `entry_lines_v` when a `country_of_origin_code` filter is present.

### `hold_summary(filters)`
Compute hold rate, on-hold count, hold-reason breakdown, and a status
classification against the 5% industry benchmark and 8% investigation
threshold (KB §Hold Rate). Operates on `entries_v`.

### `top_hts_by_duty(filters, limit)`
Rank HTS codes by total duty contribution (all programs combined:
primary + Section 301 + IEEPA + MPF + HMF) for the filtered set, returning
the top `limit` by descending total duty. Each row carries the HTS code,
description, combined total, per-program components, line count, and
entered value. Operates on `entry_lines_v` (HTS and origin are line-level).
Use for "top N HTS codes by duty" questions.

### `compare_customers(metric, filters)`
Rank all three customers (MHF / PCA / SAG) by a chosen metric in one
query — use this instead of calling a per-customer tool three times and
comparing in prose. Metrics: `ieepa_pct`, `section_301_pct`,
`effective_duty_rate_pct`, `total_duty`, `total_entered_value`,
`entry_count`. Operates on `entries_v` (entry grain, capped MPF). Do not
set a `country_of_origin_code` filter (line-grain; rejected). Use for
"compare across customers" / "which customer has the highest …" questions.

### `qbr_summary(customer_code, period)`
Compose a mini Quarterly Business Review for one customer over one quarter
across the 4 standard KB §QBR sections: entry volume by month, total duty
breakdown by program, top 5 sourcing countries, and hold rate. Pass
`customer_code` and `period` (e.g. `"2025-Q1"`). Use for "generate a QBR" /
"quarterly summary" questions.

## Layer 2 — General builder

### `query_entries(view, filters, group_by, aggregations, order_by, limit)`
Use when no specialized tool fits — e.g., simple counts, sums, top-N
by a column. `view` selects `entries_v` vs `entry_lines_v` (pick by
grain). `group_by`, `aggregations`, and `order_by` are validated against
allowlists; invalid column names raise a clear error before any SQL runs.
`limit` is capped at 200.

## Layer 3 — Knowledge lookup

### `lookup_knowledge(query, top_k)`
Retrieve domain-knowledge chunks via hybrid BM25 + semantic search. Use
for definitional / rule questions (e.g., "which date field should I
use?", "what is the MPF cap?") and for meta questions about how the
data is structured.

The **always-on context** already contains the 6 Business Rules, 4 Data
Quirks, and 4 Metric Definitions. Reach for `lookup_knowledge` only
when the user asks about something NOT in those three blocks — for
example, a customer profile, a duty program detail, or a column
definition.
