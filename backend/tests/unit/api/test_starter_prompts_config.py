"""Unit tests for :mod:`customs_agent.config.starter_prompts`.

Treats :data:`STARTER_PROMPTS` as a static data contract: 6 chips,
all four tiers + meta covered, no duplicate IDs, no title over the
Fork 33 truncation budget, and round-trip ``model_dump()`` shapes
match what the frontend expects.

The HTTP layer (:mod:`customs_agent.api.starter_prompts`) is covered
end-to-end by ``tests/integration/test_starter_prompts.py`` on chunk
3a; this file deliberately tests only the data contract so a
typo-level regression surfaces before it reaches the integration
boundary.
"""

import pytest

from customs_agent.config.starter_prompts import (
    STARTER_PROMPTS,
    StarterPrompt,
)


@pytest.mark.unit
def test_starter_prompts_count_is_six() -> None:
    """Fork 30 spec: 6 chips covering Q1, Q2, Q4, Q5, Q6, meta."""
    assert len(STARTER_PROMPTS) == 6


@pytest.mark.unit
def test_all_chips_are_starter_prompt_instances() -> None:
    """No accidental dicts or other types in the list."""
    for chip in STARTER_PROMPTS:
        assert isinstance(chip, StarterPrompt)


@pytest.mark.unit
def test_chip_ids_are_unique() -> None:
    """The ``id`` field is the analytics/dedup key; duplicates would
    silently merge frontend telemetry."""
    ids = [chip.id for chip in STARTER_PROMPTS]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_chip_titles_under_40_chars() -> None:
    """Fork 33 truncates chip labels at 40 chars; longer titles would
    visually truncate. The Pydantic ``max_length=40`` constructor
    validator already catches this, but a redundant test documents
    the constraint as part of the data contract."""
    for chip in STARTER_PROMPTS:
        assert len(chip.title) <= 40, (
            f"chip {chip.id!r} title {chip.title!r} exceeds 40-char budget"
        )


@pytest.mark.unit
def test_all_tiers_represented() -> None:
    """The 6 chips cover all 4 difficulty tiers plus the meta tier."""
    tiers = {chip.tier for chip in STARTER_PROMPTS}
    assert tiers == {"tier_1", "tier_2", "tier_3", "tier_4", "meta"}


@pytest.mark.unit
def test_categories_cover_all_tool_routes() -> None:
    """Each non-meta category routes to a distinct tool. The set spans
    the 5 tools the agent will exercise for tier-graded questions."""
    categories = {chip.category for chip in STARTER_PROMPTS}
    assert "volume" in categories
    assert "value" in categories
    assert "duty_breakdown" in categories
    assert "effective_rate" in categories
    assert "hold_rate" in categories
    assert "meta" in categories


@pytest.mark.unit
def test_model_dump_round_trip_shape() -> None:
    """``model_dump()`` produces a dict with exactly the 5 declared
    fields. The handler in ``api/starter_prompts.py`` calls
    ``model_dump`` on each chip; this test pins the shape the frontend
    will see."""
    dumped = STARTER_PROMPTS[0].model_dump()
    assert set(dumped.keys()) == {"id", "title", "prompt", "category", "tier"}


@pytest.mark.unit
def test_model_is_frozen_and_rejects_extra() -> None:
    """Configuration drift defense: extra keys fail at construction
    (typo in a chip definition surfaces at boot), and existing chips
    can't be mutated post-construction."""
    with pytest.raises(Exception):  # noqa: B017 — covers FrozenInstance + ValidationError
        STARTER_PROMPTS[0].title = "mutated"  # type: ignore[misc]

    with pytest.raises(Exception):  # noqa: B017
        StarterPrompt(
            id="x",
            title="x",
            prompt="x",
            category="volume",
            tier="tier_1",
            unknown_field="should not be allowed",  # type: ignore[call-arg]
        )
