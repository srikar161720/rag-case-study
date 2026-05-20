"""Load the customs CSV into a typed DuckDB ``entry_lines`` base table (Fork 18).

The load is idempotent (``DROP TABLE IF EXISTS`` first) so re-running against
the same in-memory connection is safe. Every column is explicitly CAST from
``VARCHAR`` (DuckDB's default when ``read_csv_auto(..., all_varchar=True)``
is used) to the right type — Decimal for money fields, Date for dates,
Integer for ordinals, Boolean for ``on_hold``. The ``NULLIF('', col)`` wrap
on Section 301 and IEEPA columns converts empty strings to ``NULL`` so the
downstream ``COALESCE(SUM(...), 0)`` patterns in ``views.py`` work correctly
(KB §Quirk 1 and §Quirk 2).

Five columns are derived at load time:

- ``port_of_entry_code`` — leading digits of ``Port of Entry`` (e.g., "2704")
- ``port_of_entry_name`` — parenthesized name (e.g., "Los Angeles")
- ``entry_type_code`` — first 2 chars of ``Entry Type`` (e.g., "01")
- ``is_china_origin`` — ``country_of_origin_code = 'CN'`` boolean shortcut
"""

from pathlib import Path

import duckdb

# load.py lives at  <repo>/backend/src/customs_agent/data/load.py
# CSV lives at      <repo>/backend/data/customs_entries_oct2024_mar2025.csv
# Walk up 4 parents (data/ → customs_agent/ → src/ → backend/) then dive into data/.
CSV_PATH = Path(__file__).resolve().parents[3] / "data" / "customs_entries_oct2024_mar2025.csv"


def load_entries(
    con: duckdb.DuckDBPyConnection,
    csv_path: Path = CSV_PATH,
) -> None:
    """Create the typed ``entry_lines`` table from the source CSV.

    Parameters
    ----------
    con
        An open DuckDB connection (typically ``duckdb.connect(":memory:")``).
    csv_path
        Override path to the CSV. Defaults to the committed
        ``backend/data/customs_entries_oct2024_mar2025.csv``.
    """
    con.execute("DROP TABLE IF EXISTS entry_lines")
    con.execute(
        """
        CREATE TABLE entry_lines AS
        SELECT
            "Entry Number"                                              AS entry_number,
            "Broker Reference"                                          AS broker_reference,
            "Customer Name"                                             AS customer_name,
            "Customer Code"                                             AS customer_code,
            CAST("Entry Filed Date" AS DATE)                            AS entry_filed_date,
            CAST("Release Date" AS DATE)                                AS release_date,
            CAST("Summary Date" AS DATE)                                AS summary_date,
            "Port of Entry"                                             AS port_of_entry,
            regexp_extract("Port of Entry", '^(\\d+)', 1)               AS port_of_entry_code,
            regexp_extract("Port of Entry", '\\(([^)]+)\\)', 1)         AS port_of_entry_name,
            "Port of Lading"                                            AS port_of_lading,
            "Mode of Transport"                                         AS mode_of_transport,
            "Carrier"                                                   AS carrier,
            "Bill of Lading"                                            AS bill_of_lading,
            "Container Number"                                          AS container_number,
            "Country of Origin Code"                                    AS country_of_origin_code,
            "Country of Origin"                                         AS country_of_origin,
            "MID"                                                       AS mid,
            CAST("Invoice Tariff Line" AS INTEGER)                      AS invoice_tariff_line,
            "Invoice Tariff - HTS Code"                                 AS hts_code,
            "Invoice Tariff - Description"                              AS hts_description,
            CAST("Invoice Line - Units" AS DECIMAL(18,4))               AS units,
            "Invoice Line - UOM"                                        AS uom,
            CAST("Invoice Tariff - Entered Value" AS DECIMAL(18,2))     AS entered_value,
            CAST("Invoice Tariff - Duty Rate (%)" AS DECIMAL(7,4))      AS duty_rate_pct,
            CAST("Invoice Tariff - Duty" AS DECIMAL(18,2))              AS primary_duty,
            -- KB §Quirk 1 + §Quirk 2: Section 301 and IEEPA fields are
            -- "populated ONLY for" applicable lines (CN for 301; release_date
            -- >= 2025-02-01 for IEEPA). In the actual CSV, this manifests as:
            --   CODE columns: empty (→ NULL via NULLIF) on non-applicable lines
            --   DUTY columns: explicit 0.00 on non-applicable lines
            -- We preserve both as-is. The CODE column is the authoritative
            -- applicability signal — use `WHERE section_301_code IS NOT NULL`
            -- to filter "lines that had Section 301 applied". The 0.00 duty
            -- on non-applicable lines is a true value (zero duty was applied),
            -- not an absence, so we leave it intact.
            NULLIF("Section 301 Code", '')                              AS section_301_code,
            CAST(NULLIF("Section 301 Duty", '') AS DECIMAL(18,2))       AS section_301_duty,
            NULLIF("IEEPA Code", '')                                    AS ieepa_code,
            CAST(NULLIF("IEEPA Duty", '') AS DECIMAL(18,2))             AS ieepa_duty,
            CAST("MPF" AS DECIMAL(18,2))                                AS mpf,
            CAST("HMF" AS DECIMAL(18,2))                                AS hmf,
            CAST("Total Duty, Taxes, Fees & Penalties" AS DECIMAL(18,2)) AS total_duty_taxes_fees,
            ("On Hold" = 'Yes')                                         AS on_hold,
            NULLIF("Hold Reason", '')                                   AS hold_reason,
            "Pay Type"                                                  AS pay_type,
            "Entry Type"                                                AS entry_type,
            substr("Entry Type", 1, 2)                                  AS entry_type_code,
            ("Country of Origin Code" = 'CN')                           AS is_china_origin
        FROM read_csv_auto(?, header=True, all_varchar=True)
        """,
        [str(csv_path)],
    )
