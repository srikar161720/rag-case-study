# PROGRESS.md

Phase checklist + session log for the Customs Analytics Agent build.

---

## Current Status

- **Phase**: Day 2 nearly complete — agent runtime layer shipped across 4 merged PRs (`feat/rag-pipeline` → `feat/prompts-and-tools` → `chore/copilot-review-cleanup` → `feat/agent-loop`). Remaining Day 2 work is the `test/backend-units` branch, slimmed to data-layer unit-test coverage (tools tests + agent-primitive tests already shipped alongside their source modules on prior branches).
- **Current branch**: `main` (clean; ready to start `test/backend-units`)
- **Last PR merged**: `feat/agent-loop` (preceded by `chore/copilot-review-cleanup`, `feat/prompts-and-tools`, `feat/rag-pipeline`)
- **Last session**: 2026-05-27 — Day 2 agent core (RAG + prompts + tools + agent loop, 4 branches)
- **Days elapsed / remaining**: 2 / 5
- **Blockers**: None. Next: `test/backend-units` for `tests/unit/data/{test_load,test_views,test_validation}.py`, then Day 3 begins with `feat/fastapi-backend`.

---

## Pre-Build Scaffolding (one-time)

- [x] `CLAUDE.md` created
- [x] `PROGRESS.md` created (this file)
- [x] `context/` directory + 12 context files created
- [x] Commit context-files scaffolding to `main` (one-off direct commit; all
      subsequent work goes through feature branches per CLAUDE.md workflow)

---

## Phase Checklist

Aligned with Fork 57's 7-day plan. Each subsection corresponds to one feature
branch (and therefore one PR). The branch list below maps 1:1 to the planned
~20 PRs across the build.

### Day 1 — Foundation

#### Branch: `chore/scaffold-monorepo`

- [x] Move `data/` → `backend/data/` and `knowledge/` → `backend/knowledge/`
- [x] Create `backend/` and `frontend/` subdirectory skeletons
- [x] `.github/workflows/` directory with placeholder files
- [x] Root `Makefile` with all targets per `context/07-infrastructure.md` (G6)
- [x] `scripts/setup.sh` interactive first-time setup
- [x] `.tool-versions` (Python 3.12, Node 20, pnpm 9) _(installed: Python 3.12 via uv-managed, Node 22.22.3, pnpm 11.1.3 — pinned to installed)_
- [x] `.gitattributes` for generated files
- [x] Update `.gitignore` per Fork 35
- [x] Initial `README.md` skeleton (full content lands Day 7)

#### Branch: `feat/data-layer`

- [x] `backend/pyproject.toml` + initial `uv.lock` with core deps (DuckDB, pydantic, fastapi) _(13 prod + 4 dev deps locked against Python 3.12; `tool.uv.required-environments` constrains resolution for macOS Intel wheel compatibility — onnxruntime locked to 1.23.2)_
- [x] `backend/src/customs_agent/data/load.py` — typed CAST schema with snake_case + derived columns (Fork 18)
- [x] `backend/src/customs_agent/data/views.py` — `entry_lines_v` + `entries_v` with capped MPF (Fork 19)
- [x] `backend/src/customs_agent/data/validation.py` — boot-time row count, enum drift, shell-entry log _(5 hard assertions: row count, distinct entries, Section 301 + IEEPA applicability via CODE columns, customer + country enum drift; 1 INFO log on shell count)_
- [x] `backend/src/customs_agent/config.py` — initial `AgentConfig`, `LLMConfig`, `RateLimitConfig`, `SafetyConfig` (skeleton) _(collapsed to a single flat `Settings(BaseSettings)` class with 21 env-bound fields across 7 logical sections; module-level singleton instantiation deferred to `feat/fastapi-backend`)_

#### Branch: `test/ground-truth`

- [x] `backend/tests/ground_truth.py` — all 11 canonical answers computed via SQL (Fork 43)
- [x] Generate `backend/tests/ground_truth.json` with dataset SHA-256 pin _(CSV SHA: `1d6df8e5710e4fe8d1b5ee43a9dc9ba08f82596148e49ec8407f3b0301bea98f`)_
- [x] Manually cross-check the 11 answers against a spreadsheet before committing _(verified via two independent code paths: DuckDB views and Python stdlib `csv.DictReader` — every numeric result agreed to the cent)_

### Day 2 — Agent Core

#### Branch: `feat/rag-pipeline`

