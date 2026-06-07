"""Layer-2 integration tests: the real agent loop with a stubbed LLM.

Exercises :func:`customs_agent.agent.loop.run_agent` end-to-end against
the REAL tools + REAL DuckDB + REAL citation assembly — only the LLM is
scripted (via :mod:`tests.integration.stub_llm`). This is the Fork 45
Layer 2 surface: it catches control-flow + wiring bugs the isolated unit
tests can't (does the loop dispatch the 3 new tools? does the Fork-28
citation merge surface tool-declared + lookup citations?).

Hermetic: builds its own ``AgentContext`` with a fake retriever, so no
app boot and no RAG index are needed (and no real LLM cost). The 17
loop-mechanics cases (dedup, iteration cap, refusal, etc.) live in
``tests/unit/agent/test_loop.py``; this module focuses on the 3 Day-4
tools and the citation merge.
"""

from collections.abc import Callable

import duckdb
import pytest

from customs_agent.agent.bootstrap import (
    AgentContext,
    build_tool_definitions,
    compute_always_on_chunk_ids,
)
from customs_agent.agent.loop import run_agent
from customs_agent.data.load import load_entries
from customs_agent.data.validation import validate_loaded_data
from customs_agent.data.views import create_views
from customs_agent.rag.chunker import Chunk, parse_chunks
from tests._fakes import FakeAnthropicClient, FakeRetriever
from tests.integration.stub_llm import TextTurn, ToolUseTurn, build_stub_client

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped real substrate (DuckDB + tool defs + always-on ids)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def loop_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)
    return con


@pytest.fixture(scope="module")
def all_chunks() -> list[Chunk]:
    return parse_chunks()


@pytest.fixture
def make_ctx(
    loop_con: duckdb.DuckDBPyConnection,
) -> Callable[[FakeAnthropicClient, list[Chunk] | None], AgentContext]:
    """Factory: build a real AgentContext with a scripted client + fake
    retriever. Tool definitions + always-on ids are built from the live
    DuckDB, exactly as production bootstrap does."""

    def _make(
        client: FakeAnthropicClient, retrieved: list[Chunk] | None = None
    ) -> AgentContext:
        return AgentContext(
            con=loop_con,
            retriever=FakeRetriever(chunks_to_return=list(retrieved or [])),  # type: ignore[arg-type]
            client=client,  # type: ignore[arg-type]
            tool_definitions=build_tool_definitions(loop_con),
            always_on_chunk_ids=compute_always_on_chunk_ids(),
        )

    return _make


# ─────────────────────────────────────────────────────────────────────────────
# The 3 Day-4 tools dispatch end-to-end through the real loop
# ─────────────────────────────────────────────────────────────────────────────


def test_top_hts_by_duty_dispatched_with_real_result(make_ctx) -> None:
    client = build_stub_client(
        ToolUseTurn(
            "top_hts_by_duty",
            {"filters": {"customer_code": "PCA", "country_of_origin_code": "CN"}, "limit": 5},
        ),
        TextTurn("Top HTS code is 6104.63.2006 [1]."),
    )
    ctx = make_ctx(client, None)
    resp = run_agent(ctx, user_message="top 5 HTS for PCA from China", history=[], request_id="r1")

    assert [tc.name for tc in resp.tool_calls] == ["top_hts_by_duty"]
    top = resp.tool_calls[0].result["top_hts"]
    assert len(top) == 5
    assert top[0]["hts_code"] == "6104.63.2006"
    # Tool-declared citations surface in knowledge_citations (Fork 28 merge).
    cited = {c.chunk_id for c in resp.knowledge_citations}
    assert {"hts_format_xxxx_xx_xxxx", "quirk_1_section_301_china_only"} <= cited


def test_compare_customers_dispatched_with_real_result(make_ctx) -> None:
    client = build_stub_client(
        ToolUseTurn(
            "compare_customers",
            {
                "metric": "ieepa_pct",
                "filters": {"release_date_from": "2025-02-01", "release_date_to": "2025-03-31"},
            },
        ),
        TextTurn("MHF has the highest IEEPA exposure [1]."),
    )
    ctx = make_ctx(client, None)
    resp = run_agent(ctx, user_message="compare IEEPA", history=[], request_id="r2")

    assert [tc.name for tc in resp.tool_calls] == ["compare_customers"]
    assert resp.tool_calls[0].result["highest_customer_code"] == "MHF"
    cited = {c.chunk_id for c in resp.knowledge_citations}
    assert {"quirk_2_ieepa_feb_2025", "metric_effective_duty_rate"} <= cited


