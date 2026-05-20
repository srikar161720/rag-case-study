"""Create the ``entries_v`` and ``entry_lines_v`` analytical views (Fork 19, 20).

Critical gotchas encoded in these view definitions:

- **MPF cap per entry**: ``$31.67`` minimum, ``$614.35`` maximum, applied at
  the entry grain via ``LEAST(GREATEST(SUM(mpf), 31.67), 614.35)`` (KB
  §Quirk 3). Tools must compute entry-level duty totals using
  ``total_mpf_capped``, never ``total_mpf_raw``.
- **Section 301 NULL** on non-CN lines → ``COALESCE(SUM(...), 0)`` (Quirk 1).
- **IEEPA NULL** on ``release_date < 2025-02-01`` → ``COALESCE(SUM(...), 0)``
  (Quirk 2).
- **Shell entries**: ``entry_number`` length ≠ 11 OR total entered value = 0
  (Fork 20). Propagated to ``entry_lines_v`` via LEFT JOIN.

Order matters at materialization: ``entries_v`` is created first because
``entry_lines_v`` joins to it for the ``is_shell`` flag.
"""

import duckdb


def create_views(con: duckdb.DuckDBPyConnection) -> None:
    """Materialize the two canonical views on top of ``entry_lines``.

    Parameters
    ----------
    con
        An open DuckDB connection that already has ``entry_lines`` loaded
        (see :func:`customs_agent.data.load.load_entries`).
    """
    # Drop child view first so we can re-create the parent without dependency
    # complaints when this is called more than once on the same connection.
    con.execute("DROP VIEW IF EXISTS entry_lines_v")
    con.execute("DROP VIEW IF EXISTS entries_v")

    con.execute(
        """
        CREATE VIEW entries_v AS
        SELECT
            entry_number,

            -- Entry-level attributes (constant within entry; ANY_VALUE for explicitness)
            ANY_VALUE(customer_code)         AS customer_code,
            ANY_VALUE(customer_name)         AS customer_name,
            ANY_VALUE(entry_filed_date)      AS entry_filed_date,
            ANY_VALUE(release_date)          AS release_date,
            ANY_VALUE(summary_date)          AS summary_date,
            ANY_VALUE(port_of_entry)         AS port_of_entry,
            ANY_VALUE(port_of_entry_code)    AS port_of_entry_code,
            ANY_VALUE(port_of_entry_name)    AS port_of_entry_name,
            ANY_VALUE(carrier)               AS carrier,
            ANY_VALUE(pay_type)              AS pay_type,
            ANY_VALUE(entry_type)            AS entry_type,
            ANY_VALUE(entry_type_code)       AS entry_type_code,
            BOOL_OR(on_hold)                 AS on_hold,
            ANY_VALUE(hold_reason)           AS hold_reason,

            -- Period helpers (mirroring entry_lines_v)
            DATE_TRUNC('month',   ANY_VALUE(release_date))                  AS release_month,
            DATE_TRUNC('quarter', ANY_VALUE(release_date))                  AS release_quarter,
            strftime(ANY_VALUE(release_date), '%Y-%m')                      AS release_year_month,
            CAST(YEAR(ANY_VALUE(release_date)) AS VARCHAR)
                || '-Q'
                || CAST(QUARTER(ANY_VALUE(release_date)) AS VARCHAR)        AS release_year_quarter,

            -- Multi-origin awareness (entries CAN span multiple countries)
            LIST(DISTINCT country_of_origin_code)            AS origin_country_codes,
            COUNT(DISTINCT country_of_origin_code)           AS distinct_origin_count,

            -- Grain summary
            COUNT(*)                                         AS line_count,

            -- Financial rollups
            SUM(entered_value)                               AS total_entered_value,
            SUM(primary_duty)                                AS total_primary_duty,
            COALESCE(SUM(section_301_duty), 0)               AS total_section_301_duty,
            COALESCE(SUM(ieepa_duty), 0)                     AS total_ieepa_duty,

            -- MPF: keep both forms for transparency. Tools must use the capped form.
            SUM(mpf)                                         AS total_mpf_raw,
            LEAST(
                GREATEST(SUM(mpf), 31.67::DECIMAL(18,2)),
                614.35::DECIMAL(18,2)
            )                                                AS total_mpf_capped,

            SUM(hmf)                                         AS total_hmf,

            -- Two total-duty figures with distinct purposes
            SUM(total_duty_taxes_fees)                       AS total_duty_taxes_fees_line_sum,
            (
                SUM(primary_duty)
                + COALESCE(SUM(section_301_duty), 0)
                + COALESCE(SUM(ieepa_duty), 0)
                + LEAST(GREATEST(SUM(mpf), 31.67::DECIMAL(18,2)), 614.35::DECIMAL(18,2))
                + SUM(hmf)
            )                                                AS total_duty_taxes_fees_correct,

            -- Shell flag (Fork 20). Computed inline so we don't need a self-join.
            (
                LENGTH(entry_number) != 11
                OR COALESCE(SUM(entered_value), 0) = 0
            )                                                AS is_shell

        FROM entry_lines
        GROUP BY entry_number
        """
    )

    con.execute(
        """
        CREATE VIEW entry_lines_v AS
        SELECT
            el.*,
            e.is_shell,
            DATE_TRUNC('month',   el.release_date)                    AS release_month,
            DATE_TRUNC('quarter', el.release_date)                    AS release_quarter,
            strftime(el.release_date, '%Y-%m')                        AS release_year_month,
            CAST(YEAR(el.release_date) AS VARCHAR)
                || '-Q' || CAST(QUARTER(el.release_date) AS VARCHAR) AS release_year_quarter
        FROM entry_lines el
        LEFT JOIN entries_v e USING (entry_number)
        """
    )
