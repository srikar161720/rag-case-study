# Observability

Authoritative source for the two-layer observability stack: structlog
stdout JSON (app events) + Langfuse Cloud (agent reasoning traces).
Also covers the per-request log schema, the pricing module + cost
tracking, prompt-cache effectiveness measurement, performance budgets,
PII / retention policy, and provider cost alerts.

Load this file when working on
`backend/src/customs_agent/observability/`, the `request_logging_middleware`,
Langfuse `@observe` decorators, or any cost / latency tracking.

---

## Two-Sink Architecture (Forks 10, 54)

Two stores tuned to their content type. Same `request_id` joins both.

```
                                ┌──────────────────────────────┐
                                │  fly logs (CLI + Web UI)     │
                                │  ~5-day retention            │
                          ┌────►│  Used by: developer +        │
                          │     │  reviewer for app events,    │
┌───────────────────┐  stdout   │  security forensics,         │
│ FastAPI app       │  JSON     │  rate-limit debugging        │
│ (Fly machine, iad)│ ─────────►└──────────────────────────────┘
│                   │
│  ┌──────────────┐ │
│  │ agent.run    │ │  HTTPS    ┌──────────────────────────────┐
│  │  (@observe)  │ │ ─────────►│  Langfuse Cloud              │
│  └──────────────┘ │  SDK      │  30-day retention            │
└───────────────────┘  (async   │  Used by: developer +        │
                       batched) │  reviewer for agent trace    │
                                │  inspection; EVALUATION.md   │
                                │  trace links per question    │
                                └──────────────────────────────┘
```

| Sink | Captures | Format | Retention | Access |
|---|---|---|---|---|
| **stdout JSON** | App-level events (Fork 52 taxonomy below) | structlog one-line-per-event JSON | ~5 days (Fly free tier) | `fly logs --tail`, `fly logs --since 1h \| jq` |
| **Langfuse Cloud** | Agent reasoning (`rag.retrieve`, `llm.call`, `tool.*`, `output.validation` spans) | Hierarchical trace + nested spans | 30 days (Langfuse free tier) | https://cloud.langfuse.com web UI; trace URL in stdout completion log |

Same `request_id` (UUID, `req_<12 hex>`) flows into both stores; the
`request.completed` stdout line carries `langfuse_trace_url` for one-
click pivot from grep'd log to visual trace.

---

## stdout JSON via structlog (Fork 54)

### Configuration with dev/prod renderer split

```python
# backend/src/customs_agent/observability/logging.py
import logging
import os
import structlog
from structlog.contextvars import merge_contextvars
from .scrubber import scrub_secrets  # Fork 53 secret-shape redaction processor


def configure_logging() -> None:
    """Configure structlog. Production emits JSON; dev emits pretty-printed colors."""
    env = os.getenv("ENVIRONMENT", "development")
    shared_processors = [
        merge_contextvars,                              # request_id flows here
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        scrub_secrets,                                  # Fork 53 — redact secret-shape strings
    ]
    if env == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger()
```

`ENVIRONMENT=production` is set in `fly.toml`'s `[env]` block. Local
dev leaves it unset → pretty colored output. Single config file.

### Request-logging middleware (Fork 52)

```python
# backend/src/customs_agent/observability/logging.py (continued)
import time
import uuid
from contextvars import ContextVar
from fastapi import Request

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


async def request_logging_middleware(request: Request, call_next):
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id          # exposed to endpoints
    request_id_var.set(request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id)

    api_key = request.headers.get("X-API-Key", "")
    log.info(
        "request.received",
        path=request.url.path,
        method=request.method,
        client_ip=request.client.host if request.client else None,
        api_key_prefix=api_key[:8] if api_key else None,
    )

    start = time.perf_counter()
    try:
        response = await call_next(request)
        log.info(
            "request.completed",
            path=request.url.path,
            status=response.status_code,
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        return response
    except Exception as e:
        log.error(
            "request.failed",
            path=request.url.path,
            error_class=type(e).__name__,
            error_message=str(e),
            latency_ms=int((time.perf_counter() - start) * 1000),
        )
        raise
    finally:
        structlog.contextvars.clear_contextvars()
```

