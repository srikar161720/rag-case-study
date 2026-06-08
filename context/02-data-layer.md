# Data Layer

Authoritative source for the data pipeline: CSV load, typed schema,
materialized views, shell-entry filter, boot-time validators, and the
ground-truth fixture.

Load this file when working on `backend/src/customs_agent/data/`,
`backend/tests/ground_truth.py`, or any tool implementation that needs to
understand the underlying schema.

---

## Dataset (provided, committed)

- **Path**: `backend/data/customs_entries_oct2024_mar2025.csv` (moved from
  root per Fork 35)
- **Grain**: one row per **tariff line** per customs entry (NOT one row
  per entry)
- **Period**: 2024-10-01 through 2025-03-31 (6 months, Release Date)
- **Rows**: 4,574 line records across 1,200 distinct entries
- **Customers**: 3 — MHF (Meridian Home Furnishings), PCA (Pacific Coast
  Apparel), SAG (Summit Athletic Gear)
- **Origin countries**: 7 — CN (1,750), VN (943), IN (790), ID (405),
  BD (362), TW (183), KR (141) lines
- **Ports of entry**: 5 — 1001 (NY/Newark), 1701 (Charleston), 2704 (LA),
  2809 (Long Beach), 5301 (Houston)
- **Carriers**: 7 — CMA CGM, COSCO, EVERGREEN, HAPAG-LLOYD, MAERSK LINE,
  MSC, ONE
- **Mode of transport**: Ocean (universal — all rows)
- **On-hold entries**: 236 of 1,200 distinct entries (~19.7%)
- **Shell entries**: 0 detected (per Fork 20 verification — all entry
  numbers are exactly 11 digits, all entered values > 0)

The CSV is provided as part of the case study materials and committed to
the repo (per Fork 11, after Fork 35 moved it into `backend/data/`).

---

## Load Pipeline (Fork 18)

The CSV is loaded once at process boot into an in-memory DuckDB database
(Fork 3). Every column gets an explicit `CAST` so the tool layer sees a
clean typed schema — no per-query coercion, no string-date comparison
bugs, no `DOUBLE`-vs-`DECIMAL` rounding drift.

### Schema decisions (the "why" behind each type)

