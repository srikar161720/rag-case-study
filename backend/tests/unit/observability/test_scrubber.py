"""Unit tests for the secret-shape scrubber processor (Fork 53).

The scrubber is defense-in-depth: it must redact provider-key-shaped
strings wherever they appear in an event dict — top-level values, nested
dicts, lists — while leaving ordinary domain strings (HTS codes, tool
names, prose) untouched. Keys here are clearly-fake but shape-accurate.
"""

import pytest

from customs_agent.observability.scrubber import _REDACTED, scrub_secrets

# Shape-accurate fakes — NOT real keys. Each must trip exactly one pattern.
FAKE_ANTHROPIC = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA"
FAKE_OPENAI = "sk-proj-BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
FAKE_LANGFUSE_PUBLIC = "pk-lf-1234567890abcdef1234"
FAKE_LANGFUSE_SECRET = "sk-lf-1234567890abcdef1234"

ALL_FAKES = [FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_LANGFUSE_PUBLIC, FAKE_LANGFUSE_SECRET]


@pytest.mark.unit
@pytest.mark.parametrize("secret", ALL_FAKES)
def test_secret_shape_redacted_in_top_level_string(secret: str) -> None:
    """Each provider key shape is replaced by the redaction marker."""
    out = scrub_secrets(None, "info", {"event": "x", "value": secret})
    assert out["value"] == _REDACTED
    assert secret not in out["value"]


@pytest.mark.unit
def test_secret_embedded_in_larger_string_is_redacted() -> None:
    """A key embedded mid-string (e.g. a leaked stack trace) is redacted
    without dropping the surrounding text."""
    msg = f"auth failed for key {FAKE_ANTHROPIC} on /chat"
    out = scrub_secrets(None, "error", {"event": "boom", "error_message": msg})
    assert FAKE_ANTHROPIC not in out["error_message"]
    assert _REDACTED in out["error_message"]
    assert out["error_message"].startswith("auth failed for key ")
    assert out["error_message"].endswith(" on /chat")


@pytest.mark.unit
def test_nested_dict_and_list_values_redacted() -> None:
    """Recursion reaches secrets nested in dicts and lists."""
    out = scrub_secrets(
        None,
        "info",
        {
            "event": "x",
            "headers": {"X-API-Key": FAKE_OPENAI},
            "items": ["safe", FAKE_LANGFUSE_SECRET, {"k": FAKE_LANGFUSE_PUBLIC}],
        },
    )
    assert out["headers"]["X-API-Key"] == _REDACTED
    assert out["items"][0] == "safe"
    assert out["items"][1] == _REDACTED
    assert out["items"][2]["k"] == _REDACTED


@pytest.mark.unit
@pytest.mark.parametrize(
    "benign",
    [
        "hello world",
        "9903.88.15",  # HTS code — dotted numerics must survive
        "query_entries",  # tool name
        "sk-short",  # too short to be a key (< 20 chars after prefix)
        "release_date",
        "ACME-CORP",
    ],
)
def test_benign_strings_untouched(benign: str) -> None:
    """Ordinary domain strings are not mistaken for secrets."""
    out = scrub_secrets(None, "info", {"event": "x", "value": benign})
    assert out["value"] == benign


@pytest.mark.unit
def test_non_string_values_pass_through_unchanged() -> None:
    """Ints, floats, bools, and None are returned as-is."""
    payload = {"event": "x", "count": 5, "ratio": 0.5, "flag": True, "none": None}
    out = scrub_secrets(None, "info", payload)
    assert out["count"] == 5
    assert out["ratio"] == 0.5
    assert out["flag"] is True
    assert out["none"] is None


@pytest.mark.unit
def test_keys_are_not_scrubbed_only_values() -> None:
    """The event dict's KEYS are preserved verbatim — only values are
    walked. (A key shaped like a secret would be a programming bug, not a
    leak vector; preserving keys keeps the event schema intact.)"""
    out = scrub_secrets(None, "info", {"event": "request.received", "path": "/chat"})
    assert set(out.keys()) == {"event", "path"}
    assert out["event"] == "request.received"
    assert out["path"] == "/chat"
