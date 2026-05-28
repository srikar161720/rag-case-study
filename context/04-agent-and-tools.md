# Agent and Tools

Authoritative source for the agent loop, the 8-tool surface, the
templated system prompt, the output sidecar contract, ambiguity and
refusal handling, conversation-history pruning, and the determinism /
prompt-cache configuration.

Load this file when working on `backend/src/customs_agent/agent/`,
`backend/src/customs_agent/tools/`, or `backend/prompts/`. SQL-safety
specifics for tool implementations live here at a high level; the
deep detail (column allowlists, `safe_execute`, threat model) is in
`09-security.md`.

---

## Agent Pattern (Fork 2 + Fork 56)

**Hybrid agent pattern**: RAG retrieves rules → LLM picks among **8 typed
tools** → tools run deterministic parameterized SQL or return retrieved
chunks → backend assembles the structured sidecar from real history.
**No raw SQL surface; no `execute_sql(query)` tool.** Rules live in code;
the LLM owns narrative; the backend owns facts.

### Three-model partition by function (Fork 56)

| Job | Model | Where called |
|---|---|---|
| Main agent loop | **`claude-sonnet-4-6`** (Anthropic) | `agent/loop.py` for every chat request |
| Eval judge (Q9 rubric, Fork 8) | `gpt-4o-mini` (OpenAI) | `tests/eval/_grading.py` only during eval runs |
| RAG embeddings (build-time) | `text-embedding-3-small` (OpenAI) | `scripts/build_index.py` during `docker build` only — never at runtime |

Single agent model — **no question-difficulty routing**. Fork 55 prompt
caching makes cost a non-issue (~$3-5/month CI total), so the accuracy
risk of model-mixing isn't worth taking.

### Model alias vs dated pin (G1 nuance)

- Default: use the alias `claude-sonnet-4-6` in `LLMConfig.model`. It's
  what reviewers recognize.
- For strict reproducibility: pin to the dated model ID
  (`claude-sonnet-4-6-YYYYMMDD`) once you've validated against a specific
  snapshot. The alias may rotate to point at a newer snapshot over time;
  the dated ID is immutable. Document as future-work in README's
  "Reproducibility" section.

---

## System Prompt (Fork 27)

**Templated** with a stable cached prefix + volatile per-request suffix.

### Structure (~2,880 stable tokens + tool definitions ~1,100 = ~3,980 cached)

The system prompt is concatenated from 7 modular section files in
`backend/prompts/`, in this order:

| Order | Section file | Authoritative for | ~Tokens |
|---|---|---|---|
| 1 | `persona.md` | Agent role, filer code (Vandegrift 595) | 80 |
| 2 | `scope.md` | Fork 25 — 5-category scope + out-of-scope handling | 250 |
| 3 | `data_overview.md` | Fork 21 — dataset shape, customer codes, schema fingerprint, period helpers, grain selection rule | 200 |
| 4 | `knowledge_always_on.md` | Fork 15 — Business Rules 1-6 + 4 Known Data Quirks + 4 Metric Definitions, generated/synced from RAG corpus | 1,400 |
| 5 | `behavioral.md` | Forks 12, 20, 24 — citation conventions, shell-entry default, ambiguity default+state, format rules | 350 |
| 6 | `tools_guidance.md` | Fork 22 — when to use each of the 8 tools | 400 |
| 7 | `output_format.md` | Fork 28 — markdown, `[N]` markers, HTS/currency/% formatting, no "Sources" footer | 200 |
| **Total stable prefix** | | | **~2,880** |

