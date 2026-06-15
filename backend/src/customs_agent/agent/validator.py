"""Citation marker validator (Fork 28).

The LLM writes ``[N]`` markers in prose; the backend constructs the
``knowledge_citations`` and ``tool_calls`` arrays from real history and
assigns sequential IDs. This module reconciles the two: any ``[N]`` in
prose that doesn't correspond to a real citation or tool-call ID is
**stripped silently** before the response leaves the backend.

Why silent (vs. raising): a hallucinated marker is a model error, not
a request error. The user's question was answerable; the orphan marker
is just noise. Logging the orphan ID set + the valid ID set gives
ops a clean signal for "the model invented citations" without
breaking the user-facing response.

Scope this branch:

- ``validate_markers(prose, citations, tool_calls) -> str`` — the spec
  shape from context/04-agent-and-tools.md, verbatim.

The marker regex (``MARKER_RE``) is exported so other modules
(``loop.py`` for marker extraction during sidecar assembly) can reuse
it without redefining the pattern — single source of truth.
"""

import re
from collections.abc import Sequence
from typing import Protocol

import structlog

from customs_agent.observability.events import Events

log = structlog.get_logger()

MARKER_RE = re.compile(r"\[(\d+)\]")
"""Matches inline ``[N]`` citation markers in prose. ``\\d+`` is greedy
so multi-digit IDs (``[42]``) round-trip cleanly."""


class _HasId(Protocol):
    """Structural type for anything with an integer ``id`` field.

    Avoids a hard import of :class:`Citation` / :class:`ToolCallTrace`
    so this module can be exercised in isolation by tests with stub
    objects and keeps the dependency graph thin.
    """

    id: int


def validate_markers(
    prose: str,
    citations: Sequence[_HasId],
    tool_calls: Sequence[_HasId],
) -> str:
    """Strip ``[N]`` markers that don't reference a real citation or tool call.

    Parameters
    ----------
    prose
        The LLM's prose output, possibly containing ``[N]`` markers.
    citations
        The :class:`Citation` list the backend assembled from retrieved
        chunks; each has an integer ``id``.
    tool_calls
        The :class:`ToolCallTrace` list the backend assembled from real
        tool history; each has an integer ``id`` in the shared numeric
        space with citations.

    Returns
    -------
    str
        ``prose`` unchanged if every marker is valid; otherwise the
        prose with orphan markers removed. Whitespace around stripped
        markers is left as-is — the LLM's surrounding punctuation
        usually still reads cleanly, and aggressive re-spacing would
        risk altering meaningful prose.
    """
    used = {int(m) for m in MARKER_RE.findall(prose)}
    valid = {c.id for c in citations} | {t.id for t in tool_calls}
    invalid = used - valid
    if not invalid:
        return prose
    log.warning(
        Events.AGENT_HALLUCINATED_CITATION,
        invalid_ids=sorted(invalid),
        valid_ids=sorted(valid),
    )
    return MARKER_RE.sub(
        lambda m: m.group(0) if int(m.group(1)) in valid else "",
        prose,
    )
