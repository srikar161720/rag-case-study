# PROGRESS.md

Phase checklist + session log for the Customs Analytics Agent build.

---

## Current Status

- **Phase**: Pre-build (planning locked, scaffolding pending)
- **Current branch**: `main`
- **Last PR merged**: — (none yet)
- **Last session**: 2026-05-18 — Plan lock-in + context-file scaffolding
- **Days elapsed / remaining**: 0 / 7
- **Blockers**: None

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
- [ ] Create `backend/` and `frontend/` subdirectory skeletons
- [ ] `.github/workflows/` directory with placeholder files
- [ ] Root `Makefile` with all targets per `context/07-infrastructure.md` (G6)
- [ ] `scripts/setup.sh` interactive first-time setup
- [ ] `.tool-versions` (Python 3.12, Node 20, pnpm 9)
- [ ] `.gitattributes` for generated files
- [ ] Update `.gitignore` per Fork 35
- [ ] Initial `README.md` skeleton (full content lands Day 7)

#### Branch: `feat/data-layer`

- [ ] `backend/pyproject.toml` + initial `uv.lock` with core deps (DuckDB, pydantic, fastapi)
- [ ] `backend/src/customs_agent/data/load.py` — typed CAST schema with snake_case + derived columns (Fork 18)
- [ ] `backend/src/customs_agent/data/views.py` — `entry_lines_v` + `entries_v` with capped MPF (Fork 19)
- [ ] `backend/src/customs_agent/data/validation.py` — boot-time row count, enum drift, shell-entry log
- [ ] `backend/src/customs_agent/config.py` — initial `AgentConfig`, `LLMConfig`, `RateLimitConfig`, `SafetyConfig` (skeleton)

#### Branch: `test/ground-truth`

- [ ] `backend/tests/ground_truth.py` — all 11 canonical answers computed via SQL (Fork 43)
- [ ] Generate `backend/tests/ground_truth.json` with dataset SHA-256 pin
- [ ] Manually cross-check the 11 answers against a spreadsheet before committing

### Day 2 — Agent Core

#### Branch: `feat/rag-pipeline`

- [ ] `backend/src/customs_agent/rag/chunker.py` — section-header chunking with `section_kind` metadata (Fork 14)
- [ ] `backend/scripts/build_index.py` — OpenAI embeddings → ChromaDB + `bm25.pkl` + `manifest.json` (Fork 17)
- [ ] `backend/src/customs_agent/rag/retriever.py` — hybrid BM25 + semantic with RRF, top-K=5 (Fork 16)
- [ ] Unit tests for chunker + retriever in `backend/tests/unit/rag/`

#### Branch: `feat/prompts-and-tools`

- [ ] `backend/prompts/*.md` — 7 section files: persona, scope, data_overview, knowledge_always_on, behavioral, tools_guidance, output_format (Fork 27)
- [ ] `backend/src/customs_agent/agent/prompt.py` — templated system prompt + `PROMPT_VERSION` constant + cache boundary marker
- [ ] `backend/src/customs_agent/rag/always_on.py` — assembles always-on knowledge block from chunks (Fork 15)
- [ ] `backend/src/customs_agent/tools/_filters.py` — `EntryFilters` Pydantic with `Literal` enums (Fork 21)
- [ ] `backend/src/customs_agent/tools/_shared.py` — `build_where_clause` (parameterized) + `safe_execute` SELECT-only guardrail + `ToolResult` envelope
- [ ] `backend/src/customs_agent/tools/_allowlists.py` — `ALLOWED_GROUP_BY`, `ALLOWED_AGGREGATIONS`, `ALLOWED_ORDER_BY` for `query_entries` (Fork 50)
- [ ] Specialized tools (Day 2 set): `effective_duty_rate.py`, `total_duty_breakdown.py`, `hold_summary.py` (Fork 22)
- [ ] Builder + lookup: `query_entries.py`, `lookup_knowledge.py`

#### Branch: `feat/agent-loop`

- [ ] `backend/src/customs_agent/agent/loop.py` — tool-calling loop, MAX_ITERATIONS=5, dedup, token-budget guard, graceful degradation (Fork 23)
- [ ] `backend/src/customs_agent/agent/refusal.py` — 5-category refusal routing (Fork 25)
- [ ] `backend/src/customs_agent/agent/validator.py` — citation marker validation (strip orphans) (Fork 28)
- [ ] `backend/src/customs_agent/api/chat.py` — `ChatRequest` / `ChatResponse` Pydantic models (Fork 28)

#### Branch: `test/backend-units`

- [ ] Unit tests for tools: per-file in `backend/tests/unit/tools/`
- [ ] Unit tests for data layer: `tests/unit/data/test_load.py`, `test_views.py`, `test_validation.py`
- [ ] Unit tests for agent primitives: `test_refusal_classifier.py`, `test_marker_validator.py`

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

### 2026-05-18 — Plan lock-in + context-file scaffolding

- **Branch(es) touched**: `main`
- **PRs**: none (one-off scaffolding commit directly to `main`; all subsequent work goes through feature branches)
- **Progress**: Locked all 58 architectural decision forks plus 26 gap-scrutiny G-items. Scaffolded `CLAUDE.md`, `PROGRESS.md`, and 12 `context/` files documenting the full plan. Confirmed `claude-sonnet-4-6` as the main agent model.
- **Decisions / surprises**: Recruiter signaled awareness expectations for Azure Container App Jobs and Graphite — flagged as Day-7 README documentation, no plan or code change. G16 (custom domain) and G21 (overall a11y audit) explicitly skipped as out-of-scope.
- **Next session**: Begin Day 1 — branch `chore/scaffold-monorepo` to create `backend/` + `frontend/` directories, move `data/` and `knowledge/` into `backend/`, scaffold the root `Makefile`, `scripts/setup.sh`, and `.tool-versions`.