| Source CSV column | Renamed | Type | Rationale |
|---|---|---|---|
| Entry Number | `entry_number` | `VARCHAR` | Leading zeros possible; never aggregated; keep as string |
| Broker Reference | `broker_reference` | `VARCHAR` | — |
| Customer Name | `customer_name` | `VARCHAR` | — |
| Customer Code | `customer_code` | `VARCHAR(3)` | MHF / PCA / SAG (matches `Literal` in Fork 21) |
| Entry Filed Date | `entry_filed_date` | `DATE` | Typed for range queries |
| Release Date | `release_date` | `DATE` | **Default date field per KB Rule 1** |
| Summary Date | `summary_date` | `DATE` | — |
| Port of Entry | `port_of_entry` | `VARCHAR` | Raw "2704 (Los Angeles)" form |
| (derived) | `port_of_entry_code` | `VARCHAR(4)` | `regexp_extract(port_of_entry, '^(\d+)', 1)` |
| (derived) | `port_of_entry_name` | `VARCHAR` | `regexp_extract(port_of_entry, '\(([^)]+)\)', 1)` |
| Port of Lading | `port_of_lading` | `VARCHAR` | — |
| Mode of Transport | `mode_of_transport` | `VARCHAR` | Always "Ocean" in this dataset |
| Carrier | `carrier` | `VARCHAR` | — |
| Bill of Lading | `bill_of_lading` | `VARCHAR` | — |
| Container Number | `container_number` | `VARCHAR` | — |
| Country of Origin Code | `country_of_origin_code` | `VARCHAR(2)` | CN / VN / IN / ID / BD / TW / KR |
| Country of Origin | `country_of_origin` | `VARCHAR` | Full name |
| MID | `mid` | `VARCHAR` | — |
| Invoice Tariff Line | `invoice_tariff_line` | `INTEGER` | — |
| Invoice Tariff - HTS Code | `hts_code` | `VARCHAR` | **Keep dots `XXXX.XX.XXXX` per KB §1** — never math on HTS |
| Invoice Tariff - Description | `hts_description` | `VARCHAR` | — |
| Invoice Line - Units | `units` | `DECIMAL(18,4)` | Fractional units possible per UOM |
| Invoice Line - UOM | `uom` | `VARCHAR` | NMB / KGM / DOZ / PRS / M2 / DOZ-PRS |
| Invoice Tariff - Entered Value | `entered_value` | `DECIMAL(18,2)` | **Money — never `DOUBLE`** |
| Invoice Tariff - Duty Rate (%) | `duty_rate_pct` | `DECIMAL(7,4)` | Captures 18.625% etc. |
| Invoice Tariff - Duty | `primary_duty` | `DECIMAL(18,2)` | — |
| Section 301 Code | `section_301_code` | `VARCHAR` | `NULLIF('', code)` — **NULL on non-CN lines (applicability signal)** (KB §Quirk 1) |
| Section 301 Duty | `section_301_duty` | `DECIMAL(18,2)` | `NULLIF('', val)` then CAST — **`0.00` on non-CN lines** (KB §Quirk 1). Gated by `section_301_code IS NOT NULL`, not by the duty value. |
| IEEPA Code | `ieepa_code` | `VARCHAR` | `NULLIF('', code)` — **NULL when Release Date < 2025-02-01 (applicability signal)** (KB §Quirk 2) |
| IEEPA Duty | `ieepa_duty` | `DECIMAL(18,2)` | `NULLIF('', val)` then CAST — **`0.00` when Release Date < 2025-02-01** (KB §Quirk 2). Gated by `ieepa_code IS NOT NULL`, not by the duty value. |
| MPF | `mpf` | `DECIMAL(18,2)` | **Line allocation — entry-level cap applied in `entries_v`** (KB §Quirk 3) |
| HMF | `hmf` | `DECIMAL(18,2)` | Ocean-only; no cap |
| Total Duty, Taxes, Fees & Penalties | `total_duty_taxes_fees` | `DECIMAL(18,2)` | Line-level sum (uses uncapped line-level MPF) |
| On Hold | `on_hold` | `BOOLEAN` | `("On Hold" = 'Yes')` cast |
| Hold Reason | `hold_reason` | `VARCHAR` | NULLIF |
| Pay Type | `pay_type` | `VARCHAR` | Daily / Statement |
| Entry Type | `entry_type` | `VARCHAR` | "01 - Consumption" / "06 - FTZ" |
| (derived) | `entry_type_code` | `VARCHAR(2)` | `substr(entry_type, 1, 2)` |
| (derived) | `is_china_origin` | `BOOLEAN` | `country_of_origin_code = 'CN'` — convenience flag for Tier 2 |

### Why each non-obvious choice

- **`DECIMAL(18,2)` for every money column**, never `DOUBLE`. `SUM` of
  4,574 penny-precise values in floating-point introduces drift; DECIMAL
  is exact.
- **`BOOLEAN` for `on_hold`**, not `VARCHAR`. Tools write
  `WHERE on_hold` instead of `WHERE on_hold = 'Yes'`. Single source of
  truth for the concept.
- **`NULLIF('', col)`** on Section 301 + IEEPA. The CSV uses empty strings
  for "not applicable" — converting to `NULL` makes `SUM(...)` correct
  without `CASE WHEN`. Combined with `COALESCE(SUM(...), 0)` at the
  aggregation site (Fork 19), the KB quirks become defaults.
