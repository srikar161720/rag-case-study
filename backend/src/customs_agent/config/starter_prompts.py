"""Empty-state chip definitions (Fork 30).

Six starter prompts covering the four question tiers the agent
answers plus a meta capability prompt. The same
:data:`STARTER_PROMPTS` list will be imported by:

- :mod:`customs_agent.api.starter_prompts` — exposes them to the
  frontend at ``GET /api/starter-prompts``.
- The Fork 25 off-domain refusal handler — single source of truth
  for "what can the agent actually answer about?" so the refusal
  message can quote examples that are guaranteed in-scope.

**Title length is capped at 40 characters** to match the frontend's
chip-truncation budget (Fork 33).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Tiers mirror the four classes of question the eval suite covers
# (Fork 43); ``meta`` is for capability/scoping questions that aren't
# data queries at all.
StarterPromptTier = Literal["tier_1", "tier_2", "tier_3", "tier_4", "meta"]

# Categories shape downstream telemetry and refusal-suggestion grouping
# (Fork 25). They map to the dominant tool used to answer each example:
# - volume / value: ``query_entries`` aggregations
# - duty_breakdown: ``total_duty_breakdown``
# - effective_rate: ``effective_duty_rate``
# - hold_rate: ``hold_summary``
# - meta: ``lookup_knowledge`` or pure agent response (no tool)
StarterPromptCategory = Literal[
    "volume",
    "value",
    "duty_breakdown",
    "effective_rate",
    "hold_rate",
    "meta",
]


class StarterPrompt(BaseModel):
    """A single empty-state chip.

    Fields are immutable (``frozen=True``) and the model rejects extra
    keys (``extra="forbid"``) so a typo in a chip definition fails at
    boot rather than silently shipping a malformed payload.
    """

    id: str
    """Stable identifier used by the frontend for analytics + dedup."""

    title: str = Field(max_length=40)
    """Chip label shown to the user. Truncated at 40 chars (Fork 33)."""

    prompt: str
    """The text injected into the chat input when the chip is clicked."""

    category: StarterPromptCategory
    """Routing hint for telemetry + Fork 25 refusal suggestions."""

    tier: StarterPromptTier
    """Question complexity tier per Fork 43's evaluation rubric."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# Six chips covering Q1 (volume), Q2 (value), Q4 (duty breakdown),
# Q5 (effective rate), Q6 (hold rate), plus one meta capability prompt.
# Ordering reflects the recommended UI order (simple → complex →
# meta).
STARTER_PROMPTS: list[StarterPrompt] = [
    StarterPrompt(
        id="q1_volume_mhf_q1_2025",
        title="MHF entries in Q1 2025",
        prompt="How many entries did MHF file in Q1 2025?",
        category="volume",
        tier="tier_1",
    ),
    StarterPrompt(
        id="q2_value_pca_feb_2025",
        title="PCA value in February 2025",
        prompt="What was the total entered value for PCA in February 2025?",
        category="value",
        tier="tier_1",
    ),
    StarterPrompt(
        id="q4_duty_breakdown_sag_q1_2025",
        title="SAG duty breakdown in Q1 2025",
        prompt="Break down total duties for SAG in Q1 2025.",
        category="duty_breakdown",
        tier="tier_2",
    ),
    StarterPrompt(
        id="q5_effective_rate_pca_cn",
        title="PCA effective duty rate, China",
        prompt="What's PCA's effective duty rate on CN-origin entries in Q1 2025?",
        category="effective_rate",
        tier="tier_3",
    ),
    StarterPrompt(
        id="q6_hold_rate_mhf",
        title="MHF hold rate vs benchmark",
        prompt="Show MHF's hold rate this quarter — is it within benchmark?",
        category="hold_rate",
        tier="tier_4",
    ),
    StarterPrompt(
        id="meta_capabilities",
        title="What can you help with?",
        prompt="What kinds of questions can you answer about our customs entries?",
        category="meta",
        tier="meta",
    ),
]
