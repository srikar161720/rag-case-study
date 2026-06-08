"""Tests for ``compare_customers`` (Fork 22 — Q7)."""

from datetime import date

import duckdb
import pytest
from pydantic import ValidationError

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools.compare_customers import (
    CompareCustomersInput,
    compare_customers,
)
from tests.ground_truth import q7

_FEB_MAR = EntryFilters(
    release_date_from=date(2025, 2, 1),
    release_date_to=date(2025, 3, 31),
)


@pytest.mark.unit
def test_q7_matches_ground_truth(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """IEEPA % ranking across customers must match ``tests.ground_truth.q7``:
    same customer order, same highest, each ieepa_pct within rel tolerance."""
    expected = q7(duckdb_con)
    got = compare_customers(duckdb_con, "ieepa_pct", _FEB_MAR).data

    assert got["highest_customer_code"] == expected["highest_customer_code"]
    assert [r["customer_code"] for r in got["ranked"]] == [
        e["customer_code"] for e in expected["ranked"]
    ]
    for g, e in zip(got["ranked"], expected["ranked"], strict=True):
        assert g["rank"] == e["rank"]
        assert g["ieepa_pct"] == pytest.approx(e["ieepa_pct"], rel=0.001)
        assert float(g["ieepa"]) == pytest.approx(float(e["ieepa"]), abs=0.01)
        assert float(g["total_duty"]) == pytest.approx(float(e["total_duty"]), abs=0.01)


@pytest.mark.unit
def test_ranking_is_descending(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    got = compare_customers(duckdb_con, "ieepa_pct", _FEB_MAR).data["ranked"]
    pcts = [r["ieepa_pct"] for r in got]
    assert pcts == sorted(pcts, reverse=True)
    assert [r["rank"] for r in got] == list(range(1, len(got) + 1))


@pytest.mark.unit
def test_all_three_customers_present(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    got = compare_customers(duckdb_con, "ieepa_pct", _FEB_MAR).data["ranked"]
    assert {r["customer_code"] for r in got} == {"MHF", "PCA", "SAG"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "metric",
    ["section_301_pct", "effective_duty_rate_pct", "total_duty", "entry_count"],
)
def test_other_metrics_rank_descending(
    duckdb_con: duckdb.DuckDBPyConnection, metric: str
) -> None:
    got = compare_customers(duckdb_con, metric, _FEB_MAR).data  # type: ignore[arg-type]
    values = [float(r[metric]) for r in got["ranked"]]
    assert values == sorted(values, reverse=True)
    assert got["highest_customer_code"] == got["ranked"][0]["customer_code"]


@pytest.mark.unit
def test_rejects_country_of_origin_filter() -> None:
    """compare_customers is entry-grain; a line-grain country filter is rejected
    at the input boundary with a message that names the grain."""
    with pytest.raises(ValidationError, match="country_of_origin_code"):
        CompareCustomersInput(
            metric="ieepa_pct",
            filters=EntryFilters(country_of_origin_code="CN"),
        )


@pytest.mark.unit
def test_rejects_customer_code_filter() -> None:
    """The tool ranks ALL customers — a customer_code filter would collapse it
    to a single customer, so it's rejected at the input boundary (not just
    documented)."""
    with pytest.raises(ValidationError, match="customer_code"):
        CompareCustomersInput(
            metric="ieepa_pct",
            filters=EntryFilters(customer_code="MHF"),
        )


@pytest.mark.unit
def test_metric_is_required() -> None:
    with pytest.raises(ValidationError):
        CompareCustomersInput()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        CompareCustomersInput(metric="not_a_metric")  # type: ignore[arg-type]


@pytest.mark.unit
def test_meta_records_entries_v_view(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = compare_customers(duckdb_con, "ieepa_pct", _FEB_MAR)
    assert result.meta.view_used == "entries_v"
    assert "entries_v" in result.meta.sql_executed


@pytest.mark.unit
def test_citations_reference_ieepa_quirk_and_rate_metric(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = compare_customers(duckdb_con, "ieepa_pct", _FEB_MAR)
    chunk_ids = {c.chunk_id for c in result.citations}
    assert chunk_ids == {
        "quirk_2_ieepa_feb_2025",
        "metric_effective_duty_rate",
    }