- **Derived `port_of_entry_code` and `port_of_entry_name`**. Q3 ("top
  port") groups by port; pre-deriving avoids per-query regex.
- **Derived `is_china_origin`**. Convenience flag for the very common
  "filter to CN" pattern in Tier 2/3 questions. **Note**: the canonical
  Section 301 rule still says "filter by `country_of_origin_code = 'CN'`";
  the derived flag is shorthand, not a substitute for the rule.
- **`all_varchar=True`** in `read_csv_auto`. Forces every column to be
  read as `VARCHAR` first, so we control the `CAST` explicitly — no
  DuckDB type-inference surprises.

### Reference: load.py pattern

```python
# backend/src/customs_agent/data/load.py
from pathlib import Path
import duckdb

CSV_PATH = Path(__file__).parent.parent.parent.parent / "data" / "customs_entries_oct2024_mar2025.csv"

def load_entries(con: duckdb.DuckDBPyConnection, csv_path: Path = CSV_PATH) -> None:
    """Load the CSV into a typed `entry_lines` base table.

    Idempotent within a connection — drops the table first if it exists.
    """
    con.execute("DROP TABLE IF EXISTS entry_lines")
    con.execute("""
        CREATE TABLE entry_lines AS
        SELECT
            "Entry Number"                               AS entry_number,
            "Broker Reference"                           AS broker_reference,
            "Customer Name"                              AS customer_name,
            "Customer Code"                              AS customer_code,
            CAST("Entry Filed Date" AS DATE)             AS entry_filed_date,
            CAST("Release Date" AS DATE)                 AS release_date,
            CAST("Summary Date" AS DATE)                 AS summary_date,
            "Port of Entry"                              AS port_of_entry,
            regexp_extract("Port of Entry", '^(\\d+)', 1)             AS port_of_entry_code,
            regexp_extract("Port of Entry", '\\(([^)]+)\\)', 1)       AS port_of_entry_name,
            "Port of Lading"                             AS port_of_lading,
            "Mode of Transport"                          AS mode_of_transport,
            "Carrier"                                    AS carrier,
            "Bill of Lading"                             AS bill_of_lading,
            "Container Number"                           AS container_number,
            "Country of Origin Code"                     AS country_of_origin_code,
            "Country of Origin"                          AS country_of_origin,
            "MID"                                        AS mid,
            CAST("Invoice Tariff Line" AS INTEGER)       AS invoice_tariff_line,
            "Invoice Tariff - HTS Code"                  AS hts_code,
            "Invoice Tariff - Description"               AS hts_description,
            CAST("Invoice Line - Units" AS DECIMAL(18,4)) AS units,
            "Invoice Line - UOM"                         AS uom,
            CAST("Invoice Tariff - Entered Value" AS DECIMAL(18,2))    AS entered_value,
            CAST("Invoice Tariff - Duty Rate (%)" AS DECIMAL(7,4))     AS duty_rate_pct,
            CAST("Invoice Tariff - Duty" AS DECIMAL(18,2))             AS primary_duty,
            NULLIF("Section 301 Code", '')                             AS section_301_code,
            CAST(NULLIF("Section 301 Duty", '') AS DECIMAL(18,2))      AS section_301_duty,
            NULLIF("IEEPA Code", '')                                   AS ieepa_code,
            CAST(NULLIF("IEEPA Duty", '') AS DECIMAL(18,2))            AS ieepa_duty,
            CAST("MPF" AS DECIMAL(18,2))                               AS mpf,
            CAST("HMF" AS DECIMAL(18,2))                               AS hmf,
            CAST("Total Duty, Taxes, Fees & Penalties" AS DECIMAL(18,2)) AS total_duty_taxes_fees,
            ("On Hold" = 'Yes')                          AS on_hold,
            NULLIF("Hold Reason", '')                    AS hold_reason,
            "Pay Type"                                   AS pay_type,
            "Entry Type"                                 AS entry_type,
            substr("Entry Type", 1, 2)                   AS entry_type_code,
            ("Country of Origin Code" = 'CN')            AS is_china_origin
        FROM read_csv_auto(?, header=True, all_varchar=True);
    """, [str(csv_path)])
```

---

## Views (Fork 19)

Two materialized views sit on top of `entry_lines` at boot time. Tools
query the views, not the base table. The views encode the MPF cap,
grain distinction, period helpers, and shell-entry flag — once, in one
place.

### `entry_lines_v` — line grain enriched

```sql
CREATE VIEW entry_lines_v AS
SELECT
    el.*,
    e.is_shell,                                                    -- joined from entries_v
    DATE_TRUNC('month',   el.release_date)                  AS release_month,
    DATE_TRUNC('quarter', el.release_date)                  AS release_quarter,
    strftime(el.release_date, '%Y-%m')                      AS release_year_month,
    CAST(YEAR(el.release_date) AS VARCHAR)
        || '-Q' || CAST(QUARTER(el.release_date) AS VARCHAR) AS release_year_quarter
FROM entry_lines el
LEFT JOIN entries_v e USING (entry_number);
```

**Period helpers** (`release_month`, `release_quarter`,
`release_year_month`, `release_year_quarter`) let tools group by month
or quarter without per-query date extraction. The agent passes filter
values like `release_year_month = '2025-01'` directly.

**`is_shell` propagation**: every line carries the entry-level shell flag
via the join. Filter `WHERE NOT is_shell` works uniformly at line grain
or entry grain.

### `entries_v` — entry grain rollup (the canonical entry-level view)

```sql
CREATE VIEW entries_v AS
SELECT
    entry_number,

    -- Entry-level attributes (constant within entry; use ANY_VALUE to be explicit)
    ANY_VALUE(customer_code)        AS customer_code,
    ANY_VALUE(customer_name)        AS customer_name,
    ANY_VALUE(entry_filed_date)     AS entry_filed_date,
    ANY_VALUE(release_date)         AS release_date,
    ANY_VALUE(summary_date)         AS summary_date,
    ANY_VALUE(port_of_entry)        AS port_of_entry,
    ANY_VALUE(port_of_entry_code)   AS port_of_entry_code,
    ANY_VALUE(port_of_entry_name)   AS port_of_entry_name,
    ANY_VALUE(carrier)              AS carrier,
    ANY_VALUE(pay_type)             AS pay_type,
    ANY_VALUE(entry_type)           AS entry_type,
    ANY_VALUE(entry_type_code)      AS entry_type_code,
    BOOL_OR(on_hold)                AS on_hold,
    ANY_VALUE(hold_reason)          AS hold_reason,

    -- Period helpers (mirroring entry_lines_v)
    DATE_TRUNC('month',   ANY_VALUE(release_date))                AS release_month,
    DATE_TRUNC('quarter', ANY_VALUE(release_date))                AS release_quarter,
    strftime(ANY_VALUE(release_date), '%Y-%m')                    AS release_year_month,
    CAST(YEAR(ANY_VALUE(release_date)) AS VARCHAR)
        || '-Q' || CAST(QUARTER(ANY_VALUE(release_date)) AS VARCHAR) AS release_year_quarter,

    -- Multi-origin awareness (entries CAN span multiple countries)
    LIST(DISTINCT country_of_origin_code)         AS origin_country_codes,
    COUNT(DISTINCT country_of_origin_code)        AS distinct_origin_count,

    -- Grain summary
    COUNT(*)                                      AS line_count,

    -- Financial rollups
    SUM(entered_value)                            AS total_entered_value,
    SUM(primary_duty)                             AS total_primary_duty,
    COALESCE(SUM(section_301_duty), 0)            AS total_section_301_duty,
    COALESCE(SUM(ieepa_duty), 0)                  AS total_ieepa_duty,

    -- MPF: keep both for transparency; default to capped for downstream use
    SUM(mpf)                                      AS total_mpf_raw,
    LEAST(
        GREATEST(SUM(mpf), 31.67::DECIMAL(18,2)),
        614.35::DECIMAL(18,2)
    )                                             AS total_mpf_capped,

    SUM(hmf)                                      AS total_hmf,

    -- Two total-duty figures with distinct purposes
    SUM(total_duty_taxes_fees)                    AS total_duty_taxes_fees_line_sum,    -- matches CSV
    (
        SUM(primary_duty)
        + COALESCE(SUM(section_301_duty), 0)
        + COALESCE(SUM(ieepa_duty), 0)
        + LEAST(GREATEST(SUM(mpf), 31.67::DECIMAL(18,2)), 614.35::DECIMAL(18,2))
        + SUM(hmf)
    )                                             AS total_duty_taxes_fees_correct,

    -- Shell-entry flag (Fork 20)
    (
        LENGTH(entry_number) != 11
        OR COALESCE(SUM(entered_value), 0) = 0
    )                                             AS is_shell

FROM entry_lines
GROUP BY entry_number;
```

### Why each non-obvious choice (entries_v)

- **`total_mpf_capped` AND `total_mpf_raw`**. Capped is the correct
  entry-level economic figure (KB §Quirk 3 — $31.67 min, $614.35 max);
  raw lets us audit allocation behavior. Tools that compute entry-level
  duty totals MUST use `total_mpf_capped`.
- **Two total-duty columns**. `total_duty_taxes_fees_line_sum` matches
  the CSV's per-line column summed (uses uncapped line-level MPF, so it
  may overcount on entries with high-MPF allocations).
  `total_duty_taxes_fees_correct` applies the MPF cap. Tools default to
  `_correct`; `_line_sum` is for sanity/validation.
