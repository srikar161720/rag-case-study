"""Conversation history pruning (G9).

When the cumulative tokens in the request (system prefix + retrieved
chunks + current user message + full history) would exceed the
``AGENT_MAX_INPUT_TOKENS_PER_TURN`` budget (default 50,000), drop the
oldest turn pairs until we fit. Always keep:

- The system prefix (it's the cached prefix, not part of ``history``).
- The retrieved chunks for the current query.
- The current user message.
- The last 2 user+assistant turn pairs (most recent context).

Eviction unit is a turn PAIR (user + assistant) — never split a pair.
Drop oldest first.

Token counting: this module ships with a deterministic
``len(text) // 4`` heuristic so tests don't need a live Anthropic
client. The agent loop can substitute
``anthropic.tokens.count_messages`` for higher accuracy via the
:func:`prune_history` ``token_counter`` parameter when it lands; the
default keeps the unit suite offline.

The return value is ``(pruned_history, n_pairs_dropped)`` so the
sidecar can populate ``ResponseMeta.history_truncated_turns`` and the
frontend can render the "earlier history truncated to fit context"
banner mentioned in the G9 spec.
"""

from collections.abc import Callable, Sequence

from customs_agent.agent.contracts import Message

# Heuristic tokens-per-character constant; rough but fine for the
# pruning heuristic (we only need correct ORDERING, not exact counts).
# Anthropic's BPE-style tokenizer averages ~3.5-4 chars/token on English
# text; 4 is a conservative ceiling.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Deterministic token-count estimate from text length.

    Used by :func:`prune_history` as the default ``token_counter``.
    Conservative (overestimates rather than underestimates) so the
    budget guard kicks in slightly before the real tokenizer would —
    favors leaving headroom over running over.
    """
    return len(text) // _CHARS_PER_TOKEN + 1  # +1 so empty isn't 0


def _estimate_messages(messages: Sequence[Message], counter: Callable[[str], int]) -> int:
    """Sum the token estimate across a sequence of Messages."""
    return sum(counter(m.content) for m in messages)


def prune_history(
    history: list[Message],
    current_user_msg: str,
    retrieved_text: str = "",
    *,
    static_prefix_tokens: int = 3980,
    budget: int = 50_000,
    token_counter: Callable[[str], int] = estimate_tokens,
) -> tuple[list[Message], int]:
    """Trim ``history`` to fit within the input-token budget.

    Parameters
    ----------
    history
        Prior turns (NOT including the current user message). Mutated
        only via slicing; the original list is not modified.
    current_user_msg
        The text of the current user message (counted against the
        budget but never evicted).
    retrieved_text
        The full text of the retrieved-knowledge block that will be
        injected into the current user message (counted against the
        budget but never evicted). Pass ``""`` if no retrieval
        happened or the caller doesn't have it materialized yet.
    static_prefix_tokens
        Tokens consumed by the cached system prefix (Fork 55 — ~3,980
        tokens for ``STATIC_SYSTEM_PROMPT`` plus tool definitions).
        Default approximates the locked spec; the loop can pass a
        more accurate count if it has one.
    budget
        Total input-token cap per turn. Defaults to the
        ``AGENT_MAX_INPUT_TOKENS_PER_TURN`` setting.
    token_counter
        Callable that takes a string and returns its estimated token
        count. Defaults to :func:`estimate_tokens` (heuristic, fast,
        deterministic). The loop can pass a closure over
        ``anthropic.tokens.count_messages`` for higher accuracy.

    Returns
    -------
    tuple[list[Message], int]
        - The (possibly-trimmed) history list. Same identity as the
          input only when nothing was dropped.
        - The count of turn PAIRS dropped (0 when no pruning happened).
    """
    fixed_overhead = (
        static_prefix_tokens
        + token_counter(retrieved_text)
        + token_counter(current_user_msg)
    )
    available = budget - fixed_overhead

    if _estimate_messages(history, token_counter) <= available:
        return history, 0

    # Always preserve the last 2 turn pairs (4 messages). If history is
    # shorter than 4, nothing to drop — return as-is even if over budget.
    if len(history) <= 4:
        return history, 0

    keep_tail = history[-4:]
    candidates = history[:-4]
    dropped = 0
    while candidates and _estimate_messages(candidates + keep_tail, token_counter) > available:
        # Drop the oldest user+assistant pair (2 messages). If the prefix
        # has an odd number (broken pairing), drop one message at a time
        # so we still make progress; this is defensive against malformed
        # history.
        chunk_size = 2 if len(candidates) >= 2 else 1
        candidates = candidates[chunk_size:]
        dropped += 1

    return candidates + keep_tail, dropped
