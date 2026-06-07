"""Shared test fakes — Anthropic SDK stand-ins.

Extracted out of ``tests/unit/agent/conftest.py`` so the integration
suite at ``tests/integration/`` and the future eval suite can reuse the
exact same fakes without violating the per-subdir conftest convention
(``unit/agent/conftest.py`` fixtures don't cross-pollinate into
``integration/conftest.py`` automatically — and a cross-subdir conftest
import would be a code smell).

The fakes mirror the slice of the ``anthropic`` Python SDK surface that
:func:`customs_agent.agent.loop.run_agent` actually reads. They are
plain dataclasses + a FIFO-queue client class. Behavior:

- :class:`FakeAnthropicClient` queues canned :class:`FakeResponse`
  payloads via ``.queue(resp)``; each ``.messages.create(...)`` call
  pops the next one (FIFO) and records the full kwargs in ``.calls``.
- Tests construct scenarios by queueing a sequence of FakeResponse
  objects (one per agent-loop iteration) before invoking ``run_agent``.

The unit conftest re-exports these so existing tests don't change
imports; the integration conftest imports them via the same module
path.
"""

from dataclasses import dataclass, field
from typing import Any

from customs_agent.rag.chunker import Chunk


@dataclass
class FakeTextBlock:
    """Mirrors anthropic's TextBlock surface (the bits the loop reads)."""

    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    """Mirrors anthropic's ToolUseBlock surface."""

    name: str
    input: dict[str, Any]
    id: str
    type: str = "tool_use"


@dataclass
class FakeUsage:
    """Mirrors anthropic's Usage object (subset)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class FakeResponse:
    """Mirrors anthropic's Message response surface."""

    stop_reason: str
    content: list[FakeTextBlock | FakeToolUseBlock]
    usage: FakeUsage | None = None


@dataclass
class _FakeMessagesAPI:
    """Stand-in for ``Anthropic().messages``."""

    parent: "FakeAnthropicClient"

    def create(self, **kwargs: Any) -> FakeResponse:
        self.parent.calls.append(kwargs)
        if not self.parent._queued:
            raise RuntimeError(
                "FakeAnthropicClient: no canned response queued. "
                "Did the test forget to call .queue() enough times?"
            )
        return self.parent._queued.pop(0)


@dataclass
class FakeAnthropicClient:
    """Records every ``messages.create`` call; replays queued responses in order.

    Drop-in replacement for ``anthropic.Anthropic()`` for any test that
    exercises :func:`customs_agent.agent.loop.run_agent`. Set up scenarios
    via ``.queue(FakeResponse(...))``; inspect ``.calls`` to assert on what
    the loop sent.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)
    _queued: list[FakeResponse] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = _FakeMessagesAPI(parent=self)

    def queue(self, response: FakeResponse) -> None:
        """Add a response to the FIFO replay queue."""
        self._queued.append(response)


# ─────────────────────────────────────────────────────────────────────────────
# Retriever fakes — mirror the HybridRetriever.retrieve() surface the loop reads
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeRetrievedChunk:
    """Mirrors ``customs_agent.rag.retriever.RetrievedChunk`` shape."""

    chunk: Chunk
    rank_semantic: int | None = None
    rank_bm25: int | None = None
    score_rrf: float = 0.0


@dataclass
class FakeRetriever:
    """Replays canned chunks; records every retrieve() call.

    Drop-in for :class:`customs_agent.rag.retriever.HybridRetriever` in any
    test that exercises :func:`customs_agent.agent.loop.run_agent` (or
    ``lookup_knowledge``, which reads ``ctx.retriever``). Shared here so the
    unit and integration suites use the exact same retriever stub.
    """

    chunks_to_return: list[Chunk] = field(default_factory=list)
    call_log: list[dict[str, Any]] = field(default_factory=list)

    def retrieve(self, query: str, k: int = 5) -> list[FakeRetrievedChunk]:
        self.call_log.append({"query": query, "k": k})
        return [
            FakeRetrievedChunk(
                chunk=c, rank_semantic=i, rank_bm25=None, score_rrf=1.0 / (i + 1)
            )
            for i, c in enumerate(self.chunks_to_return[:k])
        ]


__all__ = [
    "FakeAnthropicClient",
    "FakeResponse",
    "FakeRetrievedChunk",
    "FakeRetriever",
    "FakeTextBlock",
    "FakeToolUseBlock",
    "FakeUsage",
]
