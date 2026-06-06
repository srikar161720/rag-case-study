"""Tool registry + Anthropic tool-spec builder (Fork 22).

This module is the single import point the agent loop uses to discover
what tools exist and how to call them. Each :class:`ToolSpec` carries:

- ``name``         — the string Anthropic sends back in ``tool_use`` blocks.
- ``description``  — natural-language brief; for ``query_entries`` this
  carries ``{available_columns_*}`` placeholders that the agent-loop
  branch substitutes at app bootstrap (see decision 2 in the branch
  plan for the auto-generated column list).
- ``input_model``  — the Pydantic class whose ``model_json_schema()``
  output becomes Anthropic's ``input_schema``.
- ``function``     — the runtime callable. Signatures vary because tools
  need different dependencies: SQL tools take a
  ``duckdb.DuckDBPyConnection``; ``lookup_knowledge`` takes a retriever.
  The agent loop wires the right deps per tool.

All 8 tools are registered: the 5 from ``feat/prompts-and-tools``
(``effective_duty_rate``, ``total_duty_breakdown``, ``hold_summary``,
``query_entries``, ``lookup_knowledge``) plus the 3 specialized tools
added on ``feat/remaining-tools-and-eval`` (``top_hts_by_duty`` → Q8,
``qbr_summary`` → Q9, ``compare_customers`` → Q7). Together they cover
all 11 ground-truth questions.

Calling pattern (preview, for ``feat/agent-loop``)::

    columns_entries_v = _describe(con, "entries_v")
    columns_lines_v   = _describe(con, "entry_lines_v")
    tools_param = [
        build_anthropic_tool_def(
            spec,
            description_overrides={
                "query_entries": format_query_entries_description(
                    columns_entries_v, columns_lines_v,
                ),
            },
        )
        for spec in TOOL_REGISTRY
    ]
    client.messages.create(tools=tools_param, ...)
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from customs_agent.tools.compare_customers import (
    DESCRIPTION as _COMPARE_CUSTOMERS_DESC,
)
from customs_agent.tools.compare_customers import (
    CompareCustomersInput,
    compare_customers,
)
from customs_agent.tools.effective_duty_rate import (
    DESCRIPTION as _EFFECTIVE_DUTY_RATE_DESC,
)
from customs_agent.tools.effective_duty_rate import (
    EffectiveDutyRateInput,
    effective_duty_rate,
)
from customs_agent.tools.hold_summary import (
    DESCRIPTION as _HOLD_SUMMARY_DESC,
)
from customs_agent.tools.hold_summary import (
    HoldSummaryInput,
    hold_summary,
)
from customs_agent.tools.lookup_knowledge import (
    DESCRIPTION as _LOOKUP_KNOWLEDGE_DESC,
)
from customs_agent.tools.lookup_knowledge import (
    LookupKnowledgeInput,
    lookup_knowledge,
)
from customs_agent.tools.qbr_summary import (
    DESCRIPTION as _QBR_SUMMARY_DESC,
)
from customs_agent.tools.qbr_summary import (
    QbrSummaryInput,
    qbr_summary,
)
from customs_agent.tools.query_entries import (
    DESCRIPTION as _QUERY_ENTRIES_DESC,
)
from customs_agent.tools.query_entries import (
    QueryEntriesInput,
    query_entries,
)
from customs_agent.tools.top_hts_by_duty import (
    DESCRIPTION as _TOP_HTS_BY_DUTY_DESC,
)
from customs_agent.tools.top_hts_by_duty import (
    TopHtsByDutyInput,
    top_hts_by_duty,
)
from customs_agent.tools.total_duty_breakdown import (
    DESCRIPTION as _TOTAL_DUTY_BREAKDOWN_DESC,
)
from customs_agent.tools.total_duty_breakdown import (
    TotalDutyBreakdownInput,
    total_duty_breakdown,
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Static description of one tool registered for the agent."""

    name: str
    description: str
    input_model: type[BaseModel]
    function: Callable[..., Any]


TOOL_REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="effective_duty_rate",
        description=_EFFECTIVE_DUTY_RATE_DESC,
        input_model=EffectiveDutyRateInput,
        function=effective_duty_rate,
    ),
    ToolSpec(
        name="total_duty_breakdown",
        description=_TOTAL_DUTY_BREAKDOWN_DESC,
        input_model=TotalDutyBreakdownInput,
        function=total_duty_breakdown,
    ),
    ToolSpec(
        name="hold_summary",
        description=_HOLD_SUMMARY_DESC,
        input_model=HoldSummaryInput,
        function=hold_summary,
    ),
    ToolSpec(
        name="top_hts_by_duty",
        description=_TOP_HTS_BY_DUTY_DESC,
        input_model=TopHtsByDutyInput,
        function=top_hts_by_duty,
    ),
    ToolSpec(
        name="qbr_summary",
        description=_QBR_SUMMARY_DESC,
        input_model=QbrSummaryInput,
        function=qbr_summary,
    ),
    ToolSpec(
        name="compare_customers",
        description=_COMPARE_CUSTOMERS_DESC,
        input_model=CompareCustomersInput,
        function=compare_customers,
    ),
    ToolSpec(
        name="query_entries",
        description=_QUERY_ENTRIES_DESC,
        input_model=QueryEntriesInput,
        function=query_entries,
    ),
    ToolSpec(
        name="lookup_knowledge",
        description=_LOOKUP_KNOWLEDGE_DESC,
        input_model=LookupKnowledgeInput,
        function=lookup_knowledge,
    ),
)


def format_query_entries_description(
    columns_entries_v: list[str] | tuple[str, ...],
    columns_entry_lines_v: list[str] | tuple[str, ...],
) -> str:
    """Fill the ``{available_columns_*}`` placeholders in the
    ``query_entries`` description.

    Called by the agent-loop branch at app bootstrap, after
    ``DESCRIBE entries_v`` / ``DESCRIBE entry_lines_v`` resolve the
    actual column list. This file ships only the placeholder text; the
    auto-generation lives in app bootstrap so a future view-schema
    change is reflected without touching the tool description.

    Raises
    ------
    KeyError
        If the description template ever loses one of the two
        placeholder tokens — that would silently send unsubstituted
        text to Anthropic, so fail loudly instead.
    """
    return _QUERY_ENTRIES_DESC.format(
        available_columns_entries_v=", ".join(columns_entries_v),
        available_columns_entry_lines_v=", ".join(columns_entry_lines_v),
    )


def build_anthropic_tool_def(
    spec: ToolSpec,
    description_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one Anthropic-compatible tool spec dict from a :class:`ToolSpec`.

    Parameters
    ----------
    spec
        Registry entry to render.
    description_overrides
        Optional ``{name: description}`` mapping that replaces a
        registered tool's description before it hits Anthropic.
        Required for ``query_entries`` (the agent loop substitutes the
        placeholder column list); ignored for other tools whose
        descriptions are static.

    Returns
    -------
    dict
        Shape: ``{"name": str, "description": str, "input_schema": dict}``
        — directly passable as one element of
        ``client.messages.create(tools=[...])``.
    """
    overrides = description_overrides or {}
    description = overrides.get(spec.name, spec.description)
    return {
        "name": spec.name,
        "description": description,
        "input_schema": spec.input_model.model_json_schema(),
    }


__all__ = [
    "TOOL_REGISTRY",
    "ToolSpec",
    "build_anthropic_tool_def",
    "compare_customers",
    "effective_duty_rate",
    "format_query_entries_description",
    "hold_summary",
    "lookup_knowledge",
    "qbr_summary",
    "query_entries",
    "top_hts_by_duty",
    "total_duty_breakdown",
]