- **`COALESCE(SUM(section_301_duty), 0)`**. Non-CN lines have
  `section_301_duty = 0.00` in the actual CSV (the duty column is
  zero-filled on non-applicable lines; only the `section_301_code`
  column is NULL — that's the applicability signal). The `COALESCE`
  is defensive against future NULL-shaped data and against any filter
  that excludes all applicable rows; for the current zero-filled data
  it's a no-op but harmless. Same pattern applies to `ieepa_duty`.
- **`BOOL_OR(on_hold)`**. On-hold is consistent within an entry, but
  `BOOL_OR` reads as obvious intent and is robust to any data anomaly.
- **`LIST(DISTINCT country_of_origin_code)` + `distinct_origin_count`**.
  The dataset has one country per line, and an entry CAN span multiple
  countries. Exposing the list lets the agent detect mixed-origin entries
  cleanly without re-joining.
- **`is_shell` defined here, not joined**. Computed inline from
  `entry_number` length + total entered value. `entry_lines_v` joins this
  view to propagate the flag down to line grain.

### Tool grain selection rule

| If the question's filter dimension is... | Use this view |
|---|---|
| Entry-level only (customer, period, port, carrier, on_hold) | `entries_v` |
| Touches line-level (country of origin, HTS code, UOM) | `entry_lines_v` |
| Asks for `COUNT(DISTINCT entry_number)` | `entries_v` with `COUNT(*)` |
| Asks for `COUNT(*)` of lines | `entry_lines_v` with `COUNT(*)` |
| Computes entry-level financial totals | `entries_v` with `total_*_capped` columns |
| Aggregates by HTS or origin | `entry_lines_v` with the line-level financial columns |

For Q5 (effective duty rate for MHF/CN/Q1 2025): country filter →
**`entry_lines_v`**. For Q4 (Section 301 in Dec 2024): all-CN, entry-level
period filter → either view works, but `entries_v` is preferred because
it returns one row per entry which matches the question's grain.

---

## Shell-Entry Filter (Fork 20)

Per KB Rule 5: "Entries with abnormally short entry numbers (e.g., only
3 digits) or zero entered values may be 'shell entries' — placeholder
records created when the broker was not the filing party. Exclude these
from standard analytics unless specifically asked."

