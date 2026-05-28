"""Tests for the agent bootstrap module.

Covers describe_view (the SELECT-safe column-list query),
build_tool_definitions (Anthropic tools= shape + placeholder
substitution), compute_always_on_chunk_ids (14 always-on chunks),
and the AgentContext dataclass immutability.
"""

import dataclasses

import duckdb
import pytest

from customs_agent.agent.bootstrap import (
    AgentContext,
    build_tool_definitions,
    compute_always_on_chunk_ids,
    describe_view,
)

# ─────────────────────────────────────────────────────────────────────────────
# describe_view
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_describe_view_returns_sorted_columns(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    cols = describe_view(duckdb_con, "entries_v")
    assert isinstance(cols, tuple)
    assert len(cols) == 32  # matches the hardcoded ENTRIES_V_COLUMNS
    assert list(cols) == sorted(cols)
    assert "entry_number" in cols
    assert "total_mpf_capped" in cols


@pytest.mark.unit
def test_describe_view_returns_entry_lines_v_columns(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    cols = describe_view(duckdb_con, "entry_lines_v")
    assert len(cols) == 44
    assert "hts_code" in cols
    assert "country_of_origin_code" in cols
    assert "is_shell" in cols  # added by entry_lines_v over base entry_lines


@pytest.mark.unit
def test_describe_view_unknown_view_raises(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Bootstrap-time failure is better than shipping an empty allowlist."""
    with pytest.raises(ValueError) as exc:
        describe_view(duckdb_con, "no_such_view")
    assert "no columns" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# build_tool_definitions
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_build_tool_definitions_returns_five_tools(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    defs = build_tool_definitions(duckdb_con)
    names = {d["name"] for d in defs}
    assert names == {
        "effective_duty_rate", "total_duty_breakdown", "hold_summary",
        "query_entries", "lookup_knowledge",
    }


@pytest.mark.unit
def test_each_tool_definition_has_required_keys(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Every Anthropic tool def must have name, description, input_schema."""
    defs = build_tool_definitions(duckdb_con)
    for d in defs:
        assert set(d.keys()) == {"name", "description", "input_schema"}
        assert isinstance(d["name"], str) and d["name"]
        assert isinstance(d["description"], str) and d["description"]
        assert isinstance(d["input_schema"], dict)
        assert d["input_schema"].get("type") == "object"


@pytest.mark.unit
def test_query_entries_description_has_no_leftover_placeholders(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """The {available_columns_*} tokens must be substituted, not sent
    raw to Anthropic. A leftover token means the substitution helper
    was bypassed or the description template lost a key."""
    defs = build_tool_definitions(duckdb_con)
    qe = next(d for d in defs if d["name"] == "query_entries")
    assert "{available_columns_entries_v}" not in qe["description"]
    assert "{available_columns_entry_lines_v}" not in qe["description"]
    # And it should have REAL column names substituted in
    assert "entry_number" in qe["description"]
    assert "hts_code" in qe["description"]


@pytest.mark.unit
def test_other_tool_descriptions_are_static(
    duckdb_con: duckdb.DuckDBPyConnection,
) -> None:
    """Only query_entries gets description-overrides; the other 4 use
    their registered description unchanged."""
    defs = build_tool_definitions(duckdb_con)
    for d in defs:
        if d["name"] == "query_entries":
            continue
        # No template tokens in any other tool description
        assert "{" not in d["description"], (
            f"{d['name']} description contains unsubstituted template token"
        )


# ─────────────────────────────────────────────────────────────────────────────
# compute_always_on_chunk_ids
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_always_on_chunk_ids_has_14_chunks() -> None:
    """6 rules + 4 quirks + 4 metrics = 14 always-on chunks."""
    ids = compute_always_on_chunk_ids()
    assert isinstance(ids, frozenset)
    assert len(ids) == 14


@pytest.mark.unit
def test_always_on_chunk_ids_includes_ground_truth_required() -> None:
    """The 4 always-on chunk_ids cited in ground_truth.py
    EXPECTED_CITATIONS must be present so dedup correctly removes them
    from the retrieved-knowledge injection."""
    ids = compute_always_on_chunk_ids()
    for required in (
        "rule_1_date_filtering",
        "rule_2_entry_vs_line_count",
        "quirk_1_section_301_china_only",
        "quirk_2_ieepa_feb_2025",
        "metric_effective_duty_rate",
        "metric_hold_rate_benchmark",
    ):
        assert required in ids, (
            f"{required} should be always-on (ground truth depends on it)"
        )


@pytest.mark.unit
def test_always_on_excludes_non_always_on_kinds() -> None:
    """Concepts / duty programs / customer profiles / QBR template /
    column defs / relationships are NOT always-on."""
    ids = compute_always_on_chunk_ids()
    for not_always_on in (
        "concept_entry_number",
        "duty_primary_duty",
        "customer_profile_mhf",
        "qbr_structure",
        "column_definitions",
        "relationships_and_joins",
        "hts_format_xxxx_xx_xxxx",  # duty_program kind
    ):
        assert not_always_on not in ids


# ─────────────────────────────────────────────────────────────────────────────
# AgentContext immutability
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_agent_context_is_frozen() -> None:
    """frozen=True so callers can't mutate the context mid-request."""
    fields = dataclasses.fields(AgentContext)
    field_names = {f.name for f in fields}
    assert field_names == {
        "con", "retriever", "client", "tool_definitions", "always_on_chunk_ids",
    }
    # Verify it's frozen by attempting an assignment via dataclasses' check.
    assert AgentContext.__dataclass_params__.frozen  # type: ignore[attr-defined]


@pytest.mark.unit
def test_agent_context_factory_builds_complete_context(
    agent_context_factory,
) -> None:
    ctx = agent_context_factory()
    assert ctx.con is not None
    assert ctx.retriever is not None
    assert ctx.client is not None
    assert len(ctx.tool_definitions) == 5
    assert len(ctx.always_on_chunk_ids) == 14