Plus tool definitions (~1,100 tokens for 8 tools' JSON Schemas, passed
via Anthropic's `tools=` parameter) are cached alongside the system
content.

### `PROMPT_VERSION` constant

```python
# backend/src/customs_agent/agent/prompt.py
from functools import cache
from pathlib import Path

PROMPT_VERSION = "1.0.0"   # bump when section files change

PROMPT_DIR = Path(__file__).parent.parent.parent / "prompts"
SECTION_ORDER = [
    "persona", "scope", "data_overview", "knowledge_always_on",
    "behavioral", "tools_guidance", "output_format",
]

@cache
def build_static_system_prompt() -> str:
    parts = [(PROMPT_DIR / f"{name}.md").read_text() for name in SECTION_ORDER]
    return f"<!-- PROMPT_VERSION={PROMPT_VERSION} -->\n\n" + "\n\n".join(parts)

STATIC_SYSTEM_PROMPT = build_static_system_prompt()
```

The HTML-style version comment is inside the prompt so the cache key
changes cleanly when `PROMPT_VERSION` bumps. Bumping rotates the
Anthropic cache (Fork 55) intentionally — only do this when prompts
actually change.

### Cache boundary placement (Fork 55)

```python
client.messages.create(
    model=LLM_MODEL,
    temperature=0,                                   # Fork 26
    max_tokens=AGENT_OUTPUT_BUDGET,                  # Fork 23
    system=[
        {
            "type": "text",
            "text": STATIC_SYSTEM_PROMPT,            # ~2,880 tokens, stable
            "cache_control": {"type": "ephemeral"},  # ← cache marker
        }
    ],
    tools=TOOL_DEFINITIONS,                          # cached implicitly with prefix
    messages=[
        *conversation_history,                       # may be pruned per G9
        {
            "role": "user",
            "content": [{
                "type": "text",
                "text": (
                    f"<retrieved_knowledge>\n{rag_chunks_md}\n</retrieved_knowledge>\n\n"
                    f"{user_message}"
                ),
            }],
        },
    ],
)
```

Stable prefix above the marker; volatile content (retrieved chunks +
conversation history + current user message) below. Sliding 5-minute
TTL keeps the cache hot across the eval suite's sequential 11 questions
(~7× cost reduction per Fork 55).

### Snapshot test prevents accidental drift

`tests/unit/agent/test_prompt_snapshot.py` snapshots
`STATIC_SYSTEM_PROMPT` and fails PRs that change the prompt without
bumping `PROMPT_VERSION`. Update the snapshot + bump the version in the
same commit.

---

## Tool Surface (Fork 22)

**8 tools across 3 layers.** Every tool returns the shared `ToolResult`
envelope so the agent loop can uniformly extract data, build the sidecar
(Fork 28), and emit Langfuse spans (Fork 52).

### Layer 1 — Specialized domain tools (6 tools — rules baked in)

| Tool | Returns | View | Encodes | Serves |
|---|---|---|---|---|
| `effective_duty_rate(filters)` | `{rate_pct, total_duty, total_entered_value, line_count, breakdown}` | `entry_lines_v` (origin is line-level) | KB §QBR Metrics — Effective Duty Rate formula `(SUM(total_duty_taxes_fees) / SUM(entered_value)) × 100` | **Q5** |
| `total_duty_breakdown(filters)` | `{primary, section_301, ieepa, mpf_capped, mpf_raw, hmf, total_correct, total_line_sum, line_count, entry_count}` | `entries_v` (default) or `entry_lines_v` (when line-level filter present) | MPF cap (Quirk 3), `COALESCE(SUM(section_301_duty), 0)` for Quirk 1, same for IEEPA Quirk 2 | **Q4**, primitive for Q7 / Q9 |
| `hold_summary(filters)` | `{entries_total, entries_on_hold, hold_rate_pct, benchmark_pct: 5.0, status: "below"\|"above"\|"warrants_investigation", hold_reasons: dict}` | `entries_v` | KB §Hold Rate — 5% benchmark + 8% investigation threshold | **Q6**, primitive for Q9 |
| `top_hts_by_duty(filters, limit=5)` | `[{hts_code, hts_description, total_duty, primary, section_301, ieepa, line_count, entered_value}]` | `entry_lines_v` (HTS is line-level) | HTS code formatting `XXXX.XX.XXXX` (KB §1) | **Q8** |
| `qbr_summary(customer_code, period)` | `{entry_volume_by_month: [...], duty_breakdown: {...}, top_countries: [...], hold_summary: {...}}` | composed (calls `total_duty_breakdown` + `hold_summary` + `query_entries`) | KB §QBR template — 4 standard sections | **Q9** |
| `compare_customers(metric, filters)` | `[{customer_code, value, rank}]` ranked descending | `entries_v` (or `entry_lines_v` for line metrics) | Cross-customer ranking in one SQL query — avoids LLM arithmetic | **Q7** |

### Layer 2 — General builder (1 tool)

| Tool | Signature | Aggregations whitelist | Serves |
|---|---|---|---|
| `query_entries` | `(view: Literal["entries_v","entry_lines_v"], filters: EntryFilters, group_by: list[str]=[], aggregations: list[str]=["count_distinct_entries"], order_by: list[tuple[str, "asc"\|"desc"]]=[], limit: int=Field(default=50, ge=1, le=200))` | `count_distinct_entries`, `count_lines`, `sum(<col>)`, `avg(<col>)`, `min(<col>)`, `max(<col>)` (Pydantic-validated against `ALLOWED_AGGREGATIONS` allowlist — Fork 50) | **Q1, Q2, Q3, Q11**, and unseen questions |

### Layer 3 — Knowledge lookup (1 tool)

| Tool | Signature | Serves |
|---|---|---|
| `lookup_knowledge` | `(query: str, top_k: int=5)` returns the Fork 16 hybrid retriever output as a tool result | **Q10** + any meta question about rules / definitions / customer profiles |

### Question-to-tool mapping (all 11 graded questions)

| Q | Tier | Tool path |
|---|---|---|
| 1 | 1 | `query_entries(entries_v, filters={customer_code: PCA, release_year_month: "2025-01"}, aggs=[count_distinct_entries])` |
| 2 | 1 | `query_entries(entries_v, filters={customer_code: SAG, release_year_quarter: "2025-Q1"}, aggs=[sum(total_entered_value)])` |
| 3 | 1 | `query_entries(entries_v, group_by=[port_of_entry_code, port_of_entry_name], aggs=[count_distinct_entries], order_by=[(count_distinct_entries, desc)], limit=1)` |
| 4 | 2 | `total_duty_breakdown(filters={release_year_month: "2024-12"})` → `.section_301` |
| 5 | 2 | `effective_duty_rate(filters={customer_code: MHF, country_of_origin_code: CN, release_year_quarter: "2025-Q1"})` |
| 6 | 2 | `hold_summary(filters={})` |
| 7 | 3 | `compare_customers(metric="ieepa_pct", filters={release_date_from: 2025-02-01, release_date_to: 2025-03-31})` |
| 8 | 3 | `top_hts_by_duty(filters={customer_code: PCA, country_of_origin_code: CN}, limit=5)` |
| 9 | 3 | `qbr_summary(customer_code=SAG, period="2025-Q1")` |
| 10 | 4 | `lookup_knowledge("which date field for monthly queries")` + always-on Rule 1 already present → agent narrates |
| 11 | 4 | `query_entries(entries_v, …, aggs=[count_distinct_entries])` + `query_entries(entry_lines_v, …, aggs=[count_lines])` → agent contrasts |

Every cell is either a deterministic tool call or a deterministic tool
call wrapped by LLM orchestration. **No arithmetic in prose. No SQL in
prose.**

### Shared `ToolResult` contract (Fork 22 + 28)

```python
# backend/src/customs_agent/tools/_shared.py
from typing import Any
from pydantic import BaseModel

class Citation(BaseModel):
    doc: str               # e.g., "duties_fees_tariffs.txt"
    section: str           # e.g., "§Business Rule 1 — Date Filtering"
    chunk_id: str          # links to RAG corpus chunk

class ToolMeta(BaseModel):
    tool_name: str
    sql_executed: str                      # for sidecar + Fork 31 "Show your work"
    view_used: str | None                  # "entries_v" | "entry_lines_v" | None
    filters_applied: dict
    shell_entries_excluded: int            # 0 if include_shell=True or no shells
    rows_inspected: int
    latency_ms: int

class ToolResult(BaseModel):
    data: Any                              # tool-specific payload shape
    meta: ToolMeta
    citations: list[Citation] = []         # KB rules the tool's logic relies on
```

The agent loop unwraps `ToolResult.data` to feed back into the LLM as
`tool_result` content; `ToolResult.meta` + `ToolResult.citations` flow
into the sidecar (Fork 28).

### Example tool implementation (`hold_summary`)

```python
# backend/src/customs_agent/tools/hold_summary.py
import time
import duckdb
from customs_agent.tools._filters import EntryFilters
from customs_agent.tools._shared import (
    build_where_clause, ToolMeta, ToolResult, Citation,
)
from customs_agent.data.safe_exec import safe_execute

def hold_summary(con: duckdb.DuckDBPyConnection, filters: EntryFilters) -> ToolResult:
    where, params = build_where_clause(filters)
    sql = f"""
        SELECT
            COUNT(*)                                 AS total_entries,
            COUNT(*) FILTER (WHERE on_hold)          AS entries_on_hold,
            COALESCE(
                COUNT(*) FILTER (WHERE on_hold) * 100.0
                / NULLIF(COUNT(*), 0), 0
            )                                        AS hold_rate_pct
        FROM entries_v WHERE {where};
    """
    t0 = time.perf_counter()
    row = safe_execute(con, sql, params).fetchone()
    reasons = dict(safe_execute(con, f"""
        SELECT hold_reason, COUNT(*) FROM entries_v
        WHERE {where} AND on_hold AND hold_reason IS NOT NULL
        GROUP BY hold_reason
    """, params).fetchall())

    rate = float(row[2])
    status = (
        "warrants_investigation" if rate > 8.0
        else "above"             if rate > 5.0
        else "below"
    )
    return ToolResult(
        data={
            "entries_total":   row[0],
            "entries_on_hold": row[1],
            "hold_rate_pct":   round(rate, 2),
            "benchmark_pct":   5.0,
            "status":          status,
            "hold_reasons":    reasons,
        },
        meta=ToolMeta(
            tool_name="hold_summary",
            sql_executed=sql.strip(),
            view_used="entries_v",
            filters_applied=filters.model_dump(exclude_none=True),
            shell_entries_excluded=_count_shells_excluded(con, filters),
            rows_inspected=row[0],
            latency_ms=int((time.perf_counter() - t0) * 1000),
        ),
        citations=[
            Citation(doc="customer_profiles_qbr_metrics.txt",
                     section="§Hold Rate",
                     chunk_id="qbr_metric_hold_rate"),
            Citation(doc="duties_fees_tariffs.txt",
                     section="§Business Rule 6 — On-Hold Entries",
                     chunk_id="rule_6_on_hold"),
        ],
    )
```

Every Layer 1 + Layer 2 tool follows this pattern. ~30 lines each.

---

## Pydantic Filters (Fork 21)

Typed `Literal` enums prevent the most common agent failure: invalid
argument values. The LLM literally can't emit `customer_code="Meridian"`
when the type is `Literal["MHF", "PCA", "SAG"]` — that's a schema
violation Anthropic's tool-use rejects before the tool is ever called.

### `EntryFilters` model

```python
# backend/src/customs_agent/tools/_filters.py
from typing import Literal, Optional
from datetime import date
from pydantic import BaseModel, Field

CustomerCode = Literal["MHF", "PCA", "SAG"]
CountryCode  = Literal["CN", "VN", "IN", "ID", "BD", "TW", "KR"]
PortCode     = Literal["1001", "1701", "2704", "2809", "5301"]

class EntryFilters(BaseModel):
    customer_code:          Optional[CustomerCode] = None
    country_of_origin_code: Optional[CountryCode] = None      # line-grain filter only
    port_of_entry_code:     Optional[PortCode] = None
    release_date_from:      Optional[date] = None
    release_date_to:        Optional[date] = None
    release_year_month:     Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}$")
    release_year_quarter:   Optional[str] = Field(None, pattern=r"^\d{4}-Q[1-4]$")
    on_hold:                Optional[bool] = None
    include_shell:          bool = False                       # Fork 20 default
```

### Asymmetric enum policy

Hardcoded `Literal` only for dimensions where the agent's downstream
reasoning depends on knowing each value (customer codes, country codes,
port codes — all have KB rules referencing specific values like
"Section 301 applies only to CN"). For operational dimensions (carrier,
hold_reason, entry_type), use `Optional[str]` with no enum — the agent
doesn't need per-value knowledge.

### Boot-time enum drift check

The data-layer validator (per `02-data-layer.md`) asserts that DB enum
values match the `Literal` definitions. If a new country code appears in
the data without updating the `Literal`, boot fails loudly with the
expected vs actual sets in the error message. Fail-fast > silent
adoption: a new code likely needs human review (new IEEPA mapping, new
customer profile, etc.) before being accepted.

### Schema fingerprint in `query_entries` description

The general builder's tool description (Fork 21) includes an auto-
generated column list from `DESCRIBE entries_v` and `DESCRIBE
entry_lines_v` at boot. This gives the LLM the column knowledge it needs
to build correct filter/group-by/aggregation specs without putting the
full schema in the system prompt.

**Implementation note (`feat/agent-loop`):** The auto-generation lives
in `backend/src/customs_agent/agent/bootstrap.py:build_tool_definitions()`.
The static description in `tools/query_entries.py` carries the literal
placeholder tokens `{available_columns_entries_v}` and
`{available_columns_entry_lines_v}`; at app startup,
`build_tool_definitions(con)` runs `information_schema.columns` against
both views (via `safe_execute` so the SELECT-only guard still applies)
and substitutes the live column lists through
`tools.__init__.format_query_entries_description(...)`. The Anthropic
`messages.create(tools=...)` call receives the substituted definitions;
the placeholder tokens are never sent to the model.

### View-compatibility validator on `QueryEntriesInput`

A `model_validator` on `QueryEntriesInput` (added on `feat/agent-loop`
per PR #5 Copilot review Comment 4) rejects view-incompatible
combinations at the schema boundary BEFORE the SQL builder runs:

- `view="entries_v"` with `filters.country_of_origin_code` set →
  rejected (country is line-grain).
- `view="entries_v"` with a `group_by` entry in `ENTRY_LINES_V_ONLY`
  (e.g., `hts_code`, `mid`) → rejected.
- `view="entries_v"` with an `aggregations` entry referencing a
  line-grain column (e.g., `sum(entered_value)` — the entries_v
  equivalent is `sum(total_entered_value)`) → rejected.
- Symmetric: `view="entry_lines_v"` with an entries_v-only rollup
  (e.g., `sum(total_entered_value)`) → rejected.

The per-view column sets (`ENTRIES_V_COLUMNS`,
`ENTRY_LINES_V_COLUMNS`, plus the precomputed `_ONLY` differences)
ship as hardcoded frozensets in `tools/_allowlists.py`; a drift
test (`tests/unit/tools/test_allowlists.py`) runs `DESCRIBE` on a
live in-memory DuckDB and fails loudly when the constants diverge
from `views.py`. This is intentionally separate from the boot-time
auto-generation above — the description column list reflects all
columns the LLM might see; the safety allowlist is the curated
subset of columns the LLM may use in `group_by` / `aggregations` /
`order_by`.

Error messages include the bad value, the incompatible view, AND
the correct view to switch to, so the LLM can self-correct on the
next iteration of the tool-calling loop.

---

## Agent Loop (Fork 23)

### Configuration

```python
# backend/src/customs_agent/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentConfig(BaseSettings):
    max_iterations:                int  = 5
    max_input_tokens_per_turn:     int  = 50_000
    max_output_tokens_per_turn:    int  = 8_000
    dedup_tool_calls:              bool = True
    model_config = SettingsConfigDict(env_prefix="AGENT_")

class LLMConfig(BaseSettings):
    model:           str           = "claude-sonnet-4-6"   # Fork 5 / G1
    judge_model:     str           = "gpt-4o-mini"         # Fork 8
    embedding_model: str           = "text-embedding-3-small"  # Fork 13
    temperature:     float         = 0.0                   # Fork 26
    seed:            int | None    = 42                    # OpenAI only; Anthropic doesn't expose
    model_config = SettingsConfigDict(env_prefix="LLM_")
```

All env-var overridable (e.g., `AGENT_MAX_ITERATIONS=3` for stricter CI).
Production deployment uses defaults.

### Loop structure (sketch)

```python
# backend/src/customs_agent/agent/loop.py
@observe(name="chat", capture_input=False, capture_output=False)
async def run_agent(
    user_message: str,
    history: list[dict],
    request_id: str,
    *,
    stream: bool = False,
) -> AsyncIterator[AgentEvent] | ChatResponse:
    # 1. Refusal pre-check (Fork 25 - some categories don't need LLM)
    # 2. Retrieved chunks
    retrieved = retriever.retrieve(user_message, k=5)
    # 3. Dedup against always-on (Fork 15 nuance)
    retrieved = [c for c in retrieved if c.chunk_id not in always_on_chunk_ids]
    # 4. History pruning (G9)
    history = prune_history(history, current_user_msg=user_message,
                            retrieved=retrieved)
    # 5. Tool-calling loop
    iterations_used = 0
    seen_tool_calls: dict[str, ToolResult] = {}   # (tool, args_hash) → cached result
    tool_call_traces: list[ToolCallTrace] = []

    while iterations_used < cfg.max_iterations:
        response = await llm_call_with_cache(
            messages=messages, system=STATIC_SYSTEM_PROMPT, tools=TOOL_DEFS,
        )
        iterations_used += 1
        if response.stop_reason == "end_turn":
            break
        if response.stop_reason == "tool_use":
            for block in response.content:
                if block.type == "tool_use":
                    cache_key = (block.name, hash(repr(sorted(block.input.items()))))
                    if cfg.dedup_tool_calls and cache_key in seen_tool_calls:
                        result = seen_tool_calls[cache_key]
                        log.warning("agent.duplicate_tool_call", tool=block.name, ...)
                    else:
                        result = await execute_tool(block.name, block.input)
                        seen_tool_calls[cache_key] = result
                    tool_call_traces.append(_to_trace(block, result))
                    # ... append tool_result message ...
        # Token budget check (Fork 23)
        if total_input_tokens > cfg.max_input_tokens_per_turn:
            log.warning("agent.input_token_budget_hit", tokens=total_input_tokens)
            break

    # 6. Final output validation (Fork 28 + Fork 49 layer 5)
    prose = response.content[-1].text   # final text block
    prose = validate_markers(prose, citations=…, tool_calls=tool_call_traces)
    safe, sanitized, matched = sanity_check_output(prose)
    if not safe:
        log.error("output_safety.redaction", patterns=matched)
        prose = sanitized

    # 7. Sidecar assembly (Fork 28)
    return ChatResponse(
        answer=prose,
        knowledge_citations=_build_citations(prose, retrieved, tool_call_traces),
        tool_calls=tool_call_traces,
        assumptions=_extract_assumptions(prose),
        refused=False,
        meta=ResponseMeta(
            request_id=request_id,
            prompt_version=PROMPT_VERSION,
            model=cfg.model,
            temperature=cfg.temperature,
            iterations_used=iterations_used,
            iteration_limit_hit=(iterations_used >= cfg.max_iterations),
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cached_input_tokens=cached_tokens,
            estimated_cost_usd=estimate_cost(...),  # G11
            ...
        ),
    )
```

### Graceful degradation on limits

Any of three caps trips graceful degradation (never raises):

| Limit | Trigger | Behavior |
|---|---|---|
| `MAX_ITERATIONS = 5` | Loop count hits 5 | Return partial answer + `meta.iteration_limit_hit: true` + invitation to refine |
| `MAX_INPUT_TOKENS_PER_TURN = 50_000` | Input tokens exceed budget mid-loop | Same as above + `meta.budget_limit_hit: true` |
| Duplicate tool call (same `(tool, args_hash)`) | Third identical call within a turn | Return cached result + `meta.duplicate_tool_calls: N` |

User sees prose like: *"I worked through several steps on this question
but reached my computation budget before fully resolving it. Here's what
I found so far: [partial summary]. Could you narrow the question or break
it into parts?"* — never a raw exception.

---

## Ambiguity Handling (Fork 24)

**Default + state assumption + cite the rule.** The agent does not ask
clarifying questions for routine ambiguities — it applies the documented
default from KB Business Rules, states the assumption inline with a
citation, and invites refinement.

### Why never ask

Q10 ("which date field for January?") is the canonical example. The
expected answer is *"Release Date by default, per KB Rule 1, [1]"* —
not *"Did you mean Release Date or Entry Filed Date?"* Asking would
contradict the case study's explicit Ground Rule: *"If something is
ambiguous, make a reasonable decision and document it."*

### Defaults the KB provides for free

| Ambiguity | Default | KB source |
|---|---|---|
| Which date field? | `release_date` | Business Rule 1 |
| Entries vs lines? | State which you computed | Business Rule 2 |
| What's "total duty"? | `total_duty_taxes_fees_correct` (with capped MPF) | Business Rule 3 |
| Origin-based filter grain? | Group by `country_of_origin_code` | Business Rule 4 |
| Include shell entries? | Exclude by default | Business Rule 5 (Fork 20) |
| Include on-hold entries? | Include by default | Business Rule 6 |
| MPF at entry-level? | Apply $31.67 / $614.35 cap | Known Data Quirk 3 |
| Section 301 scope? | CN-origin lines only | Known Data Quirk 1 |
| IEEPA scope? | Release Date ≥ 2025-02-01 | Known Data Quirk 2 |
| HTS code format? | `XXXX.XX.XXXX` with dots | Concept §1 |

Coverage is near-total. The few unaddressed gaps (scope when omitted,
"recent" without a time range) use the same pattern: pick a sane default,
state it, invite refinement.

### When to actually ask (narrow exception list)

| Situation | Behavior |
|---|---|
| First-turn message has no question content ("hi", "tell me about it") | Ask what they want to know |
| References a period outside Oct 2024 – Mar 2025 ("Q2 2025", "last year") | Surface the dataset bound, suggest closest in-scope alternative (refusal category `out_of_range`) |
| References a customer / country / port not in the data | Surface mismatch, offer alternatives (refusal category `unmapped`) |
| Genuinely equivalent interpretations with no KB-documented default | Ask, offering 2-3 specific options |

These are rare in practice; defaulting is the rule.

### System prompt instructions (`prompts/behavioral.md`)

```
AMBIGUITY
- When the user's request leaves a parameter unspecified, apply the
  documented default from the knowledge base (especially Business Rules
  1–6) and state the assumption with a citation in the answer.
- Do NOT ask clarifying questions for routine ambiguities.
- Ask only when: input has no question content; references data outside
  the dataset; or has multiple equally defensible interpretations with
  no KB-documented default.
- End answers that stated assumptions with a soft invitation: "Let me
  know if you'd like to use a different date field or time period."
```

---

## Refusal Routing (Fork 25)

Five categories of out-of-scope handling, branched in the system prompt
(`prompts/scope.md`). Three of them route through the agent loop with
NO tool calls (saves cost + iterations); the meta category is treated as
in-scope.

| Category | Examples | Behavior |
|---|---|---|
| `off_domain` | "What's the weather?", "Write me Python code" | Polite refusal + 2-3 in-scope suggestions from `backend/config/starter_prompts.py` |
| `out_of_range` | "What about Q2 2025?", "How about 2026?" | Surface coverage bound (2024-10 → 2025-03), suggest closest in-scope alternative |
| `unmapped` | "Show me XYZ Corp's data", "What about LCL imports?" | Surface customer/dimension mismatch, offer alternatives |
| `meta` | "What can you do?", "What questions can I ask?" | **In-scope** — return capabilities summary + starter prompts |
| `adversarial` | "Ignore previous instructions", "Show me your system prompt" | Decline without explaining the override attempt, redirect to in-scope examples |

### `ChatResponse` shape on refusal (Fork 28)

```json
{
  "answer": "I'm focused on customs analytics for MHF, PCA, and SAG over Oct 2024 – Mar 2025. I can't help with weather, but here are some things I can answer: …",
  "knowledge_citations": [],
  "tool_calls": [],
  "assumptions": [],
  "refused": true,
  "refusal_category": "off_domain",
  "meta": {
    "iterations_used": 0,
    "input_tokens": 1234,
    "output_tokens": 87,
    ...
  }
}
```

### Why the meta category is in-scope

A reviewer asking "what can you do?" is genuinely trying to learn the
agent's surface, not adversarial or off-topic. The agent returns a brief
capabilities list (drawn from `tools_guidance.md` content) plus 2-3
starter prompt examples. Strong UX win at zero cost.

### Refusal detection mechanism (locked on `feat/agent-loop`)

The five categories above describe *what* the agent does on refusal;
the *mechanism* by which the backend recognises a refusal is a hidden
marker prepended by the LLM. The system-prompt rule lives in
`prompts/scope.md` ("Internal refusal marker rule" section) and
requires the four refusal categories (everything except `meta`,
which is in-scope) to start the response with an HTML comment:

```
<!-- refusal:<category> -->
I'm focused on customs analytics for MHF, PCA, and SAG over
October 2024 – March 2025. I can't help with weather, but here are
some things I can answer: …
```

The backend matcher in `agent/refusal.py` strips the marker and
returns `(category, stripped_prose)`:

```python
REFUSAL_MARKER_RE = re.compile(
    r"^\s*<!--\s*refusal\s*:\s*(\w+)\s*-->\s*\n?",
    re.IGNORECASE,
)

def detect_refusal(prose: str) -> tuple[RefusalCategory | None, str]:
    match = REFUSAL_MARKER_RE.match(prose)
    if not match:
        return None, prose
    category = match.group(1).lower()
    if category not in VALID_CATEGORIES:
        log.warning("agent.unknown_refusal_category", category=category)
        return None, prose
    return category, prose[match.end():]
```

The regex tolerates leading whitespace, internal whitespace around
the colon, and case-insensitive `refusal` to be forgiving of small
LLM phrasing drift. Unknown categories (e.g., `<!-- refusal:typo -->`)
are logged at WARNING and treated as non-refusal — we never silently
fabricate a category that the agent might not have intended.

**Why not heuristic prose matching?** Phrase-based detection
("I'm focused on…", "I can't help with…") would false-positive on
legitimate in-scope prose and false-negative on phrasing drift.
**Why not a separate classifier LLM call?** Doubles per-turn cost
and latency for a problem the system prompt can solve directly.
The marker mechanism is deterministic, cheap, and explicit about
the agent's own classification — bumps `PROMPT_VERSION` (`1.0.0` →
`1.1.0` when the rule landed) intentionally so the prompt cache
rotates at the same moment the detector is wired.

### Single source of truth for suggestion lists

`backend/config/starter_prompts.py` defines 6 starter prompts (Fork 30).
The same list is consumed by:

1. `/api/starter-prompts` endpoint (frontend empty state)
2. `off_domain` refusal handler (Fork 25 category 1 suggestions)

Adding a new starter prompt → one file, propagates everywhere.

---

## Output Sidecar Contract (Fork 28)

**Split authorship**: LLM emits prose with `[N]` citation markers;
backend constructs the citations + tool_calls arrays from real history.
Hallucinated citations become structurally impossible.

### Why split authorship

If the LLM emits the full sidecar JSON itself, it can hallucinate
citations ("see KB §3.2" when there is no such section) or invent
numbers. By making the LLM responsible only for prose + marker
placement, and the backend responsible for citation content + tool call
records, the structural separation prevents the entire class of "agent
fabricated its sources" bug.

### `ChatResponse` shape

```typescript
type ChatResponse = {
  answer: string;                          // markdown prose with [N] markers
  knowledge_citations: Citation[];         // built by backend from real RAG hits
  tool_calls:          ToolCallTrace[];    // built by backend from real tool history
  assumptions:         Assumption[];       // explicit defaults applied (Fork 24)
  refused:             boolean;            // true iff Fork 25 refusal
  refusal_category?:   "off_domain" | "out_of_range" | "unmapped" | "meta" | "adversarial";
  meta:                ResponseMeta;
};

type Citation = {
  id: number;             // matches [N] in answer prose
  kind: "knowledge";
  doc: string;
  section: string;
  chunk_id: string;
  snippet: string;        // 1-2 sentence excerpt
};

type ToolCallTrace = {
  id: number;             // also citeable as [N] — shared number space
  kind: "computation";
  name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  sql_executed?: string;
  view_used?: "entries_v" | "entry_lines_v";
  shell_entries_excluded: number;
  rows_inspected: number;
  latency_ms: number;
};

type Assumption = {
  key: string;            // "date_field", "period_scope", "shell_entries"
  value: string;
  rule_id?: string;       // chunk_id of the rule that justifies it
  rule_section?: string;
};

type ResponseMeta = {
  request_id: string;
  prompt_version: string;
  model: string;
  embedding_model: string;
  temperature: number;
  iterations_used: number;
  iteration_limit_hit: boolean;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
  estimated_cost_usd: number;
  total_latency_ms: number;
  stream_ttft_ms?: number;          // Fork 29 streaming only
  history_truncated_turns?: number; // G9 history pruning
};
```

The shared `[N]` namespace (not `[K1]` / `[T1]`) is simpler for the LLM
and simpler for the user. The frontend (Fork 32) color-codes pills based
on whether `[N]` resolves to a `knowledge_citations` entry or a
`tool_calls` entry.

### Citation marker validator (Fork 28)

```python
# backend/src/customs_agent/agent/validator.py
import re
MARKER_RE = re.compile(r"\[(\d+)\]")

def validate_markers(
    prose: str, citations: list[Citation], tool_calls: list[ToolCallTrace]
) -> str:
    used  = {int(m) for m in MARKER_RE.findall(prose)}
    valid = {c.id for c in citations} | {t.id for t in tool_calls}
    invalid = used - valid
    if not invalid:
        return prose
    log.warning("agent.hallucinated_citation",
                invalid_ids=sorted(invalid),
                valid_ids=sorted(valid))
    return MARKER_RE.sub(
        lambda m: m.group(0) if int(m.group(1)) in valid else "",
        prose
    )
```

If the LLM emits `[99]` when only `[1]`–`[5]` exist, the validator
strips `[99]` from the prose and logs the hallucinated id. ~10 lines.

### Citation ID assignment

The backend builds `knowledge_citations[]` and `tool_calls[]` from real
history, assigning sequential IDs starting at 1. The LLM is **told** what
IDs are available via the message it receives back from tool calls:

```
<tool_results>
[Tool: hold_summary] Result: {"entries_total": 1200, "entries_on_hold": 236,
"hold_rate_pct": 19.67, "status": "warrants_investigation", ...}
Citations available: [1] qbr_metric_hold_rate, [2] rule_6_on_hold
</tool_results>
```

The LLM emits prose referencing those IDs. The backend then assembles
the final sidecar with the matching citation entries.

---

## Determinism (Fork 26)

**`temperature=0` everywhere; `seed=42` on OpenAI judge** (Anthropic
doesn't expose a `seed` parameter for any current model).

### Residual non-determinism

`temperature=0` is not bit-exact reproducible. Floating-point order of
ops, batching, and provider-side load balancing introduce small
variance. Mitigations:

| Layer | Mitigation |
|---|---|
| Tool computation | Deterministic SQL — fully reproducible |
| Eval assertions | Numeric tolerances (`abs`, `rel`) per question in `ground_truth.json` (Fork 43) |
| Tier 4 prose | Phrase assertions on required substrings, not exact match (Fork 46) |
| Q9 rubric | LLM-as-judge at `temperature=0` + `seed=42` for judge stability |

Document in `EVALUATION.md` header: *"Run against PROMPT_VERSION 1.0.0,
embedding model text-embedding-3-small, temperature=0, claude-sonnet-4-6."*

### When to deviate

Never, for the demo. Documented in README's "Design decisions" as a
deliberate choice (correctness over creativity).

---

## Prompt Injection Defense (Fork 49)

Five layers. The first four are structural (deny by typing or
instruction); the fifth is post-hoc redaction. See `09-security.md` for
the full threat model and per-layer rationale; this section names the
agent-side touchpoints.

| Layer | Where it lives | What it catches |
|---|---|---|
| **1. Request-size cap** | `ChatRequest.messages[].content: str = Field(max_length=2000)` | Length-bomb attacks at the API boundary (HTTP 422 before any LLM call) |
| **2. System prompt rule** | `prompts/scope.md` adversarial section | "Ignore previous instructions" / persona hijacks routed to `refused: true, refusal_category: "adversarial"` |
| **3. Typed tool args** | `Literal` enums in `EntryFilters` + tool arg models | Tool-abuse via fictitious customer codes — Pydantic rejects at boundary, schema-level fail-secure |
| **4. Citation validator** | `agent/validator.py` (see above) | Hallucinated `[N]` markers stripped from prose |
| **5. Output sanity scrubber** | `agent/output_safety.py` | Belt-and-suspenders: post-LLM regex scan for prohibited patterns (API key shapes, env var names, system prompt fingerprint); on match, full-response redaction |

### Layer 5: output_safety.py

```python
# backend/src/customs_agent/agent/output_safety.py
import re

PROHIBITED_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    re.compile(r"\bpk-lf-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b(BACKEND_API_KEY|ANTHROPIC_API_KEY|OPENAI_API_KEY)\b"),
    re.compile(r"<!-- PROMPT_VERSION="),     # system prompt fingerprint
    re.compile(r"fly secrets set", re.IGNORECASE),
]

def sanity_check_output(answer: str) -> tuple[bool, str, list[str]]:
    matches = [p.pattern for p in PROHIBITED_PATTERNS if p.search(answer)]
    if matches:
        return (False,
                "[response redacted: contained prohibited content; the operator has been notified]",
                matches)
    return (True, answer, [])
```

Under normal operation this layer never fires — no secrets are in the
system prompt or knowledge corpus. When it does fire, it's evidence of
something genuinely wrong: either a system prompt change introduced a
sensitive string, or an injection extracted one. Either way, hard fail
beats partial leak.

### What's deliberately NOT defended (out of scope for demo)

- Multi-turn context-building jailbreaks (mitigated some by typed args
  + system prompt, not 100%)
- Token-smuggling via specific unicode characters
- Indirect injection via untrusted dataset content (the dataset is
  synthetic; this would be production future-work)
- Sophisticated "DAN" jailbreaks

Documented in README's "Security considerations" section as honest
scoping (G7 + Fork 49).

---

## SQL Safety Touchpoints (Fork 50)

The agent never authors SQL. Every tool uses:

1. **Parameterized values** via `build_where_clause(filters)` (`?`
   placeholders, never string interpolation)
2. **Column-name allowlists** for `query_entries` `group_by`,
   `aggregations`, `order_by` (Pydantic validators against `ALLOWED_*`
   frozensets)
3. **SELECT-only guardrail** via `safe_execute(con, sql, params)`
   wrapping every `con.execute`

See `09-security.md` for the full breakdown of these three layers + the
threat model. The tool-side application is straightforward: import
`safe_execute` from `data/safe_exec.py`, validate filter args via
Pydantic, call once per query.

---

## History Pruning (G9)

Conversation history is pruned at the agent loop before the LLM call
when token-budget threshold is exceeded. The pruning is invisible to the
user except for a sidecar signal.

### Decisions

| Aspect | Choice |
|---|---|
| **Trigger** | Estimated input tokens > 50K (`AGENT_MAX_INPUT_TOKENS_PER_TURN`) |
| **Eviction unit** | Whole user+assistant turn pairs (never split a pair) |
| **Eviction order** | Oldest first |
| **Never evict** | System message; current user message; retrieved chunks for current query; last 2 turn pairs minimum |
| **User signal** | `meta.history_truncated_turns: int` in sidecar; frontend shows a subtle "earlier history truncated to fit context" banner above the relevant message when > 0 |
| **Token counting** | `anthropic.tokens.count_messages()` for accuracy; falls back to `len(text) // 4` heuristic if API call fails |

```python
# backend/src/customs_agent/agent/history.py
def prune_history(
    history: list[Message],
    current_user_msg: str,
    retrieved: list[Chunk],
    static_prefix_tokens: int = ~3980,   # Fork 55 cached prefix
    budget: int = 50_000,
) -> tuple[list[Message], int]:
    """Returns (pruned_history, n_pairs_dropped)."""
    fixed_overhead = static_prefix_tokens + estimate(retrieved) + estimate(current_user_msg)
    available = budget - fixed_overhead

    if estimate(history) <= available:
        return history, 0

    # Always keep last 2 turn pairs (4 messages); evict oldest
    keep_tail = history[-4:]
    candidates = history[:-4]
    dropped = 0
    while candidates and estimate(candidates + keep_tail) > available:
        # Drop oldest pair (2 messages: user + assistant)
        candidates = candidates[2:]
        dropped += 1
    return candidates + keep_tail, dropped
```

### Future work

LLM-summarized compaction (replace dropped turns with synthesized
`[Earlier discussion: X, Y, Z]` via a cheap model); user-pinnable "keep
this turn" markers; persistent compaction (compacted summaries written
back to `localStorage` per Fork 33).

---

## Composition with Other Layers

- **`03-rag-layer.md`**: agent loop calls `retriever.retrieve(query,
  k=5)` once per request before the first LLM call; chunks land in the
  user message below the cache boundary.
- **`02-data-layer.md`**: tools call `safe_execute(con, sql, params)`
  against `entries_v` / `entry_lines_v` views; `build_where_clause`
  reads `EntryFilters` to construct the parameterized `WHERE`.
- **`05-api-and-backend.md`**: `/chat` and `/chat/stream` endpoints
  delegate to `run_agent()` and surface the `ChatResponse` (or stream
  events derived from it per Fork 29).
- **`06-frontend.md`**: frontend `<Chat>` renders prose; `<AgentPanel>`
  populates from `tool_calls[]` + `knowledge_citations[]` +
  `assumptions[]`; `<CitationMarker>` resolves `[N]` against both arrays.
- **`08-cicd-and-testing.md`**: Fork 45 Layer 2 integration tests use
  `StubLLM` with scripted responses to verify control flow (tool
  selection, iteration cap, dedup, refusal routing, citation
  validation); Fork 45 Layer 3 eval tests exercise the real model.
- **`09-security.md`**: all five injection layers + SQL safety touch
  points have their full threat model and per-layer rationale here.
- **`10-observability.md`**: every tool emits a Langfuse `tool.<name>`
  span; agent loop emits `chat` trace + nested `rag.retrieve`,
  `llm.call`, `output.validation` spans.

---

## Future Work (agent + tools)

| Item | Trigger |
|---|---|
| Discriminated unions for `ToolCallTrace.args` / `result` per tool | When frontend needs per-tool rendering (specialized chart components) |
| Per-tool `examples=[…]` for Anthropic's tool definitions | If LLM consistently misroutes between tools |
| Plan-then-execute split (Sonnet plans, Haiku executes) | Latency optimization for long Tier 3 responses |
| Classifier-based model routing (cheap classifier → Haiku or Sonnet) | When per-question cost becomes meaningful |
| Fine-tuned customs-specific routing model | At Pedestal scale |
| LLM-summarized history compaction (G9 follow-on) | When conversations regularly exceed 50K tokens |
| Dated model pin (e.g., `claude-sonnet-4-6-YYYYMMDD`) for strict reproducibility | When EVALUATION.md needs to be re-verifiable months later |
| Provider-fallback router (Anthropic ↔ OpenAI) | Production reliability |
| Long-context model variant (Sonnet 1M-token variants) | When persistent multi-day conversations matter |
| Per-tool retrieval bypass (some tools don't need RAG context) | When latency budget tightens |
| Metadata-aware retrieval filtering (`section_kind` filter for Tier 4) | When unseen-question diversity reveals patterns |

All deferred. The plan ships with the simplest correct version of each
choice.