- [x] **Env templates first** — `backend/.env.example` + `frontend/.env.example` env-var contracts (21 backend vars across 7 logical sections; frontend Next.js proxy pattern with synced `BACKEND_API_KEY`). `config.py` module docstring updated to point at the committed contract. `./scripts/setup.sh` ran cleanly (generated `backend/.env` with `openssl`-derived `BACKEND_API_KEY`; synced to `frontend/.env.local`). User edited `.env.example` to swap `LANGFUSE_HOST` to the US-region URL.
- [x] `backend/src/customs_agent/rag/chunker.py` — registry-driven chunker (Fork 14); `CHUNKS_REGISTRY` declares 39 chunks across 9 `section_kind` buckets; all 8 `EXPECTED_CITATIONS` chunk IDs (`rule_1_date_filtering` etc.) emitted verbatim.
- [x] `backend/scripts/build_index.py` — `make build-index` produces `chroma_db/` (ChromaDB persistent + OpenAI `text-embedding-3-small`) + `bm25.pkl` (pickled `BM25Okapi`) + `manifest.json` (embedding model + UTC timestamp + sorted chunk IDs + per-source-file SHA-256). Idempotent. Real index built end-to-end against OpenAI (~$0.0001 cost; 39 chunks in ~3s).
- [x] `backend/src/customs_agent/rag/retriever.py` — `HybridRetriever` with RRF (constant=60, top-K=5, candidate pool 10); shared `_tokenize.py` preserves dotted numeric sequences (`9903.88.15`) as single tokens. `from_artifacts()` reads disk; direct `__init__` accepts injected stubs for tests.
- [x] Unit tests for chunker + retriever in `backend/tests/unit/rag/` — 16 tests; mock ChromaDB + real BM25 (offline). Hard chunk-ID contract test enforces every ID in `tests/ground_truth.py:EXPECTED_CITATIONS`.

#### Branch: `feat/prompts-and-tools`

- [x] `backend/prompts/*.md` — 7 section files (`persona`, `scope`, `data_overview`, `knowledge_always_on`, `behavioral`, `tools_guidance`, `output_format`); `PROMPT_VERSION` 1.0.0 baseline; snapshot at `backend/tests/snapshots/system_prompt.md`.
- [x] `backend/src/customs_agent/agent/prompt.py` — `PROMPT_VERSION` + `SECTION_ORDER` + `@cache`'d `build_static_system_prompt()` + `STATIC_SYSTEM_PROMPT` module constant; HTML comment cache-boundary marker leads the assembled prompt.
- [x] `backend/src/customs_agent/rag/always_on.py` — `ALWAYS_ON_KINDS = frozenset({rule, quirk, metric})`; deterministic sort key `(section_kind, section_id, chunk_id)` so the cached prefix doesn't drift; renders 14 chunks (6 rules + 4 quirks + 4 metrics) to `prompts/knowledge_always_on.md`.
- [x] `backend/src/customs_agent/tools/_filters.py` — `CustomerCode` / `CountryCode` / `PortCode` Literal aliases; `EntryFilters` BaseModel with 9 fields, `include_shell: bool = False` default, date-range coherence + period-exclusivity validators, `extra="forbid"`.
- [x] `backend/src/customs_agent/tools/_shared.py` — `Citation` / `ToolMeta` / `ToolResult` Pydantic envelope (`citations=Field(default_factory=list)` per Copilot review); `build_where_clause` with `?` placeholders; `safe_execute` SELECT/WITH-only guardrail; `_count_shells_excluded` helper.
- [x] `backend/src/customs_agent/tools/_allowlists.py` — `ALLOWED_GROUP_BY` / `ALLOWED_AGGREGATIONS` / `ALLOWED_ORDER_BY` frozensets (Fork 50). Per-view column sets (`ENTRIES_V_COLUMNS`, `ENTRY_LINES_V_COLUMNS`, `_ONLY` differences) added on `feat/agent-loop` for the view-compat validator + drift test.
- [x] Specialized tools (Day 2 set): `effective_duty_rate.py` (Q5), `total_duty_breakdown.py` (Q4 + entry/line-grain auto-switch), `hold_summary.py` (Q6 + 5%/8% benchmarks).
- [x] Builder + lookup: `query_entries.py` (Q1/Q2/Q3/Q11; allowlist `field_validator`s; aggregation parser maps `sum(col)` → `col` alias; view-compat `model_validator` added on `feat/agent-loop`), `lookup_knowledge.py` (Q10; thin retriever wrapper, no synthesis). `tools/__init__.py` exports `TOOL_REGISTRY` + `build_anthropic_tool_def` + `format_query_entries_description`. Also: `data/validation.py` refactored to derive `EXPECTED_CUSTOMERS` / `EXPECTED_COUNTRIES` / `EXPECTED_PORTS` from the Literal aliases via `typing.get_args` (single source of truth).

#### Branch: `feat/agent-loop`

