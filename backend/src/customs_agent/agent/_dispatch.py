"""Tool dispatch table for the agent loop.

The 5 tools registered in :data:`customs_agent.tools.TOOL_REGISTRY`
have heterogeneous dependencies — SQL tools need a DuckDB connection;
:func:`lookup_knowledge` needs a :class:`HybridRetriever`. This module
owns the per-tool wrappers that:

1. Parse the raw input dict (Anthropic's ``tool_use.input``) through
   the tool's Pydantic input model — re-running validation at runtime
   is cheap and catches LLM-generated args that don't match the
   schema (e.g., misspelled field names that slipped through if the
   Anthropic API ever loosened ``input_schema`` enforcement).
2. Bind the right dependency from :class:`customs_agent.agent.bootstrap.AgentContext`.
3. Call the tool function with the unpacked, type-coerced fields.

The wrappers live as module-level functions (not lambdas) so stack
traces in production point at a real symbol — useful when a tool
raises mid-loop.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from customs_agent.tools._shared import ToolResult
from customs_agent.tools.effective_duty_rate import (
    EffectiveDutyRateInput,
    effective_duty_rate,
)
from customs_agent.tools.hold_summary import (
    HoldSummaryInput,
    hold_summary,
)
from customs_agent.tools.lookup_knowledge import (
    LookupKnowledgeInput,
    lookup_knowledge,
)
from customs_agent.tools.query_entries import (
    QueryEntriesInput,
    query_entries,
)
from customs_agent.tools.total_duty_breakdown import (
    TotalDutyBreakdownInput,
    total_duty_breakdown,
)

if TYPE_CHECKING:
    from customs_agent.agent.bootstrap import AgentContext

log = structlog.get_logger()


def _exec_effective_duty_rate(ctx: "AgentContext", raw_input: dict[str, Any]) -> ToolResult:
    inp = EffectiveDutyRateInput.model_validate(raw_input)
    return effective_duty_rate(ctx.con, inp.filters)


def _exec_total_duty_breakdown(ctx: "AgentContext", raw_input: dict[str, Any]) -> ToolResult:
    inp = TotalDutyBreakdownInput.model_validate(raw_input)
    return total_duty_breakdown(ctx.con, inp.filters)


def _exec_hold_summary(ctx: "AgentContext", raw_input: dict[str, Any]) -> ToolResult:
    inp = HoldSummaryInput.model_validate(raw_input)
    return hold_summary(ctx.con, inp.filters)


def _exec_query_entries(ctx: "AgentContext", raw_input: dict[str, Any]) -> ToolResult:
    inp = QueryEntriesInput.model_validate(raw_input)
    return query_entries(
        ctx.con,
        view=inp.view,
        filters=inp.filters,
        group_by=inp.group_by,
        aggregations=inp.aggregations,
        order_by=inp.order_by,
        limit=inp.limit,
    )


def _exec_lookup_knowledge(ctx: "AgentContext", raw_input: dict[str, Any]) -> ToolResult:
    inp = LookupKnowledgeInput.model_validate(raw_input)
    return lookup_knowledge(ctx.retriever, query=inp.query, top_k=inp.top_k)


# Name → handler. Mirrors the 5 entries in TOOL_REGISTRY. Adding a new
# tool requires touching this dict AND TOOL_REGISTRY (intentional —
# keeps the two layers explicit; mismatches are caught by
# test_dispatch's "all registered tools dispatch" coverage).
_DispatchHandler = Callable[["AgentContext", dict[str, Any]], ToolResult]

_DISPATCH: dict[str, _DispatchHandler] = {
    "effective_duty_rate":  _exec_effective_duty_rate,
    "total_duty_breakdown": _exec_total_duty_breakdown,
    "hold_summary":         _exec_hold_summary,
    "query_entries":        _exec_query_entries,
    "lookup_knowledge":     _exec_lookup_knowledge,
}


def execute_tool(
    ctx: "AgentContext",
    tool_name: str,
    raw_input: dict[str, Any],
) -> ToolResult:
    """Validate ``raw_input`` and dispatch to the matching tool function.

    Parameters
    ----------
    ctx
        Bundle of runtime deps; the handler picks ``ctx.con`` or
        ``ctx.retriever`` per tool.
    tool_name
        Anthropic's ``tool_use.name`` field — must be in :data:`_DISPATCH`.
    raw_input
        Anthropic's ``tool_use.input`` dict; passed through the tool's
        Pydantic input model for validation before the tool runs.

    Returns
    -------
    ToolResult
        Standard envelope; the loop turns this into a ``tool_result``
        block to send back to the LLM.

    Raises
    ------
    ValueError
        If ``tool_name`` is not registered. The loop catches this and
        feeds the error back to the LLM so it can retry with a valid
        tool name.
    pydantic.ValidationError
        If ``raw_input`` doesn't match the tool's input model. Same
        recovery path — loop catches, feeds back, LLM corrects.
    """
    handler = _DISPATCH.get(tool_name)
    if handler is None:
        raise ValueError(
            f"Unknown tool: {tool_name!r}. Registered: {sorted(_DISPATCH)}"
        )
    log.info("agent.tool_dispatch", tool=tool_name)
    return handler(ctx, raw_input)