def test_qbr_summary_dispatched_with_real_result(make_ctx) -> None:
    client = build_stub_client(
        ToolUseTurn("qbr_summary", {"customer_code": "SAG", "period": "2025-Q1"}),
        TextTurn("Here is the SAG Q1 2025 QBR [1] [2] [3]."),
    )
    ctx = make_ctx(client, None)
    resp = run_agent(ctx, user_message="QBR for SAG Q1 2025", history=[], request_id="r3")

    assert [tc.name for tc in resp.tool_calls] == ["qbr_summary"]
    result = resp.tool_calls[0].result
    assert set(result.keys()) == {
        "entry_volume_by_month", "duty_breakdown", "top_countries", "hold_summary",
    }
    cited = {c.chunk_id for c in resp.knowledge_citations}
    assert {
        "qbr_structure", "metric_hold_rate_benchmark", "metric_effective_duty_rate",
    } <= cited


# ─────────────────────────────────────────────────────────────────────────────
# Fork-28 citation merge — the three sources combine + dedup
# ─────────────────────────────────────────────────────────────────────────────


def test_lookup_knowledge_chunks_become_citations(make_ctx, all_chunks) -> None:
    """lookup_knowledge declares no citations — its returned chunks ARE the
    citations and must surface in knowledge_citations[]."""
    rule_1 = next(c for c in all_chunks if c.chunk_id == "rule_1_date_filtering")
    client = build_stub_client(
        ToolUseTurn("lookup_knowledge", {"query": "which date field for monthly queries"}),
        TextTurn("Use Release Date by default [1]."),
    )
    # Fake retriever returns rule_1 for ANY query, so lookup_knowledge returns it.
    ctx = make_ctx(client, [rule_1])
    resp = run_agent(ctx, user_message="which date field?", history=[], request_id="r4")

    assert [tc.name for tc in resp.tool_calls] == ["lookup_knowledge"]
    cited = {c.chunk_id for c in resp.knowledge_citations}
    assert "rule_1_date_filtering" in cited
    # The lookup-derived citation carries a real snippet (not the empty
    # placeholder used for tool-declared citations).
    rule_1_cit = next(c for c in resp.knowledge_citations if c.chunk_id == "rule_1_date_filtering")
    assert rule_1_cit.snippet != ""


def test_rag_and_tool_citations_merge_and_dedup(make_ctx, all_chunks) -> None:
    """Retrieved chunks + a tool's declared citations both land in
    knowledge_citations, deduped by chunk_id, with a contiguous 1..N id
    range and tool_calls continuing the namespace."""
    # qbr_structure is NOT always-on, so it survives retrieval dedup.
    qbr = next(c for c in all_chunks if c.chunk_id == "qbr_structure")
    client = build_stub_client(
        ToolUseTurn("hold_summary", {"filters": {}}),
        TextTurn("Hold rate computed [1]."),
    )
    ctx = make_ctx(client, [qbr])
    resp = run_agent(ctx, user_message="hold rate", history=[], request_id="r5")

    cited = [c.chunk_id for c in resp.knowledge_citations]
    # RAG-retrieved chunk + hold_summary's two declared citations.
    assert "qbr_structure" in cited
    assert "metric_hold_rate_benchmark" in cited
    assert "rule_6_on_hold_entries" in cited
    assert len(cited) == len(set(cited)), "citations deduped by chunk_id"

    n_cit = len(resp.knowledge_citations)
    assert [c.id for c in resp.knowledge_citations] == list(range(1, n_cit + 1))
    assert [t.id for t in resp.tool_calls] == [n_cit + 1]


def test_specialized_tool_receives_validated_args(make_ctx) -> None:
    """Args flow through the dispatch wrapper's Pydantic validation: a
    line-grain country filter on compare_customers (entry-grain) is
    rejected, the loop catches it, and the result carries an error — the
    loop never crashes (graceful degradation)."""
    client = build_stub_client(
        ToolUseTurn(
            "compare_customers",
            {"metric": "ieepa_pct", "filters": {"country_of_origin_code": "CN"}},
        ),
        TextTurn("I could not compare by country at entry grain."),
    )
    ctx = make_ctx(client, None)
    resp = run_agent(ctx, user_message="compare", history=[], request_id="r6")

    assert resp.refused is False  # graceful, not a refusal
    assert resp.tool_calls[0].name == "compare_customers"
    assert "error" in resp.tool_calls[0].result
