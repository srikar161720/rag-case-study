"""Public API contracts — every Pydantic shape the agent loop binds to.

This module is the single source of truth for the request and response
schemas of the `/chat` endpoint that lands on
``feat/fastapi-backend``. The 7 types below split into three concerns:

- **Wire-level shape** — :class:`Message`, :class:`ChatRequest`,
  :class:`ChatResponse`. These define the JSON the frontend sends and
  receives.
- **Sidecar parts** — :class:`Citation`, :class:`ToolCallTrace`,
  :class:`Assumption`, :class:`ResponseMeta`. The agent loop's
  per-request sidecar builder constructs these from real history (Fork
  28's "structurally impossible to hallucinate citations" pattern).
- **Refusal enum** — :data:`RefusalCategory`, one of 5 routing categories
  per Fork 25; the LLM signals refusal via the
  ``<!-- refusal:<category> -->`` marker that :mod:`refusal` detects.

Why everything lives here (and not in ``api/chat.py``):

The agent loop in ``agent/loop.py`` constructs :class:`ChatResponse`
directly; the API layer is a thin handler that forwards. Putting the
contracts beside the producer (agent) keeps the dependency direction
conventional (api → agent → contracts) and gives future API surfaces
(e.g., ``api/conversations.py``) a single import path for shared
types. ``api/chat.py`` re-exports :class:`ChatRequest` and
:class:`ChatResponse` so PROGRESS.md's named-export checklist item is
honored without duplicating definitions.

All models use ``extra="forbid"`` so unknown fields fail at the
schema boundary — the same fail-fast principle as ``EntryFilters``
(Fork 21). The request-side ``max_length=2000`` on
:class:`Message.content` is Fork 49 layer-1 input validation (length-
bomb defense); the value matches the
``safety_max_user_message_chars`` default in :mod:`config`.

Shared-ID rule (Fork 28): :class:`Citation` and :class:`ToolCallTrace`
share one numeric ``id`` space (1, 2, 3, …). The agent loop assigns
IDs sequentially when building the sidecar, and the LLM's prose
markers (``[N]``) resolve into either array based on which one holds
``id: N``. This is what makes citation forgery structurally
impossible — the LLM only writes ``[N]`` and never the citation body.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────────────────────────────────────

RefusalCategory = Literal[
    "off_domain",
    "out_of_range",
    "unmapped",
    "meta",
    "adversarial",
]
"""Fork 25 — five refusal categories. The LLM signals refusal by
prepending ``<!-- refusal:<category> -->`` to its response (see
``agent/refusal.py``); the backend strips the marker, sets
:attr:`ChatResponse.refused` to ``True``, and copies the category
into :attr:`ChatResponse.refusal_category`."""


# ─────────────────────────────────────────────────────────────────────────────
# Wire-level: request side
# ─────────────────────────────────────────────────────────────────────────────


class Message(BaseModel):
    """One turn in a conversation.

    ``content`` is capped at 2,000 characters — Fork 49 layer-1
    length-bomb defense. The cap matches
    ``Settings.safety_max_user_message_chars`` so a future config edit
    in both places fails loudly via the snapshot test rather than
    silently diverging.
    """

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class ChatRequest(BaseModel):
    """POST /chat body.

    ``messages`` carries the conversation history including the
    current user turn (the last element should have ``role="user"``;
    the agent loop's history pruner (G9) operates on
    ``messages[:-1]`` as prior turns and treats the last as the
    current query).

    ``conversation_id`` is an optional frontend-generated UUID used
    for trace correlation across Langfuse spans and structlog
    requests; the backend does not validate its shape because future
    frontends may use any opaque correlation token.
    """

    messages: list[Message] = Field(min_length=1, max_length=100)
    conversation_id: str | None = None

    model_config = ConfigDict(extra="forbid")


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar parts: Citation, ToolCallTrace, Assumption
# ─────────────────────────────────────────────────────────────────────────────


class Citation(BaseModel):
    """One retrieved-knowledge entry the LLM can cite via ``[id]`` in prose.

    ``id`` is assigned sequentially by the agent loop (1..N for the N
    surfaced knowledge chunks). The LLM never assigns IDs — it only
    writes the ``[N]`` marker; the backend resolves the marker to a
    citation. Hallucinated markers (``[99]`` when only ``[1]..[5]`` are
    valid) are stripped by :mod:`validator` before the response goes
    out.

    ``chunk_id`` matches an entry in
    :data:`customs_agent.rag.chunker.CHUNKS_REGISTRY`, allowing the
    show-work panel to jump from a citation back to its source.
    """

    id: int = Field(ge=1)
    kind: Literal["knowledge"] = "knowledge"
    doc: str
    section: str
    chunk_id: str
    snippet: str

    model_config = ConfigDict(extra="forbid")


class ToolCallTrace(BaseModel):
    """One tool invocation recorded by the agent loop.

    Shares the ``id`` numeric space with :class:`Citation` so the LLM's
    ``[N]`` markers can reference either a knowledge citation or a
    computation. The loop assigns tool-call IDs sequentially starting
    at ``len(citations) + 1``.

    The non-``Optional`` SQL fields (``sql_executed``, ``view_used``)
    are populated for SQL tools and ``None`` for
    :func:`customs_agent.tools.lookup_knowledge.lookup_knowledge` — the
    only tool that doesn't issue SQL.
    """

    id: int = Field(ge=1)
    kind: Literal["computation"] = "computation"
    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    sql_executed: str | None = None
    view_used: Literal["entries_v", "entry_lines_v"] | None = None
    shell_entries_excluded: int = Field(ge=0)
    rows_inspected: int = Field(ge=0)
    latency_ms: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


class Assumption(BaseModel):
    """One default the agent applied silently per Fork 24's
    "default + state + cite" pattern.

    Surfaced in the sidecar so the user can see what choices were made
    without asking. ``rule_id`` and ``rule_section`` are optional
    because some assumptions (e.g., "interpreting 'January' as the
    most recent January in the dataset") aren't backed by a KB rule.
    """

    key: str
    value: str
    rule_id: str | None = None
    rule_section: str | None = None

    model_config = ConfigDict(extra="forbid")


# ─────────────────────────────────────────────────────────────────────────────
# Sidecar parts: ResponseMeta
# ─────────────────────────────────────────────────────────────────────────────


class ResponseMeta(BaseModel):
    """Per-response operational metadata.

    Surfaces in the response shape so the show-work panel and any
    debugging tooling can answer "what model / version / budget did
    this turn use, and did it bump into any limit". Three guard
    fields (``iteration_limit_hit``, ``budget_limit_hit``,
    ``duplicate_tool_calls``) make graceful degradation observable.

    Token + cost fields default to 0 here so test fixtures can
    construct a meta cheaply; the agent loop overwrites them with
    Anthropic's reported usage on every real request. The
    ``estimated_cost_usd`` calculation lands on
    ``feat/langfuse-traces`` via the pricing module (G11) — until
    then the loop passes ``0.0``.
    """

    request_id: str
    prompt_version: str
    model: str
    embedding_model: str
    temperature: float
    iterations_used: int = Field(ge=0)
    iteration_limit_hit: bool = False
    budget_limit_hit: bool = False
    duplicate_tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    total_latency_ms: int = Field(default=0, ge=0)
    # Streaming (Fork 29) lands later; this field stays None on this branch.
    stream_ttft_ms: int | None = None
    # History pruning (G9) — populated when prune_history drops turns.
    history_truncated_turns: int | None = None

    model_config = ConfigDict(extra="forbid")


# ─────────────────────────────────────────────────────────────────────────────
# Wire-level: response side
# ─────────────────────────────────────────────────────────────────────────────


class ChatResponse(BaseModel):
    """POST /chat response body.

    Constructed by ``agent/loop.py`` after the tool-calling loop
    settles. On refusal (``refused=True``), ``knowledge_citations``,
    ``tool_calls``, and ``assumptions`` are empty lists and
    ``refusal_category`` is populated. On a successful answer, the
    lists carry the real history; ``refusal_category`` stays ``None``.

    Uses ``Field(default_factory=list)`` everywhere (not ``= []``) to
    match the codebase convention and defend against the
    shared-mutable-default footgun.
    """

    answer: str
    knowledge_citations: list[Citation] = Field(default_factory=list)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    refused: bool = False
    refusal_category: RefusalCategory | None = None
    meta: ResponseMeta

    model_config = ConfigDict(extra="forbid")
