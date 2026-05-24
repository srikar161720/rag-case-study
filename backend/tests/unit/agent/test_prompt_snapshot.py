"""Snapshot test for the assembled system prompt (Fork 27 + 55).

Enforces the bumping discipline from CLAUDE.md: any edit to a file
under ``backend/prompts/`` must also bump ``PROMPT_VERSION`` AND
refresh the snapshot at ``tests/snapshots/system_prompt.md``. The
three changes land in one commit.

Why this test matters:

- Anthropic's prompt cache keys off the byte sequence of the system
  prefix (Fork 55). Silent prompt drift can either rotate the cache
  every PR (cost regression) or keep a stale prompt running long after
  intent has changed (behavior regression).
- ``PROMPT_VERSION`` is the visible signal that the prompt changed on
  purpose. The snapshot file is the diff a reviewer reads to confirm.

To refresh the snapshot after an intentional change:

    cd backend && uv run python -c \\
        "from customs_agent.agent.prompt import build_static_system_prompt; \\
         from pathlib import Path; \\
         build_static_system_prompt.cache_clear(); \\
         Path('tests/snapshots/system_prompt.md').write_text(build_static_system_prompt())"

Then bump ``PROMPT_VERSION`` and stage both in the same commit.
"""

from pathlib import Path

import pytest

from customs_agent.agent.prompt import (
    PROMPT_VERSION,
    SECTION_ORDER,
    build_static_system_prompt,
)

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent.parent / "snapshots" / "system_prompt.md"


@pytest.mark.unit
def test_snapshot_file_exists() -> None:
    """Snapshot file must be committed; missing snapshot is a setup error."""
    assert SNAPSHOT_PATH.is_file(), (
        f"Missing snapshot: {SNAPSHOT_PATH}. Regenerate via the docstring "
        "instructions in this file."
    )


@pytest.mark.unit
def test_assembled_prompt_matches_snapshot() -> None:
    """Assembled prompt must equal the committed snapshot byte-for-byte.

    On failure, the diff is the source of truth — read the diff, decide
    whether the change is intentional, and if so bump ``PROMPT_VERSION``
    and refresh the snapshot in the same commit.
    """
    build_static_system_prompt.cache_clear()
    actual = build_static_system_prompt()
    expected = SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "System prompt drifted from snapshot. "
        f"PROMPT_VERSION={PROMPT_VERSION}. "
        "If this drift is intentional: bump PROMPT_VERSION and refresh "
        f"the snapshot at {SNAPSHOT_PATH}."
    )


@pytest.mark.unit
def test_prompt_starts_with_version_marker() -> None:
    """The cache-boundary marker must lead the assembled prompt verbatim."""
    build_static_system_prompt.cache_clear()
    assembled = build_static_system_prompt()
    expected_marker = f"<!-- PROMPT_VERSION={PROMPT_VERSION} -->"
    assert assembled.startswith(expected_marker), (
        f"First chars: {assembled[:80]!r}; expected to lead with {expected_marker!r}"
    )


@pytest.mark.unit
def test_all_section_files_present() -> None:
    """Every name in SECTION_ORDER must resolve to a real .md file."""
    from customs_agent.agent.prompt import PROMPT_DIR
    for name in SECTION_ORDER:
        path = PROMPT_DIR / f"{name}.md"
        assert path.is_file(), f"Missing section file: {path}"
