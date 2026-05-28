"""Tests for the agent tool dispatch table.

Covers:
- Every TOOL_REGISTRY entry has a matching dispatch handler.
- Each handler routes to the right tool function with the right dep
  (DuckDB conn vs. retriever).
- Unknown tool name raises ValueError with a helpful message.
- Malformed input raises ValidationError before the tool function runs.
"""

import pytest
from pydantic import ValidationError

from customs_agent.agent._dispatch import _DISPATCH, execute_tool
from customs_agent.tools import TOOL_REGISTRY
from customs_agent.tools._shared import ToolResult

# ─────────────────────────────────────────────────────────────────────────────
# Coverage: every registered tool has a dispatch handler
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_every_registered_tool_dispatches() -> None:
    """Dispatch table must cover every TOOL_REGISTRY entry — a registered
    tool with no handler would crash mid-loop."""
    registered = {spec.name for spec in TOOL_REGISTRY}
    dispatched = set(_DISPATCH.keys())
    missing = registered - dispatched
    extra = dispatched - registered
    assert not missing, f"Registered tools without a dispatch handler: {missing}"
    assert not extra, f"Dispatch handlers for non-registered tools: {extra}"


# ─────────────────────────────────────────────────────────────────────────────
# Unknown tool / bad input — raises before any tool runs
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_unknown_tool_raises_with_helpful_message(agent_context_factory) -> None:
    ctx = agent_context_factory()
    with pytest.raises(ValueError) as exc:
        execute_tool(ctx, "not_a_real_tool", {})
    msg = str(exc.value)
    assert "not_a_real_tool" in msg
    assert "Registered" in msg
    # Lists all 5 real tools in the error so the LLM can self-correct
    for tool in (
        "effective_duty_rate", "total_duty_breakdown", "hold_summary",
        "query_entries", "lookup_knowledge",
    ):
        assert tool in msg


@pytest.mark.unit
def test_bad_input_shape_raises_validation_error(agent_context_factory) -> None:
    """Validating raw input through the tool's Pydantic input model catches
    LLM schema-mismatch errors before the tool function runs."""
    ctx = agent_context_factory()
    with pytest.raises(ValidationError):
        # query_entries requires a Literal view; "junk" is rejected
        execute_tool(ctx, "query_entries", {"view": "junk"})


# ─────────────────────────────────────────────────────────────────────────────
# Happy-path dispatch — each tool routes to the right function
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dispatch_effective_duty_rate(agent_context_factory) -> None:
    """Real dispatch into effective_duty_rate against the real DuckDB."""
    ctx = agent_context_factory()
    result = execute_tool(ctx, "effective_duty_rate", {})
    assert isinstance(result, ToolResult)
    assert result.meta.tool_name == "effective_duty_rate"
    assert result.meta.view_used == "entry_lines_v"


@pytest.mark.unit
def test_dispatch_hold_summary(agent_context_factory) -> None:
    ctx = agent_context_factory()
    result = execute_tool(ctx, "hold_summary", {})
    assert result.meta.tool_name == "hold_summary"
    assert "entries_total" in result.data


@pytest.mark.unit
def test_dispatch_total_duty_breakdown(agent_context_factory) -> None:
    ctx = agent_context_factory()
    result = execute_tool(ctx, "total_duty_breakdown", {})
    assert result.meta.tool_name == "total_duty_breakdown"


@pytest.mark.unit
def test_dispatch_query_entries_with_full_input(agent_context_factory) -> None:
    """Q3-shape input exercises every QueryEntriesInput field."""
    ctx = agent_context_factory()
    result = execute_tool(
        ctx, "query_entries",
        {
            "view": "entries_v",
            "group_by": ["port_of_entry_code", "port_of_entry_name"],
            "aggregations": ["count_distinct_entries"],
            "order_by": [("count_distinct_entries", "desc")],
            "limit": 1,
        },
    )
    assert result.meta.tool_name == "query_entries"
    assert len(result.data) == 1


@pytest.mark.unit
def test_dispatch_lookup_knowledge_uses_retriever(
    agent_context_factory,
    fake_retriever_factory,
) -> None:
    """lookup_knowledge must use ctx.retriever, NOT ctx.con. Verified by
    seeding the FakeRetriever with a known chunk and asserting it appears
    in the result."""
    from customs_agent.rag.chunker import parse_chunks
    all_chunks = parse_chunks()
    rule_chunk = next(c for c in all_chunks if c.chunk_id == "rule_1_date_filtering")
    ctx = agent_context_factory([rule_chunk])
    result = execute_tool(
        ctx, "lookup_knowledge",
        {"query": "which date field for monthly?", "top_k": 5},
    )
    assert result.meta.tool_name == "lookup_knowledge"
    assert len(result.data) == 1
    assert result.data[0]["chunk_id"] == "rule_1_date_filtering"
    # Verify the FakeRetriever was actually called
    assert ctx.retriever.call_log[-1]["query"] == "which date field for monthly?"
    assert ctx.retriever.call_log[-1]["k"] == 5
