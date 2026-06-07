"""Agent tool-calling loop (Fork 23).

The orchestrator that ties together every prior layer: pull retrieved
chunks → dedup against the always-on block → prune history to fit the
token budget → call Anthropic with prompt caching + tool definitions →
dispatch tool calls → fold tool results back into the conversation →
detect a refusal marker if present → validate citation markers →
assemble the structured sidecar.

This branch ships the SYNC variant. Streaming (Fork 29) lands later
as a separate ``run_agent_streaming`` entry point on
``feat/streaming``. Langfuse decorators (Fork 10) and the cost
estimator (G11) are deferred to ``feat/langfuse-traces``.

Three "limit hit" guards trip graceful degradation (never raises):

- ``iteration_limit_hit``: loop count hits :attr:`AgentLoopSettings.max_iterations`.
  Returns whatever final text we have plus the partial tool-call history.
- ``budget_limit_hit``: cumulative input tokens exceed
  :attr:`AgentLoopSettings.max_input_tokens` mid-loop.
- ``duplicate_tool_calls``: ``(tool_name, hash(args))`` cache hit returns
  the previous result + logs a warning + increments the counter on
  :class:`ResponseMeta`.

The function returns :class:`ChatResponse` directly — the FastAPI
endpoint on ``feat/fastapi-backend`` is a thin handler that forwards.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import structlog

from customs_agent.agent._dispatch import execute_tool
from customs_agent.agent.bootstrap import AgentContext
from customs_agent.agent.contracts import (
    Assumption,
    ChatResponse,
    Citation,
    Message,
    ResponseMeta,
    ToolCallTrace,
)
from customs_agent.agent.history import prune_history
from customs_agent.agent.prompt import PROMPT_VERSION, STATIC_SYSTEM_PROMPT
from customs_agent.agent.refusal import detect_refusal
from customs_agent.agent.validator import validate_markers

log = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
# Loop settings (matches the AGENT_* env-var defaults in config.Settings;
# the future main.py reads Settings and passes the values through here).
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentLoopSettings:
    """Per-loop tuning. Defaults match :class:`customs_agent.config.Settings`
    AGENT_* / LLM_* env-var defaults; the future ``main.py`` will read
    Settings and instantiate this with the live values."""

    model: str = "claude-sonnet-4-6"
    temperature: float = 0.0
    max_iterations: int = 5
    max_input_tokens: int = 50_000
    max_output_tokens: int = 8_000
    dedup_tool_calls: bool = True
    embedding_model: str = "text-embedding-3-small"


DEFAULT_LOOP_SETTINGS = AgentLoopSettings()


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    """Wall-clock millisecond stamp for latency measurement."""
    return int(time.perf_counter() * 1000)


def _hash_input(tool_input: dict[str, Any]) -> str:
    """Stable hash of a tool-input dict for the dedup cache key.

    JSON-serialize with sorted keys so semantically-identical inputs
    (key order doesn't matter) hash the same; falls back to ``str()``
    on values JSON can't handle (``Decimal``, ``date``, etc.) so the
    function never raises mid-loop.
    """
    canonical = json.dumps(tool_input, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _format_retrieved_chunks(retrieved: list[Any]) -> str:
    """Render retrieved chunks into the Markdown block injected below
    the cache boundary in the current user message.

    Each chunk's enriched ``text`` already carries its DOCUMENT/SECTION
    header (from the chunker), so we just stack them with blank-line
    separators. Empty list returns empty string (the loop omits the
    ``<retrieved_knowledge>`` wrapper entirely in that case).
    """
    if not retrieved:
        return ""
    return "\n\n".join(rc.chunk.text for rc in retrieved)


def _build_user_message_content(rag_chunks_md: str, user_message: str) -> str:
    """Wrap user_message with the <retrieved_knowledge> block when present."""
    if rag_chunks_md:
        return (
            f"<retrieved_knowledge>\n{rag_chunks_md}\n</retrieved_knowledge>\n\n"
            f"{user_message}"
        )
    return user_message


def _to_anthropic_messages(history: list[Message]) -> list[dict[str, Any]]:
    """Convert prior-turn Message objects into Anthropic-compatible dicts."""
    return [{"role": m.role, "content": m.content} for m in history]


def _extract_final_text(response: Any) -> str:
    """Pull the concatenated text from the response's content blocks.

    The LLM may emit multiple text blocks (e.g., text → tool_use → text);
    after the tool-call loop settles, the final text is everything in the
    last response's content list that is a text block, joined with
    spaces. If the response has no text blocks, returns the empty string.
    """
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
    return "".join(parts)


def _snippet_from_text(body: str) -> str:
    """Bounded hover-preview snippet, stripping the chunker's
    DOCUMENT/SECTION enrichment prefix so the preview reads naturally
    (same intent as always_on._extract_body, inline + length-capped)."""
    if body.startswith("DOCUMENT:"):
        parts = body.split("\n", 3)
        if len(parts) >= 4:
            body = parts[3]
    snippet = body[:200].rstrip()
    if len(body) > 200:
        snippet += "…"
    return snippet


def _build_citations(
    retrieved: list[Any],
    tool_call_history: list[tuple[Any, Any]],
) -> list[Citation]:
    """Assemble ``knowledge_citations[]`` from real history (Fork 28).

    Per Fork 28 the backend builds citations from real retrieval AND
    tool-call history. Three sources are merged, deduplicated by
    ``chunk_id`` (first occurrence wins), and assigned sequential IDs
    1..N so they share one ``[N]`` namespace with ``tool_calls`` (which
    continue from N+1):

    1. **RAG retrieval** — the top-K hybrid hits injected below the cache
       boundary (already minus the always-on block, deduped upstream).
    2. **Invoked tools' declared citations** — each specialized tool
       declares the KB rules/quirks/metrics its computation relies on
       (``ToolResult.citations``). These ground the *computational*
       answers (Q4-Q9) even when the chunk is an always-on rule that was
       deduped out of retrieval — the tool's logic genuinely depends on
       it. Snippet is left empty here (the tool declares only doc /
       section / chunk_id); a later branch can enrich it.
    3. **``lookup_knowledge`` returned chunks** — that tool declares no
       citations because the chunks it returns *are* the citations; we
       convert each returned chunk into a Citation with a real snippet.
    """
    seen: dict[str, tuple[str, str, str]] = {}  # chunk_id -> (doc, section, snippet)

    def _add(chunk_id: str, doc: str, section: str, snippet: str) -> None:
        if chunk_id not in seen:
            seen[chunk_id] = (doc, section, snippet)

    # 1. RAG retrieval (RRF-fused order).
    for rc in retrieved:
        chunk = rc.chunk
        _add(
            chunk.chunk_id,
            chunk.doc,
            f"{chunk.section_id} {chunk.section_title}",
            _snippet_from_text(chunk.text),
        )

    # 2 + 3. Tool-call history, in call order.
    for _block, result in tool_call_history:
        if result.meta.tool_name == "lookup_knowledge":
            data = result.data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("chunk_id"):
                        section = (
                            f"{item.get('section_id', '')} "
                            f"{item.get('section_title', '')}"
                        ).strip()
                        _add(
                            item["chunk_id"],
                            item.get("doc", ""),
                            section,
                            _snippet_from_text(item.get("text", "")),
                        )
        else:
            for cit in result.citations:
                _add(cit.chunk_id, cit.doc, cit.section, "")

    return [
        Citation(
            id=i,
            kind="knowledge",
            doc=doc,
            section=section,
            chunk_id=chunk_id,
            snippet=snippet,
        )
        for i, (chunk_id, (doc, section, snippet)) in enumerate(seen.items(), start=1)
    ]


def _build_tool_call_traces(
    tool_call_history: list[tuple[Any, Any]],  # list of (tool_use_block, ToolResult)
    starting_id: int,
) -> list[ToolCallTrace]:
    """Assemble ToolCallTrace objects from the per-iteration tool history.

    IDs continue from ``starting_id`` (= ``len(citations) + 1``) so
    citations and tool_calls share one numeric space (Fork 28).
    """
    traces: list[ToolCallTrace] = []
    next_id = starting_id
    for block, result in tool_call_history:
        # ToolCallTrace.result is typed dict[str, Any]; most tools return
        # data already in dict shape, but lookup_knowledge returns a list.
        # Wrap non-dict shapes so the contract holds.
        result_data = result.data
        if not isinstance(result_data, dict):
            result_data = {"value": result_data}
        traces.append(
            ToolCallTrace(
                id=next_id,
                kind="computation",
                name=block.name,
                args=dict(block.input),
                result=result_data,
                sql_executed=result.meta.sql_executed,
                view_used=result.meta.view_used,
                shell_entries_excluded=result.meta.shell_entries_excluded,
                rows_inspected=result.meta.rows_inspected,
                latency_ms=result.meta.latency_ms,
            )
        )
        next_id += 1
    return traces


def _extract_assumptions(prose: str, citations: list[Citation]) -> list[Assumption]:
    """Pull out explicit assumption statements from the LLM's prose.

    **Minimal heuristic this branch**: returns an empty list. The
    eval suite (Day 4) doesn't grade against assumptions, and a real
    extractor needs more than regex — ``feat/agent-loop`` ships the
    contract shape so the sidecar response is complete; later branches
    can populate it.

    Parameters are kept in the signature so the call site doesn't need
    to change when the heuristic lands.
    """
    _ = prose, citations  # explicitly unused
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────


def run_agent(
    ctx: AgentContext,
    user_message: str,
    history: list[Message],
    request_id: str,
    *,
    settings: AgentLoopSettings = DEFAULT_LOOP_SETTINGS,
) -> ChatResponse:
    """Run one chat turn: retrieve → loop → validate → assemble sidecar.

    Parameters
    ----------
    ctx
        Boot-time runtime context (DuckDB conn, retriever, Anthropic
        client, pre-built tool definitions, always-on chunk-id set).
    user_message
        The current turn's user text. Already-validated upstream by
        :class:`customs_agent.agent.contracts.Message` (≤ 2000 chars).
    history
        Prior turns, **excluding** the current user message. The loop's
        history pruner (G9) operates on this list.
    request_id
        Caller-supplied correlation ID — UUID from the API layer.
        Echoed back in ``ResponseMeta.request_id``.
    settings
        Loop tuning; defaults match the AGENT_* env defaults.

    Returns
    -------
    ChatResponse
        Always returns; never raises for runtime errors (tool errors,
        loop overruns, etc.). The three "limit hit" signals on
        ``ResponseMeta`` make graceful degradation observable.
    """
    t_start = _now_ms()
    log.info("agent.run.started", request_id=request_id, history_len=len(history))

    # 1. Retrieve
    retrieved_all = ctx.retriever.retrieve(user_message, k=5)
    # 2. Dedup against always-on (Fork 15)
    retrieved = [
        rc for rc in retrieved_all
        if rc.chunk.chunk_id not in ctx.always_on_chunk_ids
    ]

    # 3. Format retrieved + prune history
    rag_chunks_md = _format_retrieved_chunks(retrieved)
    history, dropped_pairs = prune_history(
        history=history,
        current_user_msg=user_message,
        retrieved_text=rag_chunks_md,
        budget=settings.max_input_tokens,
    )

    # 4. Build initial messages list for Anthropic
    anthropic_messages: list[dict[str, Any]] = _to_anthropic_messages(history)
    anthropic_messages.append({
        "role": "user",
        "content": [{
            "type": "text",
            "text": _build_user_message_content(rag_chunks_md, user_message),
        }],
    })

    # 5. Tool-calling loop
    iterations_used = 0
    seen_tool_calls: dict[tuple[str, str], Any] = {}
    tool_call_history: list[tuple[Any, Any]] = []  # (block, ToolResult)

    total_input_tokens = 0
    total_output_tokens = 0
    total_cached_tokens = 0
    duplicate_count = 0
    budget_limit_hit = False
    iteration_limit_hit = False
    response: Any = None

    while iterations_used < settings.max_iterations:
        # Anthropic's SDK typing for `tools` / `messages` is very strict
        # (TypedDict + many block-param union members). Our shapes are
        # correct at runtime but trip mypy; suppress locally.
        response = ctx.client.messages.create(
            model=settings.model,
            temperature=settings.temperature,
            max_tokens=settings.max_output_tokens,
            system=[{
                "type": "text",
                "text": STATIC_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=ctx.tool_definitions,  # type: ignore[arg-type]
            messages=anthropic_messages,  # type: ignore[arg-type]
        )
        iterations_used += 1

        # Tally tokens (defensive — usage may be missing in test mocks).
        usage = getattr(response, "usage", None)
        if usage is not None:
            total_input_tokens += getattr(usage, "input_tokens", 0) or 0
            total_output_tokens += getattr(usage, "output_tokens", 0) or 0
            total_cached_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

        stop_reason = getattr(response, "stop_reason", "end_turn")
        if stop_reason == "end_turn":
            break

        if stop_reason == "tool_use":
            # Re-attach the assistant's response so the next call has the
            # tool_use block in its conversation history.
            anthropic_messages.append({
                "role": "assistant",
                "content": list(response.content),
            })
            tool_results_content: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                cache_key = (block.name, _hash_input(dict(block.input)))
                if settings.dedup_tool_calls and cache_key in seen_tool_calls:
                    result = seen_tool_calls[cache_key]
                    duplicate_count += 1
                    log.warning(
                        "agent.duplicate_tool_call",
                        request_id=request_id, tool=block.name,
                    )
                else:
                    try:
                        result = execute_tool(ctx, block.name, dict(block.input))
                    except Exception as exc:
                        # Catch-all is intentional: any tool exception is
                        # surfaced back to the LLM as a tool_result so the
                        # loop can self-correct rather than crash the request.
                        log.error(
                            "agent.tool_error",
                            request_id=request_id, tool=block.name,
                            error=str(exc),
                        )
                        result = _build_error_result(block.name, exc)
                    seen_tool_calls[cache_key] = result
                tool_call_history.append((block, result))
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result.data, default=str),
                })
            anthropic_messages.append({"role": "user", "content": tool_results_content})
        else:
            log.warning(
                "agent.unexpected_stop_reason",
                request_id=request_id, stop_reason=stop_reason,
            )
            break

        if total_input_tokens > settings.max_input_tokens:
            budget_limit_hit = True
            log.warning(
                "agent.input_token_budget_hit",
                request_id=request_id, tokens=total_input_tokens,
            )
            break

    if iterations_used >= settings.max_iterations:
        iteration_limit_hit = True
        log.warning(
            "agent.iteration_limit_hit",
            request_id=request_id, iterations=iterations_used,
        )

    # 6. Extract final prose
    final_text = _extract_final_text(response)

    # 7. Refusal detection (this branch's design decision — Fork 25)
    category, prose = detect_refusal(final_text)
    refused = category is not None

    # 8. Build sidecar — citations from real retrieval AND tool-call
    #    history (Fork 28); tool_calls continue the shared [N] namespace.
    citations = (
        _build_citations(retrieved, tool_call_history) if not refused else []
    )
    tool_call_traces = (
        _build_tool_call_traces(tool_call_history, starting_id=len(citations) + 1)
        if not refused else []
    )
    assumptions = _extract_assumptions(prose, citations) if not refused else []

    # 9. Validate citation markers (skip on refusal — no markers expected)
    if not refused:
        prose = validate_markers(prose, citations, tool_call_traces)

    meta = ResponseMeta(
        request_id=request_id,
        prompt_version=PROMPT_VERSION,
        model=settings.model,
        embedding_model=settings.embedding_model,
        temperature=settings.temperature,
        iterations_used=iterations_used,
        iteration_limit_hit=iteration_limit_hit,
        budget_limit_hit=budget_limit_hit,
        duplicate_tool_calls=duplicate_count,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        cached_input_tokens=total_cached_tokens,
        # G11 pricing module lands on feat/langfuse-traces; pass 0.0 for
        # now so the contract shape is complete.
        estimated_cost_usd=0.0,
        total_latency_ms=_now_ms() - t_start,
        history_truncated_turns=dropped_pairs if dropped_pairs > 0 else None,
    )

    log.info(
        "agent.run.completed",
        request_id=request_id,
        iterations_used=iterations_used,
        refused=refused,
        refusal_category=category,
        tool_call_count=len(tool_call_history),
        duplicate_count=duplicate_count,
        latency_ms=meta.total_latency_ms,
    )

    return ChatResponse(
        answer=prose,
        knowledge_citations=citations,
        tool_calls=tool_call_traces,
        assumptions=assumptions,
        refused=refused,
        refusal_category=category,
        meta=meta,
    )


def _build_error_result(tool_name: str, exc: Exception) -> Any:
    """Wrap a tool exception in a minimal ToolResult so the loop can
    surface the error back to the LLM (which can decide to retry or
    answer differently). Avoids the import cycle of constructing a
    real ToolResult here — we import lazily.
    """
    from customs_agent.tools._shared import ToolMeta, ToolResult
    return ToolResult(
        data={"error": f"{type(exc).__name__}: {exc}"},
        meta=ToolMeta(
            tool_name=tool_name,
            sql_executed=None,
            view_used=None,
            filters_applied={},
            shell_entries_excluded=0,
            rows_inspected=0,
            latency_ms=0,
        ),
        citations=[],
    )