### Threshold (verified against dataset)

```sql
LENGTH(entry_number) != 11
OR COALESCE(SUM(entered_value), 0) = 0
```

Verification at planning time (G20):

- All 1,200 distinct entries have 11-digit entry numbers (format: filer
  code `595` + 7-digit entry + 1-digit check digit per KB §1)
- All entries have positive total entered value
- **0 shell entries detected in the current dataset**

The `LENGTH != 11` check is **stricter** than the KB's literal phrasing
("only 3 digits"). The data confirms 11 digits is the strict standard, so
any deviation is anomalous and should be flagged.

### Tool integration

Every Layer 1 + Layer 2 tool accepts `include_shell: bool = False` in its
`EntryFilters` (Fork 21). Default behavior: append `AND NOT is_shell` to
the `WHERE` clause via `build_where_clause` (`tools/_shared.py`). Override
behavior: when `include_shell=True`, the predicate is omitted.

System prompt instruction (in `prompts/behavioral.md` per Fork 27):

> "By default, shell entries (Rule 5 — abnormally short entry numbers or
> zero entered values) are excluded from analytics. If the user
> explicitly asks for all entries including shells, or asks specifically
> about shell entries, pass `include_shell=True` to the tool call."

### Boot-time verification (advisory log)

```python
# In data/validation.py
shell_count = con.execute(
    "SELECT COUNT(*) FROM entries_v WHERE is_shell"
).fetchone()[0]
log.info("shell_entries_detected", count=shell_count)
```

If `shell_count == 0` (current state), the parameter is dead-code-in-this-
dataset but still earns rule-fidelity points and is unit-tested with a
synthetic shell row.

---

## Boot-Time Validators (Fork 18 + 21)

After `load_entries()` runs, a small validation pass catches catastrophic
CSV drift before the app starts serving. Fails fast with a clear
remediation message.