### What's logged in stdout (Fork 52 — what gets captured here)

App-level events only. **No** full user message content, **no**
retrieved chunk text, **no** LLM response prose. Those live in Langfuse.

Fields per event:

| Field | Always present | Sometimes present |
|---|---|---|
| `timestamp` (ISO) | ✅ | |
| `level` (info/warning/error) | ✅ | |
| `event` (taxonomy name) | ✅ | |
| `request_id` | ✅ (via contextvars) | |
| `path`, `method`, `status`, `latency_ms` | ✅ on HTTP events | |
| `client_ip` | ✅ on `request.*` | |
| `api_key_prefix` (8 chars only) | | only when key was present (Fork 48) |
| `user_message_length` | | only on `request.received` for /chat |
| `user_message_preview` (80 chars) | | **only** on `agent.refusal` events for security forensics (Fork 49) |
| `error_class`, `error_message` | | only on errors |
| `tools_called` (names only) | | only on `request.completed` for /chat |
| `iterations_used`, `iteration_limit_hit` | | only on `request.completed` for /chat |
| `input_tokens`, `output_tokens`, `cached_input_tokens` | | only on `request.completed` for /chat |
| `langfuse_trace_url` | | only on `request.completed` for /chat |
| `refused`, `refusal_category` | | only on `agent.refusal` |
| `patterns_matched` (output safety) | | only on `output_safety.redaction` |
| `bucket`, `limit`, `retry_after` | | only on `ratelimit.hit` |
| `field`, `invalid_values` | | only on `sql_safety.invalid_column_name` |

---

## Event Taxonomy (Fork 52)

Canonical list of stdout JSON event names. Every event uses one of
these; adding a new event is a Fork-58-style code change with a single
naming convention.