- [x] `backend/src/customs_agent/agent/loop.py` — sync `run_agent(ctx, user_message, history, request_id, settings=…)` per Fork 23 pseudocode. Steps: retrieve top-5 → dedup against always-on → prune history (G9) → tool-calling loop with prompt cache marker, dedup, iteration + budget guards → refusal detection → marker validation → sidecar assembly with shared citation/tool_call ID space (citations 1..N, tool_calls N+1..N+M). Six structlog events. Cost estimation passes `0.0` with a TODO pointing at `feat/langfuse-traces` (G11 pricing module).
- [x] `backend/src/customs_agent/agent/refusal.py` — 5-category routing (Fork 25); hidden-marker detection mechanism locked this session (`<!-- refusal:<category> -->` prefix). `REFUSAL_MARKER_RE` tolerates whitespace + case; unknown categories logged + treated as non-refusal. System-prompt rule appended to `prompts/scope.md`; `PROMPT_VERSION` bumped 1.0.0 → 1.1.0; snapshot refreshed.
- [x] `backend/src/customs_agent/agent/validator.py` — Fork 28 marker validator verbatim; orphan `[N]` markers stripped silently with structlog `agent.hallucinated_citation` warning naming invalid + valid ID sets. Structural `_HasId` Protocol keeps module decoupled from concrete `Citation` / `ToolCallTrace` types.
- [x] **`backend/src/customs_agent/agent/contracts.py`** — full set of 7 Pydantic wire types (`Message`, `ChatRequest`, `Citation`, `ToolCallTrace`, `Assumption`, `RefusalCategory` alias, `ResponseMeta`, `ChatResponse`); `extra="forbid"` everywhere; `Field(default_factory=list)` on every list. `backend/src/customs_agent/api/chat.py` ships as a 5-line re-export shim that honors the original PROGRESS.md `api/chat.py` checklist item without duplicating definitions (the agent loop's primary data model belongs alongside it; the FastAPI endpoint on `feat/fastapi-backend` will import via the shim).
- [x] `backend/src/customs_agent/tools/query_entries.py` — added `model_validator` on `QueryEntriesInput` rejecting view-incompatible `filters` / `group_by` / `aggregations` (PR #5 Copilot Comment 4 fix). Per-view column knowledge ships as hardcoded `ENTRIES_V_COLUMNS` / `ENTRY_LINES_V_COLUMNS` frozensets in `tools/_allowlists.py` + a drift-detection test (`test_allowlists.py`) that runs `DESCRIBE` against live in-memory DuckDB and fails on mismatch. Companion: `agent/bootstrap.py:build_tool_definitions()` substitutes the `{available_columns_*}` placeholders in the `query_entries` description at app startup via `information_schema.columns` (SELECT-friendly so `safe_execute` passes), closing the Fork 21 auto-generation deferral from `feat/prompts-and-tools`. Also created: `agent/bootstrap.py` (`AgentContext` frozen dataclass + `build_agent_context()` factory + `compute_always_on_chunk_ids()`), `agent/_dispatch.py` (per-tool wrappers binding `ctx.con` vs `ctx.retriever`), `agent/history.py` (G9 pruner with injectable `token_counter`).

#### Branch: `test/backend-units`

- [x] Unit tests for tools: per-file in `backend/tests/unit/tools/` _(already shipped on prior branches alongside source modules — `test_filters.py`, `test_shared.py`, `test_allowlists.py`, plus one test file per of the 5 tools)._
- [ ] Unit tests for data layer: `tests/unit/data/test_load.py`, `test_views.py`, `test_validation.py` _(the only remaining work for this branch)._
- [x] Unit tests for agent primitives: `test_refusal_classifier.py`, `test_marker_validator.py` _(shipped on `feat/agent-loop` as `tests/unit/agent/test_refusal.py` + `test_validator.py`, plus `test_history.py`, `test_contracts.py`, `test_bootstrap.py`, `test_dispatch.py`, `test_loop.py`)._

### Day 3 — Deploy + MVP

#### Branch: `feat/fastapi-backend`

- [ ] `backend/src/customs_agent/main.py` — FastAPI app with middleware stack
- [ ] `backend/src/customs_agent/api/auth.py` — `require_api_key` with `compare_digest` (Fork 48)
- [ ] `backend/src/customs_agent/api/_rate_limit.py` — slowapi composite `(key, IP)` bucket (Fork 47)
- [ ] `backend/src/customs_agent/api/_security_headers.py` — middleware (Fork 51)
- [ ] CORS allowlist via env var `ALLOWED_ORIGINS` (Fork 38)
- [ ] `backend/src/customs_agent/api/health.py` — `/health` + `/ready` with manifest (Fork 40)
- [ ] `backend/src/customs_agent/api/chat.py` — POST `/chat` non-streaming endpoint
- [ ] `backend/src/customs_agent/api/starter_prompts.py` — `/api/starter-prompts` endpoint (Fork 30 source)
- [ ] `backend/config/starter_prompts.py` — 6 chip definitions (also feeds Fork 25 refusal suggestions)

#### Branch: `chore/dockerfile-fly`

- [ ] `backend/Dockerfile` — multi-stage with `uv` + BuildKit secrets (Fork 41)
- [ ] `backend/.dockerignore`
- [ ] `backend/fly.toml` — `iad` region, shared-cpu-1x 1GB always-on, `/health` HTTP check (Forks 36, 37)
- [ ] First Fly deploy: `flyctl launch` + `fly secrets set` for all backend env vars
- [ ] Verify `/health` and `/ready` respond correctly on the deployed URL

#### Branch: `feat/web-mvp`

- [ ] `frontend/package.json` with `packageManager: "pnpm@9.x.x"` field + `engines.node >= 20`
- [ ] `frontend/vercel.json` — `regions: ["iad1"]`
- [ ] Next.js App Router scaffolding (`app/layout.tsx`, `app/page.tsx`, `app/globals.css`)
- [ ] Tailwind + shadcn/ui installation
- [ ] `frontend/src/lib/api.ts` — API client with structured error handling
- [ ] `frontend/src/lib/storage.ts` — localStorage Phase 1 (single active conversation, Fork 7)
- [ ] `frontend/src/lib/types.ts` — hand-written placeholder types (replaced in Day 4 by G3 codegen)
- [ ] `frontend/src/app/api/chat/route.ts` — Next.js server-side proxy injecting `X-API-Key` (Fork 29 non-streaming variant)
- [ ] Minimal `<Chat>` component: chat bubbles, input, "+ New chat" button (Fork 33 Phase 1)

#### Branch: `chore/ci-cd`

- [ ] `.github/workflows/ci.yml` — backend (lint + typecheck + unit + integration), frontend (lint + typecheck + build), secret-scan (gitleaks)
- [ ] `.github/workflows/deploy.yml` — Fly deploy on push to `main` + `/ready` smoke test
- [ ] Vercel project linked to GitHub repo: Root Directory = `frontend`, auto-preview on PR
- [ ] GitHub Secrets configured: `FLY_API_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`
- [ ] Branch protection on `main` (if repo is public): require PRs, require status checks, linear history, rebase-merge only
- [ ] Configure rebase-merge as the only allowed merge strategy in repo settings

### Day 4 — Accuracy Hardening

#### Branch: `feat/remaining-tools-and-eval`

- [ ] Specialized tools (Day 4 set): `top_hts_by_duty.py`, `qbr_summary.py`, `compare_customers.py` (Fork 22)
- [ ] `backend/tests/eval/_grading.py` — tier-hybrid grading with Q9 LLM-as-judge (Fork 46)
- [ ] `backend/tests/integration/stub_llm.py` + agent-loop integration tests (Fork 45 Layer 2)
- [ ] `.github/workflows/eval.yml` — path-triggered + nightly + manual + label-based; content-hash cache; nightly drift-issue auto-open (Fork 44)
- [ ] `backend/tests/eval/test_questions.py` parametrized over `ground_truth.json`
- [ ] `backend/tests/eval/test_out_of_scope.py` — 5 refusal robustness cases (Fork 25)
- [ ] `backend/scripts/generate_evaluation_md.py` — EVALUATION.md generator with full header (G5)
- [ ] `evaluation-freshness` advisory CI check (PROMPT_VERSION drift warning, non-blocking)

#### Branch: `feat/observability-base`

- [ ] `backend/src/customs_agent/observability/logging.py` — structlog with dev/prod renderer split (Fork 54)
- [ ] `backend/src/customs_agent/observability/scrubber.py` — secret-shape redaction processor (Fork 53)
- [ ] Request-logging middleware: `request_id` UUID, `api_key_prefix` (8 chars), length-only message metadata (Forks 48, 52)
- [ ] Event taxonomy constants: `request.received/completed/failed`, `agent.refusal`, `ratelimit.hit`, `auth.invalid_key`, `output_safety.redaction`, `sql_safety.invalid_column_name`, `cors.preflight_rejected`, `agent.iteration_limit`, `agent.duplicate_tool_call`

#### Branch: `feat/api-contract`

- [ ] `backend/scripts/export_openapi.py` — dump FastAPI OpenAPI to `openapi.json` (G3)
- [ ] `openapi.json` committed at repo root
- [ ] Frontend `openapi-typescript` installed; `pnpm gen:types` script wired
- [ ] `frontend/src/lib/api-types.ts` generated and committed
- [ ] `frontend/src/lib/types.ts` refactored to re-export from `api-types.ts`
- [ ] `.github/workflows/ci.yml` — `api-contract` job: regenerate both files in CI, diff against committed versions, fail on drift

### Day 5 — Bonuses

#### Branch: `feat/langfuse-traces`

- [ ] `backend/src/customs_agent/observability/langfuse.py` — SDK init + `@observe` decorators on agent loop (Fork 10)
- [ ] Span hierarchy: `rag.retrieve`, `llm.call`, `tool.*`, `output.validation` (Fork 52)
- [ ] Trace metadata: `prompt_version`, `model`, `temperature`, `seed`, tokens (input/output/cached), cost via G11 pricing module
- [ ] `backend/src/customs_agent/observability/pricing.py` — TypedDict + `estimate_cost()` helper (G11)
- [ ] OpenAI `system_fingerprint` capture on judge calls (G24)
- [ ] `request.completed` stdout log line carries `langfuse_trace_url` for pivot

#### Branch: `feat/citations-panel`

- [ ] `frontend/src/components/CitationMarker.tsx` — color-coded pill (blue=knowledge, green=computation), hover preview, click-to-jump (Fork 32)
- [ ] `frontend/src/components/AgentPanel.tsx` — collapsible "Sources & Computation" disclosure with 3 sections + Run Info (Fork 31)
- [ ] `react-markdown` plugin transforming `[N]` → `<CitationMarker>` in prose
- [ ] Streaming-compatible item appearance (placeholder until Day 6 SSE)

#### Branch: `feat/empty-state-chips`

- [ ] `frontend/src/components/EmptyState.tsx` — 6 chips covering all 4 tiers + meta (Fork 30)
- [ ] Chip click → populate input + auto-submit; chips hide after first user message
- [ ] **🚨 User action needed**: place `frontend/public/favicon.ico` + `frontend/public/og-image.png` (1200×630) — Claude will prompt at chunk completion (G22)
- [ ] `app/layout.tsx` — `metadata` export with title, description, OG image, favicon (G22)

#### Branch: `feat/security-hardening`

- [ ] `backend/src/customs_agent/agent/output_safety.py` — regex-based prohibited-pattern scrubber with full-response redaction on match (Fork 49)
- [ ] Wire `output_safety` into agent loop final step
- [ ] Integration tests: prompt injection refusal, system-prompt extraction attempt, length-bomb 422, invalid column name rejection, invalid customer code rejection (Forks 49, 50)
- [ ] Verify all 8 security controls function correctly on the deployed backend

#### Branch: `feat/error-boundary`

- [ ] `frontend/src/components/ErrorBoundary.tsx` wrapping `<Chat>` in `app/layout.tsx` (G20)
- [ ] `frontend/src/lib/errors.ts` — unified `ApiError` + error-to-toast mapping per G10 table
- [ ] `frontend/src/components/ErrorToast.tsx` using shadcn/ui `<Toast>`
- [ ] Auth failure UX, rate limit `retry_after` countdown, network error retry button (G10)

### Day 6 — Streaming + Extras

#### Branch: `feat/streaming`

- [ ] **Phase 1**: SSE backend endpoint `POST /chat/stream` emitting `event: token` (Fork 29)
- [ ] **Phase 1**: Next.js SSE proxy at `app/api/chat/stream/route.ts` (server-side, injects API key)
- [ ] **Phase 1**: Frontend SSE consumer in `lib/sse.ts`
- [ ] **Phase 2**: Backend emits `knowledge_retrieved`, `tool_call_started`, `tool_call_completed` events
- [ ] **Phase 2**: Frontend progressive panel population during stream (Fork 31 components)
- [ ] TTFT metric captured in Langfuse trace metadata (`stream.ttft_ms`)

#### Branch: `feat/conversation-sidebar`

- [ ] Phase 2 localStorage: list of conversations, auto-prune at 50 (Fork 33)
- [ ] `frontend/src/components/ConversationSidebar.tsx` — collapsible on desktop, slide-over on mobile via shadcn `<Sheet>`
- [ ] Auto-titled from first user message (40-char truncation)
- [ ] Conversation switching via sidebar click → restore from localStorage

#### Branch: `feat/frontend-tests`

- [ ] Vitest + `@vitejs/plugin-react` + jsdom + coverage-v8 installed (G2)
- [ ] `frontend/vitest.config.ts`
- [ ] `frontend/src/lib/sse.test.ts` — SSE parser cases (~7 tests)
- [ ] `frontend/src/lib/storage.test.ts` — localStorage helpers (~6 tests)
- [ ] `frontend/src/lib/citations.test.ts` — marker resolution (~5 tests)
- [ ] `frontend/src/lib/api.test.ts` — API client (~3 tests)
- [ ] `pnpm test --run` step added to `ci.yml` frontend job

#### Branch: `chore/mobile-responsive`

- [ ] 30-min responsive pass: chip grid `grid-cols-1 sm:grid-cols-2`, panel `overflow-x-auto` for tables/SQL, sidebar mobile sheet
- [ ] iOS Safari: `100dvh`, `pb-[env(safe-area-inset-bottom)]` on input container
- [ ] `<MessageBubble>` PROMPT_VERSION drift badge (G25)
- [ ] Test on iPhone SE + iPhone 14 emulation in Chrome DevTools

### Day 7 — Documentation + Final Polish

#### Branch: `docs/final-polish`

- [ ] README "Architecture" section: Mermaid diagram + design decisions narrative (deliverable per CASE_STUDY.md)
- [ ] README "How the knowledge layer works" section: embedding strategy + retrieval approach + prompt design (deliverable)
- [ ] README "Infrastructure decisions" section: why Vercel/Fly.io + how CI/CD works (deliverable) + **Azure equivalent mapping** (recruiter topic) + **G17** manual rollback commands
- [ ] README "Security considerations" section: threat model + 8-control table + future-work (deliverable)
- [ ] README "Observability cookbook": `fly logs | jq` queries + Langfuse filter recipes
- [ ] README "Cost optimization" section: measured cache hit rate + per-Q cost from latest eval run (bonus item)
- [ ] README "Performance budgets" table (G14)
- [ ] README "Browser support" statement (G15) + "Known limitations" section (G23 + others)
- [ ] README "How we'd ship this on the team" subsection (Graphite recruiter topic)
- [ ] README "Future Work" section grouped by 10 categories (G26)
- [ ] `backend/README.md` — quickstart, troubleshooting (manual rollback per G17), local dev parity paragraphs (G18)
- [ ] `frontend/README.md` — quickstart, package manager note (G13), Makefile pointer
- [ ] Anthropic + OpenAI dashboard cost alerts configured at $20 monthly cap (G19)
- [ ] `EVALUATION.md` final regeneration via `make eval-md` against deployed backend
- [ ] EVALUATION.md self-assessment paragraphs filled in for any rubric warnings
- [ ] Manual end-to-end smoke test: all 11 questions on deployed demo URL from fresh incognito browser
- [ ] Final commit cleanup

### Pre-Submission Checks

- [ ] All 11 graded questions pass (correctness axis) per latest EVALUATION.md
- [ ] CI green on `main` (all jobs)
- [ ] Deployed demo URL functional end-to-end from a fresh incognito browser
- [ ] README includes architecture diagram + all required deliverable sections
- [ ] `EVALUATION.md` regenerated within 24 hours of submission (trace-link freshness window per Fork 53)
- [ ] Anthropic + OpenAI dashboard cost alerts configured (G19)
- [ ] All secrets confirmed in Fly Secrets, Vercel Env, GitHub Secrets
- [ ] Repo set to public OR invite-only with reviewer access granted
- [ ] Recruiter-topic documentation present (Azure mapping + Graphite mention)
- [ ] Submission email/form completed with repo URL + demo URL

---

## Session Log

> **Logging guidance**: keep entries **concise and informative** — one to
> three short paragraphs is typically enough. Verbose entries are justified
> **only** when something significant happened that future sessions need to
> remember (a major design decision shift, an unexpected blocker, a
> dependency surprise, a scope change). Routine progress can be summarized
> in 4–6 lines. This keeps `PROGRESS.md` from bloating session-start context
> as the project grows.
>
> **Entry order**: newest at the top (right below this template), older
> entries below.

### Template

```markdown
### YYYY-MM-DD — <Session goal (3-5 words)>

- **Branch(es) touched**: `<branch-name>`, `<branch-name>`
- **PRs**: opened #N, merged #M
- **Progress**: <1–3 short lines summarizing what was completed against the checklist>
- **Decisions / surprises**: <only if non-routine — design changes, scope shifts, blockers, dep surprises>
- **Next session**: <1 line — next branch or checklist item to start>
```

---

### 2026-05-27 — Day 2 agent core (4 branches shipped)

- **Branch(es) touched**: `feat/rag-pipeline`, `feat/prompts-and-tools`, `chore/copilot-review-cleanup`, `feat/agent-loop`, `main` (admin).
- **PRs**: merged 4 (`feat/rag-pipeline`, `feat/prompts-and-tools`, `chore/copilot-review-cleanup`, `feat/agent-loop`); 1 admin commit to `main` (one-line `PROGRESS.md` edit adding the PR #5 Copilot Comment 4 deferral to `feat/agent-loop`'s checklist).
- **Progress**: 18 commits, 249 unit tests passing in ~3s. RAG pipeline (39 chunks, hybrid retriever with RRF, real index built end-to-end via `make build-index`); 7-file system prompt + 5 typed tools (`effective_duty_rate`, `total_duty_breakdown`, `hold_summary`, `query_entries`, `lookup_knowledge`) with `TOOL_REGISTRY` + Anthropic spec builder; agent runtime (`agent/loop.py` orchestrator + `bootstrap.py` `AgentContext` + `_dispatch.py` per-tool wrappers + `validator.py` marker stripping + `refusal.py` detection + `history.py` G9 pruning + `contracts.py` 7 Pydantic wire types). All 4 branches landed `make lint-backend` + `make typecheck-backend` clean.
- **Decisions / surprises**:
  - **Refusal detection mechanism (Fork 25 spec gap)** — chose hidden marker prefix `<!-- refusal:<category> -->` over heuristic prose matching, a separate classifier LLM call, or a stub. Deterministic, cheap, tolerant of LLM phrasing drift (regex allows leading whitespace, internal whitespace, case-insensitive `Refusal`). Authored as a `prompts/scope.md` rule so the LLM is taught to emit it; matched by `agent/refusal.py:detect_refusal()`. Bumped `PROMPT_VERSION` to `1.1.0` to rotate the prompt cache deliberately. Unknown categories logged at WARNING + treated as non-refusal so we never silently fabricate a category. Captured in CLAUDE.md Critical Gotcha #12 and `context/04-agent-and-tools.md` §"Refusal detection mechanism".
  - **Pydantic contracts placement (spec ↔ PROGRESS.md conflict)** — spec said `agent/contracts.py`, PROGRESS.md said `api/chat.py`. Resolved by putting all 7 types in `agent/contracts.py` with `api/chat.py` as a 5-line re-export shim. The agent loop's primary data model belongs alongside it; the FastAPI endpoint can import via either path. PROGRESS.md `feat/agent-loop` checklist updated this session.
  - **`query_entries` column auto-generation closed** — Fork 21's "auto-generated column list at boot" deferral from `feat/prompts-and-tools` shipped on `feat/agent-loop` via `agent/bootstrap.py:build_tool_definitions()`. Uses `information_schema.columns` rather than `DESCRIBE` (DuckDB rejects CTE-wrapped `DESCRIBE`, and `DESCRIBE` doesn't pass the SELECT-only `safe_execute` guard). Captured in CLAUDE.md Critical Gotcha #13 and `context/04-agent-and-tools.md` §"Schema fingerprint".
  - **View-compatibility validator (PR #5 Copilot Comment 4 fix)** — chose hardcoded `ENTRIES_V_COLUMNS` / `ENTRY_LINES_V_COLUMNS` frozensets in `_allowlists.py` + drift-detection test over boot-time `DESCRIBE` registration. Stateless validator, test-friendly, no module-level mutable state. Drift test runs `DESCRIBE` on live in-memory DuckDB and fails when constants diverge from `views.py`. Captured in `context/04-agent-and-tools.md` §"View-compatibility validator" and `context/09-security.md` Control 7 (now four structural protections, not three).
  - **PR #5 Copilot review** — addressed 4 of 5 comments on `chore/copilot-review-cleanup` (one logical-chunk commit, ~4 files, 3 regression tests). Comment 1: `ToolResult.citations` → `Field(default_factory=list)`. Comment 2: removed unused `_FIELD_TO_COLUMN` dict. Comment 3: fixed `build_where_clause` docstring contradiction. Comment 5: removed dead `if row is None:` branches. Comment 4 deferred to `feat/agent-loop` and shipped there.
  - **`test/backend-units` scope shrinkage** — three of the four original bullets (tools tests + agent-primitive tests) already shipped on prior branches alongside their source modules (this project's per-branch testing discipline). Remaining scope is the data-layer suite (`tests/unit/data/test_{load,views,validation}.py`). Checklist updated this session to reflect.
  - **CLAUDE.md Critical Gotchas updated this session**: #8 strengthened (snapshot test enforces `PROMPT_VERSION` bumps); #10 strengthened (view-compat `model_validator` complements the existing column allowlists + SELECT-only guard); new #12 (refusal marker mechanism); new #13 (`query_entries` description placeholders filled at boot via `bootstrap.py`).
  - **Workflow note** — `chore/copilot-review-cleanup` introduced a new commit-rewriting pattern. User combined commits 2 + 3 into one commit by accident on `feat/prompts-and-tools`; resolved cleanly via `git reset --mixed HEAD~1` before push (commit was local-only). Documented the safe local-reset path for future similar slips.
- **Next session**: `test/backend-units` for the data-layer unit tests (`tests/unit/data/test_load.py`, `test_views.py`, `test_validation.py`). After that, Day 3 begins with `feat/fastapi-backend`.

---

### 2026-05-20 — Day 1 complete (scaffold + data layer + ground truth)

- **Branch(es) touched**: `chore/scaffold-monorepo`, `feat/data-layer`, `test/ground-truth`
- **PRs**: merged: 2 (`chore/scaffold-monorepo`, `feat/data-layer`); committed locally, push pending: `test/ground-truth`
- **Progress**: All 17 Day-1 checklist items complete across 7 commits. Monorepo scaffolding (skeleton dirs, root `Makefile` with 25 self-documenting targets, idempotent `scripts/setup.sh`, CI workflow placeholders, README skeleton, comprehensive `.gitignore` + `.gitattributes`). Typed DuckDB data layer (`pyproject.toml` + `uv.lock` with 13 prod + 4 dev deps locked against Python 3.12; flat `Settings(BaseSettings)` skeleton; `load.py` + `views.py` + `validation.py` with MPF cap and 5 hard boot-time assertions). SHA-pinned ground-truth fixture for the 11 case-study answers (verified through two independent code paths).
- **Decisions / surprises**:
  - **`onnxruntime` macOS Intel wheel drop** — onnxruntime 1.26 (chromadb transitive dep) has no `darwin/x86_64` wheel; resolved via `tool.uv.required-environments` in `pyproject.toml` constraining resolution to both linux/amd64 (prod Docker target) and darwin/x86_64 (dev machine), locking onnxruntime to 1.23.2 which has wheels for both.
  - **Settings class shape** — PROGRESS.md's plural `AgentConfig` / `LLMConfig` / `RateLimitConfig` / `SafetyConfig` names collapsed to a single flat `Settings(BaseSettings)` class per the locked spec in `context/05-api-and-backend.md`; the plural names describe logical sections inside Settings, not separate classes.
  - **Spec drift discovered** — `section_301_duty` and `ieepa_duty` are `0.00` (not `NULL`) on non-applicable lines in the actual CSV; only the corresponding CODE columns are `NULL`, and those are the authoritative applicability signal. Updated 6 prose locations across `CLAUDE.md` Critical Gotchas 2 + 3 and `context/02-data-layer.md`. Validation rules now check the code columns. The `COALESCE(SUM(...), 0)` views pattern remains as defensive coding.
  - **New workflow rules added to CLAUDE.md this session**:
    1. No build-phase / "Day N" references in commits or PRs (Commit Message Format section).
    2. No build status / progress lines in `README.md` — tracking lives in CLAUDE.md + PROGRESS.md only (new Documentation hygiene subsection).
    3. Pause on data-shape or spec-drift discoveries — present options to the user before unilaterally picking a fix (When in Doubt section).
    4. New Critical Gotcha 11 — `structlog` is intentionally unconfigured pre-`feat/observability-base`; the data layer's INFO log uses the library default until that branch lands.
  - **Hold rate** — dataset has 236 on-hold entries (19.67% hold rate; status `warrants_investigation` per the >8% threshold), correcting an earlier sampling-based scan that reported 0. Ground-truth Q6 captures this.
- **Next session**: Begin Day 2 — branch `feat/rag-pipeline`. Requires `OPENAI_API_KEY` (shell export for now until `backend/.env.example` lands on `feat/fastapi-backend`).

---

### 2026-05-18 — Plan lock-in + context-file scaffolding

- **Branch(es) touched**: `main`
- **PRs**: none (one-off scaffolding commit directly to `main`; all subsequent work goes through feature branches)
- **Progress**: Locked all 58 architectural decision forks plus 26 gap-scrutiny G-items. Scaffolded `CLAUDE.md`, `PROGRESS.md`, and 12 `context/` files documenting the full plan. Confirmed `claude-sonnet-4-6` as the main agent model.
- **Decisions / surprises**: Recruiter signaled awareness expectations for Azure Container App Jobs and Graphite — flagged as Day-7 README documentation, no plan or code change. G16 (custom domain) and G21 (overall a11y audit) explicitly skipped as out-of-scope.
- **Next session**: Begin Day 1 — branch `chore/scaffold-monorepo` to create `backend/` + `frontend/` directories, move `data/` and `knowledge/` into `backend/`, scaffold the root `Makefile`, `scripts/setup.sh`, and `.tool-versions`.
