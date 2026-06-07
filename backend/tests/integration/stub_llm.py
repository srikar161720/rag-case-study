"""Ergonomic agent-loop LLM scripting (Fork 45 Layer 2).

Layer-2 integration tests run the real agent loop (real tools, real
DuckDB, real RAG) with only the LLM mocked. The mock surface the loop
actually reads already lives in :mod:`tests._fakes`
(:class:`FakeAnthropicClient` + the block dataclasses); this module adds
a thin, readable *scripting* layer on top so a test can express a whole
multi-turn LLM conversation as a list of turns instead of hand-building
``FakeResponse`` objects:

    client = build_stub_client(
        ToolUseTurn("hold_summary", {}),
        TextTurn("The hold rate is 19.67% — above the 8% threshold [1]."),
    )

Each turn maps to exactly one agent-loop iteration (one
``messages.create`` call):

- :class:`ToolUseTurn` → a ``stop_reason="tool_use"`` response carrying
  one (or more) ``tool_use`` blocks the loop will dispatch.
- :class:`TextTurn` → a ``stop_reason="end_turn"`` response carrying the
  final assistant prose.

The compiled client is a real :class:`FakeAnthropicClient`, so tests can
still inspect ``client.calls`` to assert on what the loop sent.
"""

from dataclasses import dataclass, field
from typing import Any

from tests._fakes import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    FakeUsage,
)


@dataclass
class ToolCall:
    """One tool the LLM requests within a single iteration."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


@dataclass
class ToolUseTurn:
    """One assistant iteration that requests one or more tools.

    The common single-tool case is ``ToolUseTurn("hold_summary", {...})``;
    pass extra :class:`ToolCall` objects via ``also=`` to request several
    tools in the same iteration (the loop dispatches them all before the
    next ``messages.create``).
    """

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    also: list[ToolCall] = field(default_factory=list)

    def to_calls(self) -> list[ToolCall]:
        return [ToolCall(self.tool, self.args, self.id), *self.also]


@dataclass
class TextTurn:
    """A final assistant iteration that returns prose (``end_turn``)."""

    text: str
    usage: FakeUsage | None = None


def build_stub_client(
    *turns: ToolUseTurn | TextTurn,
    usage: FakeUsage | None = None,
) -> FakeAnthropicClient:
    """Compile a sequence of turns into a primed :class:`FakeAnthropicClient`.

    ``usage`` is applied to any turn that doesn't carry its own (handy for
    asserting token-budget behavior). Tool-use blocks get stable IDs
    (``tu_<turn>_<n>``) when not supplied so tool_result correlation is
    deterministic.
    """
    client = FakeAnthropicClient()
    for t_idx, turn in enumerate(turns):
        if isinstance(turn, TextTurn):
            client.queue(
                FakeResponse(
                    stop_reason="end_turn",
                    content=[FakeTextBlock(text=turn.text)],
                    usage=turn.usage or usage,
                )
            )
        else:  # ToolUseTurn
            blocks = [
                FakeToolUseBlock(
                    name=call.tool,
                    input=call.args,
                    id=call.id or f"tu_{t_idx}_{c_idx}",
                )
                for c_idx, call in enumerate(turn.to_calls())
            ]
            client.queue(
                FakeResponse(stop_reason="tool_use", content=blocks, usage=usage)
            )
    return client


__all__ = [
    "TextTurn",
    "ToolCall",
    "ToolUseTurn",
    "build_stub_client",
]
