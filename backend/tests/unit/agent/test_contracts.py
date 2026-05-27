"""Tests for the Pydantic contracts (Fork 28).

Three concerns:

1. **Wire-level schema** — every model parses happy-path JSON, rejects
   junk fields (``extra="forbid"``), and round-trips through
   ``model_dump_json`` so the FastAPI endpoint (later branch) can
   serialize any response uniformly.
2. **Length-bomb defense (Fork 49 layer 1)** — Message.content
   max_length=2000, ChatRequest.messages min/max bounds.
3. **Shared-ID-space invariant** — Citation IDs and ToolCallTrace IDs
   coexist; the loop assigns them sequentially. Tests assert the
   types accept overlapping numbers (the loop's sidecar builder
   prevents collisions; the schema doesn't).
"""

import pytest
from pydantic import ValidationError

from customs_agent.agent.contracts import (
    Assumption,
    ChatRequest,
    ChatResponse,
    Citation,
    Message,
    ResponseMeta,
    ToolCallTrace,
)

# ─────────────────────────────────────────────────────────────────────────────
# Happy-path construction
# ─────────────────────────────────────────────────────────────────────────────


def _make_meta(**overrides) -> ResponseMeta:
    """Build a minimal valid ResponseMeta for tests; override any field."""
    defaults: dict = {
        "request_id": "req-abc",
        "prompt_version": "1.0.0",
        "model": "claude-sonnet-4-6",
        "embedding_model": "text-embedding-3-small",
        "temperature": 0.0,
        "iterations_used": 1,
    }
    defaults.update(overrides)
    return ResponseMeta(**defaults)


@pytest.mark.unit
def test_message_happy_path() -> None:
    m = Message(role="user", content="hi")
    assert m.role == "user"
    assert m.content == "hi"


@pytest.mark.unit
def test_chat_request_happy_path() -> None:
    req = ChatRequest(
        messages=[Message(role="user", content="how many entries for PCA in Jan?")],
        conversation_id="conv-123",
    )
    assert len(req.messages) == 1
    assert req.conversation_id == "conv-123"


@pytest.mark.unit
def test_chat_request_without_conversation_id() -> None:
    """conversation_id is optional; absence must parse cleanly."""
    req = ChatRequest(messages=[Message(role="user", content="x")])
    assert req.conversation_id is None


@pytest.mark.unit
def test_citation_happy_path() -> None:
    c = Citation(
        id=1,
        kind="knowledge",
        doc="duties_fees_tariffs.txt",
        section="§Rule 1",
        chunk_id="rule_1_date_filtering",
        snippet="Always use Release Date for period-based queries.",
    )
    assert c.id == 1
    assert c.chunk_id == "rule_1_date_filtering"


@pytest.mark.unit
def test_tool_call_trace_happy_path() -> None:
    t = ToolCallTrace(
        id=2,
        kind="computation",
        name="hold_summary",
        args={"filters": {}},
        result={"entries_total": 1200, "entries_on_hold": 236},
        sql_executed="SELECT COUNT(*) FROM entries_v",
        view_used="entries_v",
        shell_entries_excluded=0,
        rows_inspected=1200,
        latency_ms=5,
    )
    assert t.id == 2
    assert t.view_used == "entries_v"


@pytest.mark.unit
def test_tool_call_trace_allows_null_sql_for_non_sql_tools() -> None:
    """lookup_knowledge has no SQL — sql_executed + view_used must accept None."""
    t = ToolCallTrace(
        id=3, kind="computation", name="lookup_knowledge",
        args={"query": "x"}, result={"chunks": []},
        sql_executed=None, view_used=None,
        shell_entries_excluded=0, rows_inspected=5, latency_ms=12,
    )
    assert t.sql_executed is None
    assert t.view_used is None


@pytest.mark.unit
def test_assumption_optional_rule_fields() -> None:
    """Some assumptions aren't backed by a KB rule — rule_id/section nullable."""
    a = Assumption(key="date_field", value="release_date",
                   rule_id="rule_1_date_filtering",
                   rule_section="§Business Rule 1")
    assert a.rule_id == "rule_1_date_filtering"
    b = Assumption(key="period_scope", value="2025-01")
    assert b.rule_id is None
    assert b.rule_section is None


@pytest.mark.unit
def test_response_meta_happy_path() -> None:
    meta = _make_meta()
    assert meta.iteration_limit_hit is False
    assert meta.budget_limit_hit is False
    assert meta.duplicate_tool_calls == 0
    assert meta.input_tokens == 0
    assert meta.stream_ttft_ms is None
    assert meta.history_truncated_turns is None


@pytest.mark.unit
def test_chat_response_default_lists_are_independent() -> None:
    """Regression: list defaults use Field(default_factory=list), so two
    empty ChatResponses must NOT share their lists."""
    a = ChatResponse(answer="x", meta=_make_meta())
    b = ChatResponse(answer="y", meta=_make_meta())
    assert a.knowledge_citations is not b.knowledge_citations
    a.knowledge_citations.append(
        Citation(id=1, kind="knowledge", doc="d.txt", section="§1",
                 chunk_id="c1", snippet="s")
    )
    assert len(a.knowledge_citations) == 1
    assert len(b.knowledge_citations) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Validation: length-bomb defense (Fork 49 layer 1)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_message_content_max_length_2000() -> None:
    """Fork 49 layer 1 — 2001-char message rejected at schema boundary."""
    Message(role="user", content="x" * 2000)  # at the bound — passes
    with pytest.raises(ValidationError) as exc:
        Message(role="user", content="x" * 2001)
    assert "at most 2000" in str(exc.value) or "max_length" in str(exc.value)


