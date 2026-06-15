"""Secret-shape redaction processor (Fork 53).

Defense-in-depth for the stdout log sink: if any code path ever logs a
secret-shape string — an accidental ``log.info("...", key=api_key)``, a
stack trace that dumps a header, a tool error echoing a connection
string — this structlog processor redacts it *before* the event reaches
stdout (and therefore before it reaches ``fly logs``).

It mirrors the Fork 49 output-safety scrubber but on the logging side:
~10 lines, no false-negative-free guarantee, but real protection against
future regressions. Wired as the last shared processor in
:func:`customs_agent.observability.logging.configure_logging` so it runs
on every event regardless of renderer.

The patterns target the three provider key shapes this project handles:
Anthropic (``sk-ant-…``), OpenAI (``sk-…``), and Langfuse public
(``pk-lf-…``). Langfuse *secret* keys (``sk-lf-…``) are caught by the
generic ``sk-`` pattern.
"""

import re
from typing import Any

from structlog.typing import EventDict, WrappedLogger

_REDACTED = "[REDACTED-SECRET]"

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bpk-lf-[A-Za-z0-9_-]{10,}\b"),
]


def _scrub(value: Any) -> Any:
    """Recursively redact secret-shape substrings in ``value``.

    Walks strings, dicts, and lists; leaves every other type untouched.
    Returns a new structure (originals are not mutated).
    """
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub(_REDACTED, value)
        return value
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def scrub_secrets(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: redact secret-shape strings from every field.

    The processor signature (``logger``, ``method_name``, ``event_dict``)
    is structlog's contract; only ``event_dict`` is used. Returns the
    scrubbed event dict for the next processor in the chain.
    """
    return {key: _scrub(val) for key, val in event_dict.items()}