```python
# backend/src/customs_agent/data/validation.py
import duckdb
from structlog import get_logger
log = get_logger()

EXPECTED_ROW_COUNT = 4574
EXPECTED_DISTINCT_ENTRIES = 1200
EXPECTED_CUSTOMERS = {"MHF", "PCA", "SAG"}
EXPECTED_COUNTRIES = {"CN", "VN", "IN", "ID", "BD", "TW", "KR"}

def validate_loaded_data(con: duckdb.DuckDBPyConnection) -> None:
    # Row count
    n = con.execute("SELECT COUNT(*) FROM entry_lines").fetchone()[0]
    assert n == EXPECTED_ROW_COUNT, (
        f"Expected {EXPECTED_ROW_COUNT} rows, got {n} — has the CSV changed?"
    )

    # Distinct entries
    e = con.execute("SELECT COUNT(DISTINCT entry_number) FROM entry_lines").fetchone()[0]
    assert e == EXPECTED_DISTINCT_ENTRIES, (
        f"Expected {EXPECTED_DISTINCT_ENTRIES} distinct entries, got {e}"
    )

    # Section 301 applicability — code present only on CN-origin lines (KB §Quirk 1).
    # The CODE column is the authoritative applicability signal; the duty column
    # is zero-filled (0.00) on non-applicable lines in the actual CSV.
    bad = con.execute("""
        SELECT COUNT(*) FROM entry_lines
        WHERE section_301_code IS NOT NULL AND country_of_origin_code != 'CN'
    """).fetchone()[0]
    assert bad == 0, "Section 301 code present on non-CN line — KB §Quirk 1 violated"

    # IEEPA applicability — code present only on release_date >= 2025-02-01 (KB §Quirk 2).
    # Same code-column-is-the-signal pattern as Section 301.
    bad = con.execute("""
        SELECT COUNT(*) FROM entry_lines
        WHERE ieepa_code IS NOT NULL AND release_date < DATE '2025-02-01'
    """).fetchone()[0]
    assert bad == 0, "IEEPA code present on pre-Feb-2025 entry — KB §Quirk 2 violated"

    # Enum drift — these feed Pydantic Literal[...] in Fork 21
    actual_customers = {r[0] for r in con.execute(
        "SELECT DISTINCT customer_code FROM entries_v"
    ).fetchall()}
    assert actual_customers == EXPECTED_CUSTOMERS, (
        f"Customer enum drift: {actual_customers} ≠ {EXPECTED_CUSTOMERS}"
    )

    actual_countries = {r[0] for r in con.execute(
        "SELECT DISTINCT country_of_origin_code FROM entry_lines_v"
    ).fetchall()}
    assert actual_countries == EXPECTED_COUNTRIES, (
        f"Country enum drift: {actual_countries} ≠ {EXPECTED_COUNTRIES}"
    )

    # Shell-entry count (advisory log only — 0 expected in current dataset)
    shells = con.execute("SELECT COUNT(*) FROM entries_v WHERE is_shell").fetchone()[0]
    log.info("data.validation.complete",
             rows=n, distinct_entries=e, shell_entries_detected=shells)
```

Failing any assertion crashes the app at boot. This is intentional — a
silently wrong dataset would compound into wrong answers everywhere. The
`/ready` endpoint (Fork 40) returns 503 if the data layer didn't load
successfully, so CI catches deploy-time drift via the smoke test.

---

## Ground-Truth Fixture (Fork 43)

`backend/tests/ground_truth.py` computes the canonical answer for each of
the 11 evaluation questions via SQL — independent of the LLM, independent
of the agent — and writes the result to `tests/ground_truth.json`. This
fixture is the **authoritative answer key** for the eval suite (Fork 8 +
46) and for `EVALUATION.md` (G5).

### Build this FIRST (Day 1, per Fork 57)

Before any agent code exists, run:

```bash
cd backend && uv run python -m tests.ground_truth > tests/ground_truth.json
```

The output answers double as a dataset sanity check — if a number looks
surprising, investigate *the data* before assuming the agent is wrong.

### Fixture shape

```json
{
  "version": "1.0.0",
  "generated_at": "2026-05-19T...",
  "dataset_sha256": "a3f1c4d2e5...",
  "questions": [
    {
      "id": 1,
      "tier": 1,
      "query": "How many customs entries were filed for Pacific Coast Apparel in January 2025?",
      "answer": {"entry_count": 142},
      "tolerance": {"entry_count": 0},
      "expected_phrases": [],
      "expected_citations": ["rule_1_date_filtering"],
      "expected_tool_name": "query_entries",
      "expected_tool_args_partial": {
        "filters": {"customer_code": "PCA", "release_year_month": "2025-01"}
      }
    },
    ... (Q2 through Q11)
  ]
}
```

### Per-question entry schema