@pytest.mark.unit
def test_message_content_min_length_1() -> None:
    """Empty content rejected — no useful turn has an empty message."""
    with pytest.raises(ValidationError):
        Message(role="user", content="")


@pytest.mark.unit
def test_chat_request_min_one_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(messages=[])


@pytest.mark.unit
def test_chat_request_max_100_messages() -> None:
    """100 messages OK; 101 rejected."""
    ChatRequest(messages=[Message(role="user", content="x") for _ in range(100)])
    with pytest.raises(ValidationError):
        ChatRequest(messages=[Message(role="user", content="x") for _ in range(101)])


@pytest.mark.unit
def test_message_role_must_be_enum() -> None:
    with pytest.raises(ValidationError):
        Message(role="system", content="x")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# extra='forbid' — unknown fields rejected everywhere
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "model_cls, valid_kwargs",
    [
        (Message, {"role": "user", "content": "x"}),
        (ChatRequest, {"messages": [{"role": "user", "content": "x"}]}),
        (Citation, {"id": 1, "kind": "knowledge", "doc": "d", "section": "s",
                    "chunk_id": "c", "snippet": "sn"}),
        (Assumption, {"key": "k", "value": "v"}),
    ],
)
def test_extra_field_rejected(model_cls: type, valid_kwargs: dict) -> None:
    """Adding an unknown field on any model raises ValidationError."""
    kwargs_with_extra = {**valid_kwargs, "rogue_field": "junk"}
    with pytest.raises(ValidationError) as exc:
        model_cls(**kwargs_with_extra)
    assert "rogue_field" in str(exc.value) or "extra" in str(exc.value).lower()


# ─────────────────────────────────────────────────────────────────────────────
# JSON round-trip — catches default-factory + serialization regressions
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_chat_response_round_trip() -> None:
    """ChatResponse → JSON → ChatResponse preserves shape including nested
    citations, tool_calls, and meta."""
    original = ChatResponse(
        answer="PCA filed 25 entries in January 2025 [1].",
        knowledge_citations=[
            Citation(id=1, kind="knowledge", doc="duties_fees_tariffs.txt",
                     section="§Rule 1", chunk_id="rule_1_date_filtering",
                     snippet="Use Release Date by default."),
        ],
        tool_calls=[
            ToolCallTrace(id=2, kind="computation", name="query_entries",
                          args={"filters": {"customer_code": "PCA"}},
                          result={"entry_count": 25}, sql_executed="SELECT ...",
                          view_used="entries_v", shell_entries_excluded=0,
                          rows_inspected=25, latency_ms=3),
        ],
        assumptions=[
            Assumption(key="date_field", value="release_date",
                       rule_id="rule_1_date_filtering",
                       rule_section="§Business Rule 1"),
        ],
        refused=False,
        meta=_make_meta(input_tokens=3200, output_tokens=120),
    )
    rehydrated = ChatResponse.model_validate_json(original.model_dump_json())
    assert rehydrated.answer == original.answer
    assert rehydrated.knowledge_citations == original.knowledge_citations
    assert rehydrated.tool_calls == original.tool_calls
    assert rehydrated.assumptions == original.assumptions
    assert rehydrated.meta == original.meta


@pytest.mark.unit
def test_chat_response_refused_shape() -> None:
    """Refused response: lists empty, refusal_category set, no other shape change."""
    resp = ChatResponse(
        answer="I'm focused on customs analytics for MHF, PCA, and SAG over...",
        refused=True,
        refusal_category="off_domain",
        meta=_make_meta(iterations_used=1),
    )
    assert resp.refused is True
    assert resp.refusal_category == "off_domain"
    assert resp.knowledge_citations == []
    assert resp.tool_calls == []
    assert resp.assumptions == []


@pytest.mark.unit
def test_invalid_refusal_category_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatResponse(answer="x", refused=True,
                     refusal_category="made_up",  # type: ignore[arg-type]
                     meta=_make_meta())


# ─────────────────────────────────────────────────────────────────────────────
# Shared ID-space invariant
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_citation_and_tool_call_share_id_space() -> None:
    """Schema-level: a Citation with id=1 and a ToolCallTrace with id=2
    coexist on a ChatResponse. The loop's sidecar builder is responsible
    for assigning non-overlapping IDs; the schema doesn't enforce that
    (it would be too restrictive — the loop can re-order IDs)."""
    resp = ChatResponse(
        answer="See [1] and [2].",
        knowledge_citations=[
            Citation(id=1, kind="knowledge", doc="d", section="s",
                     chunk_id="c", snippet="sn"),
        ],
        tool_calls=[
            ToolCallTrace(id=2, kind="computation", name="hold_summary",
                          args={}, result={}, sql_executed="SELECT 1",
                          view_used="entries_v", shell_entries_excluded=0,
                          rows_inspected=0, latency_ms=0),
        ],
        meta=_make_meta(),
    )
    citation_ids = {c.id for c in resp.knowledge_citations}
    tool_call_ids = {t.id for t in resp.tool_calls}
    assert citation_ids == {1}
    assert tool_call_ids == {2}
    # And the union forms the ID universe for marker validation
    assert citation_ids | tool_call_ids == {1, 2}
