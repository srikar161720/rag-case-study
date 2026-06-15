"""Refusal detection via hidden marker prefix (Fork 25).

The spec leaves the *mechanism* for refusal detection open — only the
five categories (``off_domain`` / ``out_of_range`` / ``unmapped`` /
``meta`` / ``adversarial``) and the user-facing behavior. This branch
locks the mechanism in: the LLM signals refusal by prepending an
HTML-comment marker to its response on the first line::

    <!-- refusal:off_domain -->
    I'm focused on customs analytics for MHF, PCA, and SAG over...

The rule is authored in ``prompts/scope.md`` (the "Internal refusal
marker rule" section); this module is the backend's matching
detector. The agent loop calls :func:`detect_refusal` once after the
final LLM response and routes the result into
:class:`customs_agent.agent.contracts.ChatResponse` —
``refused: true`` + ``refusal_category: <category>`` when a marker is
present; ``refused: false`` (the normal path) otherwise.

The ``meta`` category is **in-scope** per Fork 25 — questions like
"what can you do?" get full normal answers without the marker. Only
the four refusal categories surface as ``refused: true``.

Why the marker (vs. prose heuristics or a separate classifier LLM
call): it's deterministic, requires zero extra LLM cost, and can't
false-positive on legitimate in-scope prose that happens to say "I'm
focused on...". The trade-off is the system prompt has to teach the
LLM the rule; that's covered in ``scope.md`` and locked by the
prompt-snapshot test.
"""

import re
from typing import get_args

import structlog

from customs_agent.agent.contracts import RefusalCategory
from customs_agent.observability.events import Events

log = structlog.get_logger()

# Matches an optional leading-whitespace newline tolerance + the marker
# + a trailing newline (consumed). The category captures any \w+ so
# unknown values get logged + ignored rather than treated as refusal —
# defends against the LLM emitting `<!-- refusal:typo -->`.
REFUSAL_MARKER_RE = re.compile(
    r"^\s*<!--\s*refusal\s*:\s*(\w+)\s*-->\s*\n?",
    re.IGNORECASE,
)

VALID_CATEGORIES: frozenset[str] = frozenset(get_args(RefusalCategory))
"""Closed set derived from the :data:`RefusalCategory` Literal — the
contracts module is the single source of truth for category names."""


def detect_refusal(prose: str) -> tuple[RefusalCategory | None, str]:
    """Detect a refusal marker at the start of ``prose`` and split it off.

    Parameters
    ----------
    prose
        The LLM's raw final response. May or may not lead with a
        refusal marker.

    Returns
    -------
    tuple[RefusalCategory | None, str]
        - ``(None, prose)`` if no marker is present (the common path —
          an answered question).
        - ``(category, stripped_prose)`` if a recognized marker is
          present. ``stripped_prose`` is what the user sees.
        - ``(None, prose)`` if a marker is present but the category is
          NOT in :data:`VALID_CATEGORIES`. The unknown category is
          logged at WARNING level for ops follow-up; the marker is
          left in the prose (safer than silently stripping when we
          don't know what the agent meant — the user sees the marker
          and can flag it).
    """
    match = REFUSAL_MARKER_RE.match(prose)
    if not match:
        return None, prose
    category = match.group(1).lower()
    if category not in VALID_CATEGORIES:
        log.warning(
            Events.AGENT_UNKNOWN_REFUSAL_CATEGORY,
            category=category,
            valid_categories=sorted(VALID_CATEGORIES),
        )
        return None, prose
    return category, prose[match.end():]  # type: ignore[return-value]