| Event | Level | Source | Payload (beyond defaults) |
|---|---|---|---|
| `request.received` | info | middleware | `path`, `method`, `client_ip`, `api_key_prefix`, `user_message_length` (for /chat) |
| `request.completed` | info | middleware | `status`, `latency_ms`, `iterations_used`, `input_tokens`, `output_tokens`, `cached_input_tokens`, `refused`, `tools_called`, `langfuse_trace_url` |
| `request.failed` | error | middleware | `status`, `latency_ms`, `error_class`, `error_message` |
| `auth.missing_key` | warning | `require_api_key` | `client_ip`, `path` |
| `auth.invalid_key` | warning | `require_api_key` | `api_key_prefix` (the bad value's prefix), `client_ip`, `path` |
| `ratelimit.hit` | warning | slowapi exception handler | `bucket`, `endpoint`, `limit`, `retry_after` |
| `cors.preflight_rejected` | warning | CORSMiddleware wrapper | `origin`, `method` |
| `agent.refusal` | info | refusal routing | `refusal_category`, `user_message_preview` (80 chars max) |
| `agent.iteration_limit` | warning | agent loop | `iterations_used`, `limit` |
| `agent.duplicate_tool_call` | warning | agent loop dedup | `tool_name`, `args_hash` |
| `agent.input_token_budget_hit` | warning | agent loop | `tokens_used`, `budget` |
| `agent.trace_created` | info | agent loop | `langfuse_trace_url` |
| `output_safety.redaction` | error | output_safety scrubber | `patterns_matched` |
| `sql_safety.invalid_column_name` | warning | Pydantic validator | `field` (e.g., `group_by`), `invalid_values` |
| `sql_safety.unsafe_sql_blocked` | error | `safe_execute` | `sql_prefix` (first 80 chars), `tool_name` |
| `agent.hallucinated_citation` | warning | validator | `invalid_ids`, `valid_ids` |
| `data.validation.complete` | info | boot-time | `rows`, `distinct_entries`, `shell_entries_detected` |
| `langfuse.flush_failed` | warning | Langfuse SDK callback | `error_class` |

Naming: dot-separated `<domain>.<verb>` form. Add new events sparingly
and in the corresponding fork's scope (Fork 58 commit hygiene).

---

## Langfuse Cloud — Agent Traces (Fork 52)

### Trace structure per chat request

```
trace: "chat-{request_id}"
├── input:    user_message
├── output:   final_assistant_message
├── user_id:  api_key_prefix (8 chars)
├── session_id: conversation_id (if provided by frontend)
├── metadata: {
│     request_id, prompt_version, model, embedding_model, judge_model,
│     temperature, seed, iterations_used, iteration_limit_hit,
│     input_tokens, output_tokens, cache_creation_input_tokens,
│     cache_read_input_tokens, estimated_cost_usd,
│     refused, refusal_category, output_safety_redacted,
│     stream_ttft_ms, history_truncated_turns, shell_entries_excluded
│   }
│
├── span: "rag.retrieve"
│   ├── input:  { query, k }
│   ├── output: { chunks: [{chunk_id, doc, section, score_semantic, score_bm25, score_rrf}, …] }
│   └── metadata: { retriever: "hybrid_rrf", rrf_constant: 60 }
│
├── span: "llm.call" (iteration 1)
│   ├── input:  { messages, tools_offered }
│   ├── output: { type, content }
│   └── metadata: { model, temperature, input_tokens, output_tokens, cached_input_tokens, latency_ms }
│
├── span: "tool.<name>" (per tool execution)
│   ├── input:  { args }
│   ├── output: { data, meta }
│   └── metadata: { sql_executed, view_used, rows_inspected, shell_entries_excluded, latency_ms }
│
├── span: "llm.call" (iteration 2 — final)
│   └── ...
│
└── span: "output.validation"
    ├── input:  { prose_with_markers }
    ├── output: { prose_validated }
    └── metadata: { orphan_markers_stripped, prohibited_patterns_matched }
```

Span hierarchy mirrors the agent loop. Reviewers can expand any span
to see its inputs / outputs / cost / latency.

### Wiring via `@observe` decorators

```python
# backend/src/customs_agent/observability/langfuse.py
from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context

langfuse = Langfuse()    # reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST

# In agent/loop.py:
@observe(name="chat", capture_input=False, capture_output=False)
async def run_agent(user_message: str, history: list, request_id: str, ...):
    langfuse_context.update_current_observation(
        input={"user_message": user_message},
        user_id=api_key_prefix,
        session_id=conversation_id,
        metadata={
            "request_id":      request_id,
            "prompt_version":  PROMPT_VERSION,
            "model":           settings.llm_model,
            "embedding_model": settings.llm_embedding_model,
            "temperature":     settings.llm_temperature,
            "seed":            settings.llm_seed,
        },
    )
    # ... agent loop runs; nested @observe'd functions auto-link spans ...

    langfuse_context.update_current_observation(
        output={"answer": final.answer},
        metadata={
            "iterations_used":      iterations_used,
            "iteration_limit_hit":  iteration_limit_hit,
            "input_tokens":         total_input,
            "output_tokens":        total_output,
            "cached_input_tokens":  cached,
            "cache_creation_input_tokens": cache_creation,
            "estimated_cost_usd":   cost,                   # G11 pricing module
            "refused":              final.refused,
            "refusal_category":     final.refusal_category,
            "output_safety_redacted": redacted,
            "stream_ttft_ms":       ttft,
            "history_truncated_turns": pruned,
        },
    )

    trace_url = langfuse_context.get_current_trace_url()
    log.info("agent.trace_created", langfuse_trace_url=trace_url)
```

### Resilience

Langfuse SDK calls are **async + batched** by default. If Langfuse is
down:

- SDK queues observations in-memory
- Flushes when reachable
- Failed flushes log `langfuse.flush_failed` to stdout (caught by Fly
  logs)
- **Agent continues serving requests normally** — observability failures
  never block the request critical path

Wrap any direct Langfuse SDK calls in try/except with stdout fallback
to preserve this invariant.

### Cost (Langfuse free tier)

- 50K observations/month free
- ~5-10 observations per chat turn (1 trace + ~3-7 spans)
- ⇒ 5,000-10,000 chat turns/month within free tier
- Demo expected: <500 turns total → comfortable margin
- Production scale: sample 1% of successful + 100% of errors (future
  work)

---

## Pricing Module + Cost Tracking (G11)

`backend/src/customs_agent/observability/pricing.py` is the single
source for per-model rate constants and the `estimate_cost()` helper.

```python
# backend/src/customs_agent/observability/pricing.py
"""Per-model token pricing in USD per 1M tokens.

VERIFY against current rates before relying on cost estimates:
- Anthropic: https://www.anthropic.com/pricing
- OpenAI:    https://openai.com/api/pricing/

Last verified: 2026-MM-DD  ← update this when constants change
"""
from typing import TypedDict


class ModelPricing(TypedDict):
    input_per_million:        float   # fresh input tokens
    cached_input_per_million: float   # cache-read (Anthropic ~10% of fresh)
    cache_write_per_million:  float   # cache-creation (Anthropic ~125% of fresh)
    output_per_million:       float


PRICING: dict[str, ModelPricing] = {
    "claude-sonnet-4-6": {
        # Verify against Anthropic's current pricing page before relying on
        # these numbers. Sonnet 4-6 vs 4-7 is in the same general tier.
        "input_per_million":        3.0,
        "cached_input_per_million": 0.30,
        "cache_write_per_million":  3.75,
        "output_per_million":       15.0,
    },
    "gpt-4o-mini": {                  # Fork 8 judge model
        "input_per_million":        0.15,
        "cached_input_per_million": 0.075,
        "cache_write_per_million":  0.15,
        "output_per_million":       0.60,
    },
    "text-embedding-3-small": {       # Fork 13 — build-time only
        "input_per_million":        0.02,
        "cached_input_per_million": 0.02,
        "cache_write_per_million":  0.02,
        "output_per_million":       0.0,
    },
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0                    # graceful unknown-model handling
    fresh_input = max(0, input_tokens - cached_input_tokens - cache_write_tokens)
    return round(
        fresh_input         * p["input_per_million"]        / 1_000_000
        + cached_input_tokens * p["cached_input_per_million"] / 1_000_000
        + cache_write_tokens  * p["cache_write_per_million"]  / 1_000_000
        + output_tokens       * p["output_per_million"]       / 1_000_000,
        6,
    )
```

### Update process

Manual, quarterly: bump the date comment in the docstring; update
constants; commit on `chore/update-pricing` branch. CI does not
auto-verify (would require live pricing API which providers don't
expose publicly). Documented as future work.

### Where it's called

Per Fork 52 + Fork 10, every Langfuse trace's metadata includes
`estimated_cost_usd` computed by this helper at the end of `run_agent`.
EVALUATION.md's run summary (G5) reports per-question + total cost
sourced from these values.

---

## Prompt Cache Effectiveness (Fork 55)

The Anthropic API response carries cache hit metrics:

- `response.usage.cache_creation_input_tokens` — tokens written to cache (first hit / cache miss)
- `response.usage.cache_read_input_tokens` — tokens served from cache (cache hits)

Captured per Langfuse `llm.call` span:

```python
usage = response.usage
langfuse_context.update_current_observation(metadata={
    "input_tokens":                getattr(usage, "input_tokens", 0),
    "output_tokens":               getattr(usage, "output_tokens", 0),
    "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
    "cache_read_input_tokens":     getattr(usage, "cache_read_input_tokens", 0),
})
```

### Filtering / aggregation in Langfuse

- "Show me all calls with `cache_read_input_tokens > 0`" → see all cache
  hits
- Aggregate `cache_read_input_tokens / (cache_read + cache_creation +
  fresh_input)` across a day → empirical hit rate

EVALUATION.md (G5) quotes the **actual** measured cache hit rate from
the latest eval run (e.g., "Cached input tokens 78%"), not the
theoretical maximum.

### Expected behavior

- **CI eval suite**: all 11 questions run in <2 min → cache stays hot
  from Q1's write through Q11. Expected hit rate: ~80-95% across the
  suite.
- **Reviewer evaluation**: question every 10-30s → cache stays hot
  within a session. Expected hit rate during an active session:
  ~70-90%.
- **Cold start** (after >5 min idle): first request misses cache, pays
  ~25% premium on cache-write tokens; next ~5 min hits.

### PROMPT_VERSION bumps rotate cache (intentional)

Bumping `PROMPT_VERSION` (Fork 27) changes the cached prefix bytes →
cache miss on the next request → cache writes a new prefix at ~25%
premium. Expected and intentional; signals a deliberate prompt change.

---

## Performance Budgets (G14)

Codified targets tracked via Langfuse latency metadata. **Not enforced
in CI** — measured and reported in EVALUATION.md + README.

| Metric | Target | Tracked via |
|---|---|---|
| First Contentful Paint (cold load) | < 1.5s | Manual / Lighthouse pass on Day 7 |
| Time to First Token (streaming) | < 2.0s p50 / < 3.5s p95 | Langfuse trace `metadata.stream_ttft_ms` |
| Tier 1 question end-to-end | < 3s p50 | Langfuse trace `metadata.total_latency_ms`, filtered by tier |
| Tier 3 question end-to-end | < 6s p50 | Same |
| Backend `/health` latency | < 100ms p99 | Fly metrics |
| Backend `/ready` latency | < 200ms p99 | Manual / CI smoke-test timing |
| Eval suite total runtime | < 3 minutes sequential | `eval.yml` workflow duration |

README's "Performance" section publishes these targets + the
measured-actual numbers from the latest EVALUATION.md run.

---

## PII & Retention Policy (Fork 53)

### Current demo posture

- **User messages** → Langfuse traces, 30-day retention (free-tier
  default)
- **IP addresses** → Fly stdout logs, ~5-day retention (platform
  default)
- **API keys** → logged as first-8-char prefix only anywhere they
  appear (Fork 48); full keys live in platform-native secret stores
  only (Fork 39)
- **System prompts** → **NOT** stored per-request; only
  `prompt_version` fingerprint logged. The prompt files themselves
  are in the repo at that version (Fork 27)
- **User-message previews** (80 chars) → appear in stdout logs
  **only** on `agent.refusal` events, for security forensics on
  prompt-injection attempts (Fork 49)
- **Backend stateless** (Fork 7) → no per-user data on the server;
  conversation history lives in browser `localStorage`
- The dataset is **synthetic** — no real customer PII anywhere in the
  system

### Retention by store

| Store | What's there | Retention | Configurable? |
|---|---|---|---|
| Fly stdout logs | Request lifecycle events (Fork 52), IPs, key prefixes, refusal previews | ~5 days (free tier) | Yes — Fly log drain to S3 with lifecycle rules (future work) |
| Langfuse Cloud | Full agent traces — user messages, retrieved chunks, tool inputs/outputs, LLM responses | 30 days (free tier) | Yes — paid plan or self-host |
| Frontend `localStorage` | Conversation history (Fork 7) | User-controlled (clear / quota / browser purge) | User-side |
| Backend memory | None persistent | Per-request only | N/A |
| GitHub Actions logs | CI eval results, secret-redacted | 90 days (GHA default) | Yes (org setting) |

### structlog secret-shape scrubber (defense-in-depth)

```python
# backend/src/customs_agent/observability/scrubber.py
import re

_SECRET_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    re.compile(r"\bpk-lf-[A-Za-z0-9_-]{10,}\b"),
]


def scrub_secrets(_, __, event_dict: dict) -> dict:
    """structlog processor: redact secret-shape strings from any field."""
    def scrub(val):
        if isinstance(val, str):
            for p in _SECRET_PATTERNS:
                val = p.sub("[REDACTED-SECRET]", val)
            return val
        if isinstance(val, dict):
            return {k: scrub(v) for k, v in val.items()}
        if isinstance(val, list):
            return [scrub(v) for v in val]
        return val
    return {k: scrub(v) for k, v in event_dict.items()}
```

If any code path ever logs a secret-shape string (e.g., an accidental
`print(api_key)` or a stack trace containing a header dump), this
processor redacts it before it hits stdout. Mirrors Fork 49 layer 5
output safety but on the logging side. ~10 lines; real protection
against future regressions.

### Production roadmap (per Fork 53)

| Control | Purpose |
|---|---|
| **Pseudonymized user messages** (rotating salt) | GDPR personal-data minimization |
| **Configurable per-region retention** (EU 30d, US 90d) | GDPR data residency |
| **Right-to-be-forgotten endpoint** | GDPR Art. 17 |
| **IP truncation** (last octet zeroed) | GDPR data minimization |
| **DPA with observability provider** | GDPR Art. 28 |
| **Consent / ephemeral mode toggle** | GDPR lawful basis; user trust |
| **Tamper-evident audit log** | SOC 2 CC7 |
| **CMK encryption at rest** | High-sensitivity tenants |
| **Compliance certifications** (SOC 2, GDPR DPA, HIPAA BAA) | Enterprise contract gates |
| **Log-shipping pipeline** (Fly stdout → S3 with lifecycle) | Long-term retention with explicit policy |
| **Data export endpoint** | GDPR Art. 15 right of access |

Consolidated in README's "Future work → Compliance" subsection (G26).

---

## Provider Cost Alerts (G19)

Manual pre-submission configuration:

1. Anthropic Console → Settings → Billing → Set monthly usage alert at **$20**
2. OpenAI dashboard → Billing → Usage limits → Set monthly soft limit at **$20**

Document in README's "Operations" section as a one-line note: *"Anthropic
and OpenAI dashboards are configured with $20/month soft alerts as a
runaway-cost safety net. Expected demo-window cost is ~$10-15 total."*

No programmatic alerting for the demo. Production future work
(per G19): PagerDuty / Slack webhook on provider billing thresholds;
programmatic budget tracking against the `estimated_cost_usd` aggregated
from Langfuse traces.

---

## OpenAI `system_fingerprint` Tracking (G24)

OpenAI exposes a `system_fingerprint` field on chat-completion responses
that uniquely identifies the model snapshot serving the request. When
OpenAI rotates the snapshot under a stable model name (e.g., `gpt-4o-mini`
rotates from snapshot A to B), the fingerprint changes — observable
drift signal.

Captured only for OpenAI judge calls (Fork 8 Q9 rubric):

```python
# backend/tests/eval/_grading.py
resp = openai_client.chat.completions.create(
    model=settings.llm_judge_model,
    temperature=0,
    seed=settings.llm_seed,
    messages=[...],
    response_format={"type": "json_object"},
)
fingerprint = getattr(resp, "system_fingerprint", None)
langfuse_context.update_current_observation(
    metadata={"judge_system_fingerprint": fingerprint})
```

Anthropic doesn't currently expose an equivalent field on Claude
responses, so for `claude-sonnet-4-6` calls we don't capture a
fingerprint — documented as future work in `04-agent-and-tools.md` (the
"dated model pin" pattern is the workaround if strict reproducibility
matters).

### Use case

If nightly eval (`eval.yml`) regresses unexpectedly, comparing
`judge_system_fingerprint` across runs answers "did OpenAI rotate the
judge snapshot?" in one query. The nightly drift-issue auto-open
(Fork 44) flags these regressions so they don't slip silently.

---

## Cookbook (for README)

Three reviewer-facing commands that surface in the README's
"Observability cookbook" section.

### Live tail Fly stdout

```bash
fly logs --app customs-agent-backend
```

### Filter to security events in last hour

```bash
fly logs --app customs-agent-backend --since 1h \
  | jq 'select(.event == "agent.refusal"
             or .event == "output_safety.redaction"
             or .event == "auth.invalid_key"
             or .event == "ratelimit.hit")'
```

### Find a specific request

```bash
fly logs --app customs-agent-backend --since 24h \
  | jq 'select(.request_id == "req_a3f1c4d2e5f6")'
```

### Langfuse filter recipes

Three useful UI filters worth documenting in the README:

| Filter | Question it answers |
|---|---|
| `metadata.refused = true` | "Did any requests get refused recently?" |
| `metadata.iteration_limit_hit = true` | "Are we hitting the agent budget?" |
| `metadata.cache_read_input_tokens > 0` | "What's our cache hit rate?" |
| `metadata.output_safety_redacted = true` | "Did the output safety scrubber fire?" |
| `metadata.history_truncated_turns > 0` | "Are long conversations hitting the token budget?" |

---

## Cost Sanity Check

With all the above, expected monthly cost for the demo:

| Item | Monthly cost (USD) |
|---|---|
| Fly machine (`shared-cpu-1x` 1GB always-on, `iad`) | ~$5.70 |
| Fly bandwidth | ~$0.10 |
| Langfuse Cloud (free tier) | $0 |
| Anthropic API (eval CI + reviewer demo) | ~$3-5 |
| OpenAI API (build-time embeddings + judge) | <$1 |
| Vercel (free tier) | $0 |
| GitHub Actions (free for public repos) | $0 |
| **Total demo cost** | **~$10-15/month** |

EVALUATION.md's "Run Metadata" header (G5) quotes the actual measured
cost from the most recent eval generation.

---

## Composition with Other Layers

- **`02-data-layer.md`** — boot-time validators emit
  `data.validation.complete` to stdout.
- **`03-rag-layer.md`** — every retrieval emits a Langfuse
  `rag.retrieve` span with chunk IDs and scores.
- **`04-agent-and-tools.md`** — the agent loop is wrapped in `@observe`;
  every tool, every LLM call, every output validation step gets a
  nested span; per-request metadata (tokens, cost, refused, etc.)
  computed at the end of `run_agent`.
- **`05-api-and-backend.md`** — `request_logging_middleware` is the
  outermost effective layer for stdout emission; `request.completed`
  surfaces `langfuse_trace_url` for log → trace pivot.
- **`06-frontend.md`** — frontend doesn't emit observability events
  (per Fork 7 stateless backend); client-side error capture via Sentry
  is future work (G20).
- **`07-infrastructure.md`** — `ENVIRONMENT=production` in `fly.toml`
  flips structlog to JSONRenderer; Langfuse credentials wired via Fly
  Secrets (Fork 39).
- **`08-cicd-and-testing.md`** — eval workflow generates Langfuse
  traces per question; trace URLs land in EVALUATION.md per question
  row (G5).
- **`09-security.md`** — every security control fires a structured
  event with the same `request_id` for forensic correlation.
- **`11-deliverables.md`** — README "Observability" section published
  alongside the cost-optimization narrative from Fork 55 + cache hit
  rate measurements.

---

## Future Work

| Item | Trigger |
|---|---|
| **Sampling strategy** (1% of successful + 100% of errors) | When Langfuse free tier becomes insufficient |
| **Self-host Langfuse** (Docker image) | Data residency / DPA control / unlimited observations |
| **Sentry integration** for client-side errors with breadcrumbs | When `<ErrorBoundary>` (G20) trips need server-side visibility |
| **OpenTelemetry collector** for vendor-neutral export | Multi-service / multi-provider observability |
| **Datadog / Honeycomb APM** for distributed traces | When there are multiple services to trace across |
| **Better Stack / Logflare** stdout aggregation with alerting | When pager-rules on `request.failed` rate spikes matter |
| **Live pricing-API integration** | When providers expose pricing APIs (none currently do) |
| **Programmatic cost alerts** (PagerDuty / Slack webhook) | Production scale |
| **Per-question cost dashboard** aggregated from Langfuse | When tuning prompt-cache hit rate becomes a regular activity |
| **Web Vitals reporting** via Vercel Speed Insights | Production performance monitoring |
| **Anthropic `system_fingerprint` equivalent** if Anthropic adds one | Whenever Anthropic exposes one |
| **Tamper-evident audit log** with signed log lines | SOC 2 CC7 audit-logging controls |
| **Pseudonymized user-message hashing** (Fork 53 production roadmap) | GDPR personal-data minimization |
| **Right-to-be-forgotten endpoint** | GDPR Art. 17 |
| **Fly log drain to S3 with lifecycle rules** | Longer retention than Fly's ~5 days |
