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

### `top_hts_by_duty(filters, limit)` — not available on this branch
Returns the top `limit` HTS codes by total duty contribution for a
filtered set. (Lands on a later branch; do not select.)

### `compare_customers(metric, filters)` — not available on this branch
Returns customer rankings by a chosen metric (e.g., `ieepa_pct`).
(Lands on a later branch; do not select.)

### `qbr_summary(customer_code, period)` — not available on this branch
Composes a Quarterly Business Review across the standard 4 sections.
(Lands on a later branch; do not select.)

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
