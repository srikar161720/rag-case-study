"""Knowledge lookup tool (Fork 22 — serves Q10 + meta questions).

Thin wrapper over :class:`customs_agent.rag.retriever.HybridRetriever`
that returns retrieved chunks in the standard :class:`ToolResult`
envelope. The tool itself does no synthesis — the LLM narrates the
returned chunk text.

Reach for ``lookup_knowledge`` only when the user asks about a concept
NOT already in the always-on block (rules / quirks / metrics). Per
``context/03-rag-layer.md``, the always-on context covers those three
kinds; the topical chunks (concepts, duty programs, customer profiles,
QBR template, column definitions, relationships) are what
``lookup_knowledge`` surfaces.

Tool output ``data`` shape::

    [
        {
            "chunk_id":      str,
            "doc":           str,
            "section_id":    str,
            "section_title": str,
            "text":          str,    # enriched chunk text (DOCUMENT/SECTION header + body)
        },
        ...
    ]
"""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from customs_agent.tools._shared import (
    ToolMeta,
    ToolResult,
    now_ms,
)

TOOL_NAME = "lookup_knowledge"

DESCRIPTION = (
    "Retrieve domain-knowledge chunks via hybrid BM25 + semantic search. "
    "Use for definitional / rule questions (e.g., 'which date field should "
    "I use?') and for meta questions about how the data is structured.\n\n"
    "The always-on context already includes the 6 Business Rules, the 4 "
    "Data Quirks, and the 4 Metric Definitions, so reach for this tool only "
    "when the user asks about something NOT in those three blocks — "
    "customer profiles, duty programs, QBR template, column definitions, "
    "or relationships.\n\n"
    "Returns a list of chunks (chunk_id, doc, section, title, text). The "
    "tool performs no synthesis; the LLM narrates the returned text."
)


class LookupKnowledgeInput(BaseModel):
    """Input schema for ``lookup_knowledge``."""

    query: str = Field(min_length=1, max_length=2000, description="Natural-language search query.")
    top_k: int = Field(default=5, ge=1, le=20, description="How many chunks to retrieve.")
    model_config = ConfigDict(extra="forbid")


class _RetrieverProtocol(Protocol):
    """Minimal interface for the injected retriever — keeps the tool decoupled
    from the concrete ``HybridRetriever`` import surface and lets tests pass
    a stub without round-tripping through ChromaDB / BM25."""

    def retrieve(self, query: str, k: int = ...) -> list[Any]: ...  # pragma: no cover


def lookup_knowledge(
    retriever: _RetrieverProtocol,
    query: str,
    top_k: int = 5,
) -> ToolResult:
    """Run hybrid retrieval and return the result in the ``ToolResult`` shape."""
    t0 = now_ms()
    results = retriever.retrieve(query, k=top_k)
    latency = now_ms() - t0

    data = [
        {
            "chunk_id": r.chunk.chunk_id,
            "doc": r.chunk.doc,
            "section_id": r.chunk.section_id,
            "section_title": r.chunk.section_title,
            "text": r.chunk.text,
        }
        for r in results
    ]

    return ToolResult(
        data=data,
        meta=ToolMeta(
            tool_name=TOOL_NAME,
            sql_executed=None,
            view_used=None,
            filters_applied={"query": query, "top_k": top_k},
            shell_entries_excluded=0,
            rows_inspected=len(results),
            latency_ms=latency,
        ),
        # No citations on the tool's logic — the returned chunks are
        # themselves the citation source; the agent loop's sidecar
        # builder converts them into Citation entries.
        citations=[],
    )
