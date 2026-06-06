"""System-prompt assembler (Fork 27 + Fork 55).

Concatenates the 7 section files in ``backend/prompts/`` into one
stable system prefix. The prefix is wrapped with an HTML-style
``<!-- PROMPT_VERSION=X.Y.Z -->`` marker so Anthropic's prompt cache
(Fork 55) keys cleanly off ``PROMPT_VERSION`` — bumping the version
rotates the cache deliberately.

Section order is fixed by :data:`SECTION_ORDER`. The total stable
prefix lands around ~2,880 tokens; the 8 tool definitions (passed via
the ``tools=`` parameter on ``messages.create``) cache implicitly with
it for another ~1,100 tokens.

Loading is lazy + cached: the first call to
:func:`build_static_system_prompt` reads the seven files; subsequent
calls return the cached string. The module-level
:data:`STATIC_SYSTEM_PROMPT` triggers the cache at import time so the
agent loop sees a ready-made constant.

Bumping discipline (per CLAUDE.md):

- Any edit to a file under ``backend/prompts/`` requires bumping
  :data:`PROMPT_VERSION` in the same commit.
- The snapshot test in ``tests/unit/agent/test_prompt_snapshot.py``
  fails fast when the rendered prompt drifts without a version bump —
  refresh the snapshot and the version together.
"""

from functools import cache
from pathlib import Path

PROMPT_VERSION: str = "1.2.0"
"""Bump on any edit to a file under ``backend/prompts/``. Rotates the
Anthropic prompt cache deliberately when prompts actually change.

History:

- ``1.0.0`` — initial system prompt on ``feat/prompts-and-tools``.
- ``1.1.0`` — ``scope.md`` gains the "Internal refusal marker rule"
  section paired with the new ``agent/refusal.py`` detector on
  ``feat/agent-loop``.
- ``1.2.0`` — ``tools_guidance.md`` finalizes the 3 specialized tools
  (``top_hts_by_duty``, ``qbr_summary``, ``compare_customers``),
  replacing their "not available on this branch" placeholders on
  ``feat/remaining-tools-and-eval``.
"""

# Project layout: backend/src/customs_agent/agent/prompt.py
#                  → backend/prompts/<section>.md
PROMPT_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent.parent / "prompts"
)

SECTION_ORDER: tuple[str, ...] = (
    "persona",
    "scope",
    "data_overview",
    "knowledge_always_on",
    "behavioral",
    "tools_guidance",
    "output_format",
)
"""Canonical concatenation order per Fork 27. Do not reorder without a
``PROMPT_VERSION`` bump — Anthropic's cache keys on the exact byte
sequence."""


@cache
def build_static_system_prompt() -> str:
    """Read the 7 section files and concatenate into the cached prefix.

    Returns
    -------
    str
        The assembled system prompt, opened with
        ``<!-- PROMPT_VERSION=X.Y.Z -->`` and followed by the section
        files joined with ``\\n\\n``.

    Raises
    ------
    FileNotFoundError
        If any of the 7 section files is missing. The error message
        names the missing file so the fix is obvious.
    """
    parts: list[str] = []
    for name in SECTION_ORDER:
        path = PROMPT_DIR / f"{name}.md"
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing prompt section file: {path} "
                f"(expected one of {SECTION_ORDER})"
            )
        parts.append(path.read_text(encoding="utf-8"))
    return f"<!-- PROMPT_VERSION={PROMPT_VERSION} -->\n\n" + "\n\n".join(parts)


STATIC_SYSTEM_PROMPT: str = build_static_system_prompt()
"""Module-level pre-built system prompt; ready for the agent loop's
``client.messages.create(system=[{type: 'text', text: STATIC_SYSTEM_PROMPT,
cache_control: {'type': 'ephemeral'}}], ...)`` call (Fork 55)."""