| Field | Purpose |
|---|---|
| `id` | 1–11 matching case study numbering |
| `tier` | 1, 2, 3, or 4 — drives Fork 46 assertion shape |
| `query` | Exact question text from the case study (used by `tests/eval/test_questions.py` so the fixture is self-contained) |
| `answer` | Structured payload mirroring `tool_calls[*].result` shape (sidecar) |
| `tolerance` | Per-field — `0` (exact), `("abs", 1.0)`, or `("rel", 0.001)` |
| `expected_phrases` | Required substrings in prose (Tier 4 + KB-grounded checks) |
| `expected_citations` | Required `chunk_id`s in `knowledge_citations[]` |
| `expected_tool_name` | Required tool name in `tool_calls[*]` (architecture axis per Fork 46) |
| `expected_tool_args_partial` | Subset of args that must be present (catches "right answer via wrong filter") |
| `rubric` *(Q9 only)* | 4-component LLM-as-judge rubric (Fork 8) |

### Dataset SHA-256 pin (drift guard)

The fixture carries `dataset_sha256` — the SHA of the CSV at fixture-
generation time. The eval-suite session fixture (Fork 45 Layer 3)
computes the live CSV SHA and fails fast on mismatch:

```python
# In tests/conftest.py
@pytest.fixture(scope="session")
def ground_truth():
    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    actual = sha256(CSV_PATH.read_bytes()).hexdigest()
    if gt["dataset_sha256"] != actual:
        pytest.fail(
            f"Dataset drifted since ground truth was generated.\n"
            f"  Fixture SHA: {gt['dataset_sha256'][:12]}…\n"
            f"  Live    SHA: {actual[:12]}…\n"
            f"  Regenerate: cd backend && uv run python -m tests.ground_truth"
        )
    return gt
```

> **As-built note (`feat/remaining-tools-and-eval`)**: the pin is over the
> CSV's **byte-exact** content, so the CSV MUST stay `*.csv binary` (it is,
> in root `.gitattributes`) to keep the committed blob identical to the
> working tree. The CSV was first committed while `* text=auto` was the
> effective rule (before the `*.csv binary` line was added), so its blob
> was LF-normalized while the local working tree kept CRLF — the pin was
> generated against the CRLF bytes (`1d6df8…`), but a fresh CI checkout got
> the LF blob (`b9626d…`), so the guard above ERRORed all 16 eval cases
> (~17s, before any LLM call) on the first real `eval.yml` run. Resolved
> with `git add --renormalize backend/data/customs_entries_oct2024_mar2025.csv`
> so the blob honors `*.csv binary` and stores the CRLF bytes the pin
> targets — **no `ground_truth.json` change** (the data is byte-identical;
> only the line-ending representation was being pinned). Never let the CSV
> be text-normalized. See CLAUDE.md Critical Gotcha #24.

### When to regenerate

| Trigger | Regenerate? |
|---|---|
| Project start | ✅ once |
| CSV file changes | ✅ |
| View definitions change (Fork 19) | ✅ |
| Shell-entry threshold tightens (Fork 20) | ✅ |
| Adding a new test case | ✅ |
| Pure agent / prompt / RAG change | ❌ — ground truth doesn't depend on these |
| Frontend change | ❌ |
| CI runs | ❌ never (always loads the committed fixture) |

---

## Reference SQL Patterns for Tools

These patterns appear across multiple Layer 1 tools. Each tool's specific
SQL is documented in `04-agent-and-tools.md`.

### Pattern: parameterized filter clause

Every tool uses `build_where_clause(filters)` from `tools/_shared.py`:

```python
def build_where_clause(filters: EntryFilters) -> tuple[str, list]:
    clauses, params = [], []
    if filters.customer_code:
        clauses.append("customer_code = ?")
        params.append(filters.customer_code)
    if filters.country_of_origin_code:
        clauses.append("country_of_origin_code = ?")
        params.append(filters.country_of_origin_code)
    if filters.port_of_entry_code:
        clauses.append("port_of_entry_code = ?")
        params.append(filters.port_of_entry_code)
    if filters.release_year_month:
        clauses.append("release_year_month = ?")
        params.append(filters.release_year_month)
    if filters.release_year_quarter:
        clauses.append("release_year_quarter = ?")
        params.append(filters.release_year_quarter)
    if filters.release_date_from:
        clauses.append("release_date >= ?")
        params.append(filters.release_date_from)
    if filters.release_date_to:
        clauses.append("release_date <= ?")
        params.append(filters.release_date_to)
    if filters.on_hold is not None:
        clauses.append("on_hold = ?")
        params.append(filters.on_hold)
    if not filters.include_shell:
        clauses.append("NOT is_shell")  # Fork 20 default
    return (" AND ".join(clauses) if clauses else "TRUE"), params
```

