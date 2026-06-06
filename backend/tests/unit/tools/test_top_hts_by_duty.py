"""Tests for ``top_hts_by_duty`` (Fork 22 — Q8)."""

import duckdb
import pytest
from pydantic import ValidationError

from customs_agent.tools._filters import EntryFilters
from customs_agent.tools.top_hts_by_duty import (
    TopHtsByDutyInput,
    top_hts_by_duty,
)
from tests.ground_truth import q8

_PCA_CN = EntryFilters(customer_code="PCA", country_of_origin_code="CN")


@pytest.mark.unit
def test_q8_matches_ground_truth(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """Top-5 HTS by duty for PCA + CN must match ``tests.ground_truth.q8``:
    same code set in the same order, each total_duty to the cent."""
    expected = q8(duckdb_con)["top_5"]
    got = top_hts_by_duty(duckdb_con, _PCA_CN, limit=5).data["top_hts"]

    assert [r["hts_code"] for r in got] == [e["hts_code"] for e in expected]
    for g, e in zip(got, expected, strict=True):
        assert g["hts_description"] == e["hts_description"]
        assert float(g["total_duty"]) == pytest.approx(float(e["total_duty"]), abs=0.01)
        assert float(g["primary_duty"]) == pytest.approx(float(e["primary_duty"]), abs=0.01)
        assert float(g["section_301"]) == pytest.approx(float(e["section_301"]), abs=0.01)
        assert float(g["ieepa"]) == pytest.approx(float(e["ieepa"]), abs=0.01)
        assert g["line_count"] == e["line_count"]
        assert float(g["entered_value"]) == pytest.approx(float(e["entered_value"]), abs=0.01)


@pytest.mark.unit
def test_ordering_is_descending_by_total_duty(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    got = top_hts_by_duty(duckdb_con, _PCA_CN, limit=5).data["top_hts"]
    duties = [float(r["total_duty"]) for r in got]
    assert duties == sorted(duties, reverse=True)


@pytest.mark.unit
def test_limit_caps_row_count(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    result = top_hts_by_duty(duckdb_con, _PCA_CN, limit=3)
    assert len(result.data["top_hts"]) == 3
    assert result.data["limit"] == 3


@pytest.mark.unit
def test_hts_codes_are_dotted(duckdb_con: duckdb.DuckDBPyConnection) -> None:
    """HTS codes are stored/returned in dotted XXXX.XX.XXXX form (KB §1)."""
    got = top_hts_by_duty(duckdb_con, _PCA_CN, limit=5).data["top_hts"]
    assert all(r["hts_code"].count(".") == 2 for r in got)


@pytest.mark.unit
def test_meta_records_entry_lines_v_view(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = top_hts_by_duty(duckdb_con, _PCA_CN, limit=5)
    assert result.meta.view_used == "entry_lines_v"
    assert "entry_lines_v" in result.meta.sql_executed


@pytest.mark.unit
def test_citations_reference_hts_format_and_section_301(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    result = top_hts_by_duty(duckdb_con, _PCA_CN, limit=5)
    chunk_ids = {c.chunk_id for c in result.citations}
    assert chunk_ids == {
        "hts_format_xxxx_xx_xxxx",
        "quirk_1_section_301_china_only",
    }


@pytest.mark.unit
def test_input_limit_bounds_enforced() -> None:
    """limit must be 1..50; extra fields forbidden."""
    with pytest.raises(ValidationError):
        TopHtsByDutyInput(limit=0)
    with pytest.raises(ValidationError):
        TopHtsByDutyInput(limit=51)
    with pytest.raises(ValidationError):
        TopHtsByDutyInput(bogus="x")  # type: ignore[call-arg]
    # Valid construction with default limit.
    assert TopHtsByDutyInput().limit == 5
