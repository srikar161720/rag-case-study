"""Tests for conversation history pruning (G9).

Covers the eviction algorithm: drop oldest user+assistant pairs until
the cumulative input-token estimate fits in budget; always preserve
the last 2 turn pairs; never split a pair; report the count of
dropped pairs in the return value so the sidecar can populate
``ResponseMeta.history_truncated_turns``.
"""

import pytest

from customs_agent.agent.contracts import Message
from customs_agent.agent.history import (
    estimate_tokens,
    prune_history,
)


def _u(content: str) -> Message:
    return Message(role="user", content=content)


def _a(content: str) -> Message:
    return Message(role="assistant", content=content)


# ─────────────────────────────────────────────────────────────────────────────
# estimate_tokens — heuristic sanity
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_estimate_tokens_empty_is_positive() -> None:
    """The +1 floor keeps empty strings from being free in the budget math."""
    assert estimate_tokens("") == 1


@pytest.mark.unit
def test_estimate_tokens_scales_with_length() -> None:
    a = estimate_tokens("x" * 40)   # ~10 tokens
    b = estimate_tokens("x" * 400)  # ~100 tokens
    assert b > a
    assert b > 10 * a // 2  # well above half — roughly linear


# ─────────────────────────────────────────────────────────────────────────────
# Under-budget path — pass through
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_under_budget_passes_through_with_zero_dropped() -> None:
    history = [_u("hi"), _a("hello")]
    pruned, dropped = prune_history(
        history, current_user_msg="next question",
        retrieved_text="some chunks",
        static_prefix_tokens=100, budget=10_000,
    )
    assert pruned == history
    assert dropped == 0


@pytest.mark.unit
def test_empty_history_no_op() -> None:
    pruned, dropped = prune_history(
        [], current_user_msg="hi", retrieved_text="",
        static_prefix_tokens=10, budget=10_000,
    )
    assert pruned == []
    assert dropped == 0


# ─────────────────────────────────────────────────────────────────────────────
# Over-budget eviction
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_oldest_pair_dropped_first() -> None:
    """Six messages (3 pairs); tight budget that forces eviction. The
    oldest pair is dropped; the most recent 2 pairs (4 messages) stay."""
    history = [
        _u("OLD-user"), _a("OLD-assistant"),
        _u("MID-user"), _a("MID-assistant"),
        _u("NEW-user"), _a("NEW-assistant"),
    ]
    # Tiny budget: only room for ~4 messages worth of text.
    pruned, dropped = prune_history(
        history, current_user_msg="now", retrieved_text="",
        static_prefix_tokens=0, budget=20,
    )
    assert dropped == 1
    assert len(pruned) == 4
    assert pruned[0].content == "MID-user"
    assert pruned[-1].content == "NEW-assistant"


@pytest.mark.unit
def test_keep_last_two_pairs_even_when_over_budget() -> None:
    """If the last 2 pairs alone still exceed budget, we DON'T evict
    them — the spec says they're always preserved. Pruner returns the
    minimum-viable list (last 2 pairs) and lets the caller deal with
    the overrun."""
    history = [
        _u("very-long-old-user-msg" * 50), _a("very-long-old-asst-msg" * 50),
        _u("recent-user"), _a("recent-asst"),
        _u("newest-user"), _a("newest-asst"),
    ]
    pruned, dropped = prune_history(
        history, current_user_msg="x", retrieved_text="",
        static_prefix_tokens=0, budget=10,  # absurdly tight
    )
    assert len(pruned) == 4
    assert pruned[0].content == "recent-user"
    assert pruned[-1].content == "newest-asst"
    assert dropped == 1


@pytest.mark.unit
def test_drops_in_pair_units_never_splits_a_pair() -> None:
    """Per G9: eviction is whole user+assistant pairs, never a single
    message. Even when budget is achievable mid-pair, eviction proceeds
    in 2-message increments."""
    # 80-char messages → ~21 tokens each under the 4-chars/token heuristic.
    # 8 messages * 21 = 168 tokens. Budget 100 with negligible overhead
    # forces 2 pairs (4 messages, ~84 tokens) to be dropped — leaving the
    # last 2 pairs (4 messages) untouched.
    history = [
        _u("u0" * 40), _a("a0" * 40),
        _u("u1" * 40), _a("a1" * 40),
        _u("u2" * 40), _a("a2" * 40),
        _u("u3" * 40), _a("a3" * 40),
    ]
    pruned, dropped = prune_history(
        history, current_user_msg="x", retrieved_text="",
        static_prefix_tokens=0, budget=100,
    )
    assert dropped == 2
    assert len(pruned) == 4
    # Even number of remaining messages (pair-aligned).
    assert len(pruned) % 2 == 0
    # The preserved tail is the most recent 2 pairs.
    assert pruned[0].content.startswith("u2")
    assert pruned[-1].content.startswith("a3")


# ─────────────────────────────────────────────────────────────────────────────
# History shorter than the "always preserve" tail
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_history_below_4_messages_no_op_even_when_over_budget() -> None:
    """Last 2 pairs are 4 messages. If history has fewer, nothing to drop."""
    history = [_u("only-pair-user"), _a("only-pair-asst")]
    pruned, dropped = prune_history(
        history, current_user_msg="x", retrieved_text="",
        static_prefix_tokens=0, budget=1,
    )
    assert pruned == history
    assert dropped == 0


# ─────────────────────────────────────────────────────────────────────────────
# Token counter injection (Anthropic substitution point)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_custom_token_counter_used() -> None:
    """The loop can pass a closure over anthropic.tokens.count_messages
    for higher accuracy; tests verify the injection point works."""
    # A counter that overestimates 10x will trigger eviction sooner.
    def heavy(text: str) -> int:
        return len(text) * 10

    history = [_u("hi"), _a("hi"), _u("hi"), _a("hi"), _u("hi"), _a("hi")]
    _pruned, dropped = prune_history(
        history, current_user_msg="x", retrieved_text="",
        static_prefix_tokens=0, budget=100,
        token_counter=heavy,
    )
    assert dropped >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Fixed-overhead accounting
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_retrieved_text_counts_against_budget() -> None:
    """A large retrieved block shrinks the available budget and can
    trigger eviction that wouldn't have happened with an empty retrieval."""
    history = [_u("u1"), _a("a1"), _u("u2"), _a("a2"), _u("u3"), _a("a3")]

    # No retrieval → fits comfortably.
    _, dropped_no_retrieval = prune_history(
        history, current_user_msg="x", retrieved_text="",
        static_prefix_tokens=0, budget=100,
    )
    # Big retrieval → forces eviction.
    _, dropped_with_retrieval = prune_history(
        history, current_user_msg="x",
        retrieved_text="x" * 1000,  # ~250 estimated tokens
        static_prefix_tokens=0, budget=100,
    )
    assert dropped_with_retrieval > dropped_no_retrieval