### Pattern: SELECT-only guardrail (Fork 50)

Every tool calls `safe_execute(con, sql, params)` (from
`backend/src/customs_agent/data/safe_exec.py`), never `con.execute(...)`
directly:

```python
import re
_READ_ONLY = re.compile(r"^\s*(?:SELECT|WITH)\b", re.IGNORECASE)

class UnsafeSQLError(Exception): pass

def safe_execute(con, sql: str, params: list | None = None):
    if not _READ_ONLY.match(sql):
        raise UnsafeSQLError(f"Only SELECT/WITH allowed; got: {sql.strip()[:80]}…")
    return con.execute(sql, params or [])
```

### Pattern: Q1-style count query

```sql
SELECT COUNT(*) AS entry_count FROM entries_v
WHERE customer_code = ? AND release_year_month = ? AND NOT is_shell
```

### Pattern: Q4-style sum with Section 301 quirk

```sql
SELECT COALESCE(SUM(total_section_301_duty), 0) AS section_301_total
FROM entries_v
WHERE release_year_month = ? AND NOT is_shell
```

### Pattern: Q5-style effective rate (line grain because origin is line-level)

```sql
SELECT
    CAST(SUM(total_duty_taxes_fees) AS DOUBLE)
    / NULLIF(SUM(entered_value), 0) * 100.0
    AS effective_rate_pct
FROM entry_lines_v
WHERE customer_code = ?
  AND country_of_origin_code = ?
  AND release_year_quarter = ?
  AND NOT is_shell
```

### Pattern: Q6-style hold rate with benchmark

```sql
SELECT
    COUNT(*)                                              AS total_entries,
    COUNT(*) FILTER (WHERE on_hold)                       AS entries_on_hold,
    COUNT(*) FILTER (WHERE on_hold) * 100.0
        / NULLIF(COUNT(*), 0)                             AS hold_rate_pct
FROM entries_v
WHERE NOT is_shell
```

Plus Python-side classification: `status = "warrants_investigation" if
rate > 8 else ("above" if rate > 5 else "below")` per KB §Hold Rate.

### Pattern: Q11-style entry vs line count contrast

Two queries, one per grain:

```sql
SELECT COUNT(*) AS entry_count FROM entries_v
WHERE customer_code = 'MHF' AND release_year_month = '2024-11' AND NOT is_shell;

SELECT COUNT(*) AS line_count FROM entry_lines_v
WHERE customer_code = 'MHF' AND release_year_month = '2024-11' AND NOT is_shell;
```

Agent prose contrasts the two and cites Rule 2.

---

## Composition with Other Layers

- **`04-agent-and-tools.md`**: tools query `entry_lines_v` / `entries_v`
  via parameterized SQL through `build_where_clause` + `safe_execute`.
  Column-name allowlists in `query_entries` reference columns from this
  layer.
- **`03-rag-layer.md`**: the knowledge corpus describes this data layer
  via the Data Dictionary chunks; the always-on context includes a
  compact schema overview.
- **`08-cicd-and-testing.md`**: Fork 45 Layer 1 unit tests live in
  `tests/unit/data/` and verify load schema, view definitions, validators.
- **`10-observability.md`**: every tool's `ToolMeta.sql_executed` records
  the literal SQL run for audit and reviewer verification.

---

## Future Work (data layer)

| Item | Trigger |
|---|---|
| ETL → parquet at build time for faster boot | When CSV grows beyond ~50K rows |
| Monthly / quarterly customer rollup tables (materialized) | When sustained sub-second tool latency becomes a hard requirement |
| HTS-level rollup tables | Same |
| Read-only DuckDB connection sandbox | Move to file-backed DB or real warehouse with row-level security |
| Per-query statement timeout | Production scale where bad queries could lock resources |
| Row-level security policies | Multi-tenant production deployment |
| Query plan inspection (`EXPLAIN` gating) | Genuine engineering need (not demo scale) |
