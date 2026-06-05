# PROGRESS.md

Phase checklist + session log for the Customs Analytics Agent build.

---

## Current Status

- **Phase**: **Day 3 fully complete — the demo is live and end-to-end.** All four Day-3 branches shipped this session (`chore/dockerfile-fly`, `feat/web-mvp`, `chore/ci-cd`) plus the previously-merged `feat/fastapi-backend`. Backend containerized + deployed to Fly (`https://customs-agent-backend.fly.dev`); Next.js frontend deployed to Vercel (publicly reachable); CI + automated deploy-on-merge live. Backend test suite steady at **356 tests** (hermetic; CI builds the RAG index before the integration suite).
- **Current branch**: `main` (clean; admin sweep in progress)
- **Last PR merged**: `fix/deploy-dockerfile-path` (the 2nd post-merge deploy hotfix) — preceded this session by `chore/dockerfile-fly`, `feat/web-mvp` (PR #11), `chore/ci-cd` (PR #12), and `fix/deploy-flyctl-tag`.
- **Last session**: 2026-06-02 — Day 3 close: containerize + Fly deploy + web MVP + CI/CD + live demo (4 feature branches + 2 deploy hotfixes + 2 rounds of Copilot review fixes)
- **Days elapsed / remaining**: 3 / 4
- **Blockers**: None. **Live demo URLs**: backend `https://customs-agent-backend.fly.dev` (`/health`, `/ready`, `/docs`); frontend on Vercel (Deployment Protection disabled so the demo link is public). Next: Day 4 — `feat/remaining-tools-and-eval` (3 more tools + eval suite + `eval.yml` + EVALUATION.md generator), `feat/observability-base` (structured logging), `feat/api-contract` (OpenAPI snapshot + frontend codegen + the deferred `api-contract` CI job).

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
- [x] Unit tests for data layer: `tests/unit/data/test_load.py` (12) + `test_views.py` (15) + `test_validation.py` (14) _(shipped on `test/backend-units` PR #8 as one chunk commit — 41 tests total. Two-fixture conftest pattern: session-scoped `duckdb_con` for read-only tests, function-scoped `fresh_duckdb_con` for mutation-bearing drift tests. Validator drift tests use `pytest.raises(AssertionError, match=…)` anchored on specific error strings so each assertion's grammar is pinned. MPF floor cap exercised via synthetic INSERT since the real dataset has zero entries below $31.67. Backend suite grew 249 → 290.)_
- [x] Unit tests for agent primitives: `test_refusal_classifier.py`, `test_marker_validator.py` _(shipped on `feat/agent-loop` as `tests/unit/agent/test_refusal.py` + `test_validator.py`, plus `test_history.py`, `test_contracts.py`, `test_bootstrap.py`, `test_dispatch.py`, `test_loop.py`)._

### Day 3 — Deploy + MVP

#### Branch: `feat/fastapi-backend`

- [x] `backend/src/customs_agent/main.py` — FastAPI app + lifespan (data → views → validate → retriever → AgentContext → loop_settings) + middleware stack
- [x] `backend/src/customs_agent/api/auth.py` — `require_api_key` with `compare_digest` (Fork 48); UTF-8 bytes encoding fix for non-ASCII headers landed in the Copilot-review chunk
- [x] `backend/src/customs_agent/api/_rate_limit.py` — slowapi composite `(key[:8], IP)` bucket (Fork 47); custom 429 handler emitting structured JSON + `Retry-After` header
- [x] `backend/src/customs_agent/api/_security_headers.py` — middleware (Fork 51); applies 4 defensive headers on every response including 4xx/5xx + 429 + CORS preflight (the latter two via the middleware-order fix on the Copilot-review chunk)
- [x] CORS allowlist via env var `ALLOWED_ORIGINS` (Fork 38)
- [x] `backend/src/customs_agent/api/health.py` — `/health` + `/ready` with manifest (Fork 40); manifest read wrapped in try/except + BM25 None flips overall_ok on the Copilot-review chunk
- [x] `backend/src/customs_agent/api/chat.py` — POST `/chat` non-streaming endpoint; forwards `app.state.loop_settings` as `settings=` kwarg to `run_agent` on the Copilot-review chunk
- [x] `backend/src/customs_agent/api/starter_prompts.py` — `/api/starter-prompts` endpoint (Fork 30 source)
- [x] `backend/src/customs_agent/config/starter_prompts.py` — 6 chip definitions (also feeds Fork 25 refusal suggestions) _(original PROGRESS.md path `backend/config/starter_prompts.py` was a typo — actual landing path is inside the `customs_agent.config` package per the spec import at `context/05-api-and-backend.md:354`, with `config.py` → `config/` package conversion as part of chunk 2)_
- [x] **Drive-by additions (not on original checklist)**: `backend/src/customs_agent/api/_request_id.py` (interim middleware setting `request.state.request_id = str(uuid.uuid4())` — full structured-logging middleware lands on `feat/observability-base`); `backend/tests/conftest.py` (root env shim for 4 env vars); `backend/tests/_fakes.py` (extracted Anthropic SDK fakes — `FakeAnthropicClient` + 5 supporting dataclasses — for cross-conftest reuse by integration + future eval suite); `backend/tests/integration/` test suite (36 tests across `test_health`, `test_starter_prompts`, `test_auth`, `test_rate_limit`, `test_security_headers`, `test_cors`, `test_ready`, `test_chat`); `backend/tests/unit/api/` test suite (22 tests across `test_auth`, `test_rate_limit`, `test_security_headers`, `test_starter_prompts_config`).

#### Branch: `chore/dockerfile-fly`

- [x] `backend/Dockerfile` — multi-stage with `uv` + BuildKit secrets (Fork 41) _(builder bakes the RAG index via `--mount=type=secret,id=openai_key`; slim non-root runtime carries only venv + artifacts + data/knowledge/src/prompts. **Added `ENV UV_PYTHON_DOWNLOADS=0` to the builder** — a deliberate divergence from the `context/07-infrastructure.md` snippet: uv defaults to a managed interpreter, but the runtime stage copies only `/app/.venv`, so without it the venv's `python` symlink dangles in the final image and the container crash-loops on boot. Confirmed by the official uv Docker guide.)_
- [x] `backend/.dockerignore` _(excludes `chroma_db/` / `bm25.pkl` / `manifest.json` / `.venv/` / `tests/` / `.env*` so stale local artifacts never leak into the build context)_
- [x] `backend/fly.toml` — `iad` region, shared-cpu-1x 1GB always-on, `/health` HTTP check (Forks 36, 37) _(verbatim from spec; valid current `fly.toml` format confirmed via Context7)_
- [x] First Fly deploy: `flyctl launch` + `fly secrets set` for all backend env vars _(used `fly apps create` rather than `fly launch` to avoid clobbering the hand-authored `fly.toml`; staged 6 runtime secrets + the OpenAI key as a build secret. **Discovery — `OPENAI_API_KEY` is a RUNTIME secret, not build-time-only**: the first deploy crash-looped at lifespan with `chromadb ValueError: CHROMA_OPENAI_API_KEY ... not set` because dense retrieval embeds each user query through OpenAI at request time. Resolved by setting it as a 7th Fly secret — no code change, `main.py` already mirrors it to `os.environ`. This contradicts the Fork 17/39 "build-time only" decision; `backend/.env.example` comments corrected on-branch.)_
- [x] Verify `/health` and `/ready` respond correctly on the deployed URL _(`/health` → 200 `{"status":"ok"}`; `/ready` → 200 `status: ready` with duckdb `entries_count:1200`, chroma `chunk_count:39`, bm25 ok, manifest fields from `/app/manifest.json`)_

#### Branch: `feat/web-mvp` _(PR #11; 3 chunk commits + 1 Copilot-review-fix commit)_

- [x] `frontend/package.json` with `packageManager: "pnpm@9.x.x"` field + `engines.node >= 20` _(landed as **`pnpm@11.1.3`**, matching the installed/`.tool-versions` pin — the "9.x" target was stale; `engines.node >= 20`. Also added `frontend/pnpm-workspace.yaml` with `allowBuilds: {sharp, unrs-resolver}` because pnpm 11 blocks dependency build scripts by default and its `verify-deps-before-run` hook otherwise fails every `pnpm <script>` with `ERR_PNPM_IGNORED_BUILDS`.)_
- [x] `frontend/vercel.json` — `regions: ["iad1"]`
- [x] Next.js App Router scaffolding (`app/layout.tsx`, `app/page.tsx`, `app/globals.css`) _(Next 15 + React 19; Tailwind v3 + shadcn HSL theme tokens; `tsconfig.json` strict with `@/*`→`src/*`. `layout.tsx` metadata is minimal `robots: noindex` — favicon/OG (G22) deferred to a later branch.)_
- [x] Tailwind + shadcn/ui installation _(shadcn v3 manual install — Tailwind `^3.4` per the locked stack, NOT the v4 oklch pattern current shadcn docs default to; `cn()` util + `components.json`; Button + Textarea primitives copied in. Sheet/HoverCard/Toast/Collapsible/Badge come with their later branches.)_
- [x] `frontend/src/lib/api.ts` — API client with structured error handling _(non-streaming `sendChat()` → `POST /api/chat`; **strips the assistant `sidecar` to `{role, content}` before sending** because the backend `Message` schema is `extra="forbid"`; maps every failure to `ApiError`; parses both `{detail:{...}}` and 422 `{detail:[...]}` error shapes. The spec sketch showed the streaming variant — Phase 1 is non-streaming; SSE is `feat/streaming` Day 6.)_
- [x] `frontend/src/lib/storage.ts` — localStorage Phase 1 (single active conversation, Fork 7) _(`load`/`save`/`clear`; UUID/title/timestamp preservation; private-mode + quota-exceeded graceful degradation. **Shape-guard added in the Copilot-fix commit**: `loadActiveConversation` validates `Array.isArray(messages)` and returns null on a corrupt/legacy shape, so bad localStorage can't crash `Chat`'s render on every reload — there's no ErrorBoundary yet, G20.)_
- [x] `frontend/src/lib/types.ts` — hand-written placeholder types (replaced in Day 4 by G3 codegen) _(byte-accurate mirror of `agent/contracts.py`: `Message`, `ChatRequest`, `Citation`, `ToolCallTrace`, `Assumption`, `RefusalCategory`, `ResponseMeta`, `ChatResponse` + UI-only `ChatMessage`. `lib/errors.ts` carries the `ApiError` class; the G10 toast map is deferred to `feat/error-boundary`.)_
- [x] `frontend/src/app/api/chat/route.ts` — Next.js server-side proxy injecting `X-API-Key` (Fork 29 non-streaming variant) _(reads `BACKEND_URL` + `BACKEND_API_KEY` server-side; misconfig guard → 500, unreachable-backend guard → 502. **Forwards `Retry-After`** + deliberately rebuilds a minimal header set, NOT all upstream headers — Copilot-fix commit.)_
- [x] Minimal `<Chat>` component: chat bubbles, input, "+ New chat" button (Fork 33 Phase 1) _(`useReducer` lifecycle: hydrate → submit → persist; `MessageBubble` renders assistant prose via `react-markdown` + `remark-gfm` with overflow-safe tables; `Header` "+ New chat" (confirm only when >5 msgs); `ChatInput` 2000-char cap. **Verified live end-to-end via browser preview** against the deployed Fly backend: empty state → real answer with RAG citations + Release-Date/shell-exclusion domain logic → localStorage persist + reload-restore → New-chat clears state + storage; zero console errors.)_

#### Branch: `chore/ci-cd` _(PR #12 + 2 post-merge deploy hotfixes: `fix/deploy-flyctl-tag`, `fix/deploy-dockerfile-path`)_

- [x] `.github/workflows/ci.yml` — backend (lint + typecheck + unit + integration), frontend (lint + typecheck + build), secret-scan (gitleaks) _(**3 jobs only** — `api-contract` (G3) and `evaluation-freshness` deferred to their Day-4 branches since their prerequisite files don't exist yet. Backend: `setup-uv@v6` → `uv sync --locked` (install + lockfile-drift assert, replacing the spec's two-step `--frozen` + `uv lock --check`) → ruff → mypy → **build RAG index (needs `OPENAI_API_KEY`)** → pytest. Frontend: `pnpm/action-setup@v4` pinned `11.1.3` + `setup-node@v4` **Node 22** → install → lint → typecheck → build (no `pnpm test` — Vitest is Day 6). Also folded in the `frontend/tsconfig.json` `baseUrl` removal (TS-7.0 deprecation).)_
- [x] `.github/workflows/deploy.yml` — Fly deploy on push to `main` + `/ready` smoke test _(`flyctl deploy backend --config fly.toml --remote-only` + retry-loop smoke test; manual rollback per G17, no auto-rollback. `setup-flyctl@v1`.)_
- [x] Vercel project linked to GitHub repo: Root Directory = `frontend`, auto-preview on PR _(user-performed; env vars `BACKEND_URL` + `BACKEND_API_KEY` set for Production + Preview; **Vercel Deployment Protection disabled** so the demo URL is publicly reachable — required for the recruiter demo link.)_
- [x] GitHub Secrets configured: `FLY_API_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` _(user-performed; `OPENAI_API_KEY` is needed by **both** deploy.yml (build secret) AND ci.yml backend (RAG-index build) — set before the CI re-run, not just before deploy. The 3 Langfuse/Anthropic keys are staged for `eval.yml` on Day 4.)_
- [x] Branch protection on `main` (if repo is public): require PRs, require status checks, linear history, rebase-merge only _(user-performed; required checks = the exact 3 job names `backend`, `frontend`, `secret-scan` — `api-contract` added when that job lands Day 4. Admin bypass left ON so the direct-to-main admin sweep keeps working.)_
- [x] Configure rebase-merge as the only allowed merge strategy in repo settings _(user-performed + visually confirmed "Rebase and merge" is the sole PR option)_

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

### 2026-06-02 — Day 3 close: containerize + Fly deploy + web MVP + CI/CD + live demo (4 feature branches, 2 deploy hotfixes, 2 Copilot review rounds)

- **Branch(es) touched**: `chore/dockerfile-fly`, `feat/web-mvp`, `chore/ci-cd`, `fix/deploy-flyctl-tag`, `fix/deploy-dockerfile-path`, `main` (admin sweep).
- **PRs**: merged 5 — `chore/dockerfile-fly` (3 files, manual interactive Fly deploy), `feat/web-mvp` PR #11 (3 chunks + Copilot-fix commit), `chore/ci-cd` PR #12 (1 commit + Copilot-fix), `fix/deploy-flyctl-tag`, `fix/deploy-dockerfile-path` (the two post-merge deploy hotfixes).
- **Progress**: **Day 3 fully complete — the demo is live end-to-end.** Backend containerized (multi-stage `uv` Dockerfile + `.dockerignore` + `fly.toml`) and deployed to Fly (`customs-agent-backend.fly.dev`) via an interactive first deploy (user ran `flyctl`; Claude guided). Next.js Phase-1 chat MVP (App Router + Tailwind v3 + shadcn; `lib/{types,errors,storage,api}` + server proxy + `Chat`/`MessageBubble`/`Header`/`ChatInput`) deployed to Vercel and verified live. CI (`ci.yml` 3 jobs) + automated deploy-on-merge (`deploy.yml`) wired; GitHub Secrets, branch protection, rebase-only, and Vercel linking all configured. Final production verification: automated deploy green, `/ready` `built_at` advanced (proving the pipeline rebuilt + shipped), and a real Tier-3 question ("PCA effective duty rate Q1 2025" → 44.06% with full duty-component breakdown + business rules) answered correctly through the deployed Vercel→Fly→LLM chain.
- **Decisions / surprises**:
  - **`OPENAI_API_KEY` is a RUNTIME secret, not build-time-only (contradicts Fork 17/39).** The first Fly deploy crash-looped at lifespan: dense retrieval embeds each user query through OpenAI at request time (chromadb's `query` path), so the running container needs the key — it isn't just baked into the image. Resolved by setting it as a Fly secret (no code change; `main.py` already mirrors it to `os.environ`). Same key is also needed by the **CI backend job** (see below) and `deploy.yml` (build secret). `backend/.env.example` comments corrected on the `chore/dockerfile-fly` branch (config file → normal branch flow, not a deferred doc). New CLAUDE.md Critical Gotcha #19.
  - **Dockerfile `UV_PYTHON_DOWNLOADS=0` (divergence from the spec snippet).** uv defaults to a downloaded/managed interpreter, but the runtime stage copies only `/app/.venv` — without pinning system Python the venv's `python` symlink dangles in the final image and the container crash-loops. Added to the builder stage; the official uv Docker guide does exactly this for the copy-the-venv multi-stage pattern. New CLAUDE.md Critical Gotcha #20.
  - **Workflow slip — premature implementation in plan mode.** Early in the session Claude misread a harness signal as plan approval and began creating the Dockerfile files; the user blocked it. Re-confirmed clean state and re-implemented from the top after explicit approval. Reinforces: end the planning turn only via ExitPlanMode and wait for the user.
  - **Frontend env var rename — `NEXT_PUBLIC_BACKEND_URL` → `BACKEND_URL`.** The committed `.env.example` declared the URL `NEXT_PUBLIC_`, but the server-side proxy reads `process.env.BACKEND_URL`. The browser never calls the backend directly (all traffic goes through the same-origin `/api/chat` proxy), so it's correctly server-side-only. `.env.example` edited on-branch; user mirrored `.env.local`.
  - **pnpm 11 friction (twice).** (1) `pnpm install` failed `ERR_PNPM_IGNORED_BUILDS` for `sharp` + `unrs-resolver` — pnpm 10+/11 blocks dependency build scripts by default; the `package.json` `pnpm` field is no longer read (moved to `pnpm-workspace.yaml` `allowBuilds`). (2) **CI frontend job failed**: `pnpm 11.1.3 requires Node ≥ 22.13` (uses the `node:sqlite` builtin) → `ERR_UNKNOWN_BUILTIN_MODULE` on the spec's Node 20. Fixed by Node 22 (which also matches `.tool-versions`). New CLAUDE.md Critical Gotcha #21.
  - **CI backend job failed — missing RAG index.** This was the first real CI run (PR #11 merged while workflows were still placeholders), so a fresh checkout had no `chroma_db/`/`bm25.pkl` (gitignored) — every integration test ERROR'd with `chromadb NotFoundError: Collection [knowledge] does not exist` because the `client` fixture boots the full app via lifespan. Fixed by adding a "Build RAG index" step (needs `OPENAI_API_KEY`) before pytest, mirroring `eval.yml`. The plan's "CI needs no secrets" claim was wrong. New CLAUDE.md Critical Gotcha #22. **Diagnosed authoritatively from `gh run view --log-failed`** (user granted one-time read-only `gh`), not by guessing.
  - **Two post-merge deploy hotfixes (deploy.yml can only be tested on `main`).** Because `deploy.yml` only fires on push-to-main, each fix had to merge before we learned if it worked, peeling back two layers: (1) `setup-flyctl@v1.5` **does not exist** — the repo's tags are irregular (the release *titled* "v1.5" maps to a tag literally named `1.5`; `v1` is the maintained major tag). Misread of the `gh release list` title column; fixed to `@v1` (verified via WebFetch). (2) `flyctl deploy --config backend/fly.toml` from repo root failed `app does not have a Dockerfile or buildpacks configured` — Fly resolves the Dockerfile relative to the **build-context/working-directory**, not the `--config` path. Fixed to `flyctl deploy backend --config fly.toml` (pass `backend` as the workdir arg), replicating the manual `cd backend && fly deploy`. Confirmed against Fly's monorepo docs via Context7. New CLAUDE.md Critical Gotcha #23.
  - **PR #11 Copilot review (web-mvp) — 4 comments, all addressed pre-merge.** #1 (`tsconfig paths needs baseUrl`) was **factually wrong for TS 4.1+/5.9.3** — declined; the deferred `baseUrl` removal was applied later on `chore/ci-cd`. #2 storage shape-guard (genuine crash vector — fixed), #3 proxy header forwarding (forward `Retry-After` + minimal-rebuild, fixed), #4 `rel="noopener noreferrer"` (fixed). Verified the storage guard live (injected malformed localStorage → degrades to empty state, no crash).
  - **PR #12 Copilot review (ci-cd) — comments 2/3/4 applied** (quote build-secret; pin flyctl off `@master`; fix `set -e`+`curl -f` smoke test with a retry loop). Comment 1 (re-add `baseUrl`) declined as factually wrong. Note: Copilot did NOT catch either real CI failure (Node 22, missing RAG index) — the `gh` logs did.
  - **Action-version corrections vs. the `08-cicd-and-testing.md` snapshot** (verified current via Context7 + WebSearch): `setup-uv@v3→v6`, `pnpm/action-setup@v3 version:9 → @v4 version:11.1.3`, Node `20→22`, `uv sync --frozen`+`uv lock --check` → `uv sync --locked`. gitleaks `@v2` with `GITHUB_TOKEN` only (no `GITLEAKS_LICENSE` — that's org-repos only).
  - **Vercel Deployment Protection** was on by default (production URL returned a 401 SSO wall) — would block a recruiter's demo click. User disabled it; production then verified publicly reachable + the API key confirmed absent from the page HTML (proxy isolation working).
  - **Visual frontend verification caveat** — the Claude_Preview MCP tools only attach to local `launch.json` servers, not arbitrary external URLs, so no literal screenshot of the *production* Vercel URL was captured. Production was instead proven end-to-end at the HTTP level (curl through the proxy → real LLM answers), and the identical committed build's UI was screenshotted locally earlier in the session.
- **Next session**: Day 4 — `feat/remaining-tools-and-eval` (3 more tools `top_hts_by_duty`/`qbr_summary`/`compare_customers` + Fork-46 grading + `eval.yml` + EVALUATION.md generator + the `evaluation-freshness` advisory CI check), `feat/observability-base` (structured logging replacing interim `api/_request_id.py`), `feat/api-contract` (OpenAPI snapshot + frontend `api-types.ts` codegen + the deferred `api-contract` CI job → then add it to branch-protection required checks).

---

### 2026-05-29 — Day 2 close + Day 3 backend deploy (2 branches shipped, 7 chunk commits, PR #9 Copilot review fixes)

- **Branch(es) touched**: `test/backend-units`, `feat/fastapi-backend`, `main` (admin sweep).
- **PRs**: merged 2 — `test/backend-units` PR #8 (single chunk; 41 data-layer tests closing Day 2); `feat/fastapi-backend` PR #9 (6 chunks: 3 cross-cutting middleware + config package + cheap endpoints, app + chat router + smoke integration, deep integration suite, OPENAI_API_KEY lifespan fix, Copilot review fixes).
- **Progress**: Backend suite grew 249 → 290 → 304 → 312 → 320 → 348 → 356 across the 7 chunks. Day 2 closed with data-layer unit tests (12 + 15 + 14 across `test_load.py` / `test_views.py` / `test_validation.py`) and the two-fixture conftest pattern (session `duckdb_con` + function `fresh_duckdb_con`). Day 3 shipped the full FastAPI orchestration layer: `main.py` lifespan boot (data → views → validate → retriever → AgentContext → loop_settings) + 4 middleware (SecurityHeaders → CORS → slowapi → RequestId, in inner-to-outer add order per the Starlette prepend semantics fixed before PR merge) + 5 endpoints (`/health`, `/ready`, `POST /chat`, `GET /api/starter-prompts`, plus FastAPI auto-generated `/docs` + `/openapi.json`). Config package conversion (`config.py` → `config/__init__.py` + `_settings.py` + `starter_prompts.py`). Test fakes extraction to `tests/_fakes.py` for cross-conftest reuse.
- **Decisions / surprises**:
  - **Commit message format change** — switched from "wrap body at 72 chars" to "single-line paragraphs/bullets, no hard wrap." Renders identically in GitHub PRs but stays readable in narrow terminals when wrapped by the client rather than baked into the diff. CLAUDE.md "Commit Message Format" updated this session.
  - **Tracking-doc edit timing** — established workflow rule: edits to `CLAUDE.md`, `PROGRESS.md`, and any file under `context/` happen at END of a session only when the user explicitly asks for the admin sweep. Individual sessions stay focused on code work; the closing admin commit batches all tracking-doc updates. When a code chunk would otherwise diverge from a `context/*.md` spec snippet (as the PR #9 Copilot Comment 1 middleware-order fix did), call out the spec drift in the chunk-completion message and defer the spec edit to the end-of-session sweep. CLAUDE.md "Branches & PRs" updated this session.
  - **PR #9 Copilot review — all 5 comments addressed before merge as a single chunk** (one-PR pattern, not the separate `chore/copilot-review-cleanup` branch precedent from PR #5). All 5 were legitimate bugs, none spec-intentional. Fix 1 — Starlette `add_middleware` PREPENDS so the LAST call wraps OUTERMOST; the chunk-3a [SEM, CORS, SlowAPI, RequestId] add order placed SEM INNERMOST instead of outermost, so 429 responses + CORS preflight 200s shipped without the 4 defensive headers. Fixed by reversing to [RequestId, SlowAPI, CORS, SEM]; 3 regression tests (direct order assertion, 429 mini-app, real-client preflight). Fix 2 — `run_agent` was called without `settings=` so the loop silently used `DEFAULT_LOOP_SETTINGS` while `/ready` advertised the live env values; env-overridden `LLM_MODEL` / `AGENT_MAX_ITERATIONS` etc. silently no-opped. Fixed by building `AgentLoopSettings` from `Settings` in lifespan, stashing on `app.state.loop_settings`, forwarding as `settings=` kwarg; 2 tests (state-mirror + spy on kwargs). Fix 3 — manifest read/parse wrapped in `try/except` so corrupt JSON degrades to 503 not 500. Fix 4 — `retriever._bm25 is None` now flips `overall_ok = False` mirroring the chroma block pattern. Fix 5 — `secrets.compare_digest` was passed bare `str` so non-ASCII `X-API-Key` headers raised `TypeError` → 500 instead of the documented 403; fixed by encoding both args to UTF-8 bytes. All 5 documented in CLAUDE.md Critical Gotchas #14-17 + #18 for the slowapi quirk surfaced while testing Fix 1.
  - **pydantic-settings → `os.environ` gap** (chunk 3c, surfaced during local uvicorn smoke test) — pydantic-settings reads `.env` into the `Settings` model but does NOT export to `os.environ`. chromadb's `OpenAIEmbeddingFunction` reads `OPENAI_API_KEY` from `os.environ` directly at construction (chromadb 0.5+ raises `ValueError` on empty string), so local uvicorn 500'd at lifespan even though `Settings.openai_api_key` was populated. Test suite worked because `tests/conftest.py` sets the env var directly via `os.environ.setdefault`. Fix: `main.py:lifespan` does `os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)` BEFORE constructing the retriever. Production Fly is unaffected (fly secrets set env directly). Captured in CLAUDE.md Critical Gotcha #16.
  - **slowapi 0.1.9 `RATELIMIT_ENABLED` env override** (chunk 3b landmine, took an hour to diagnose) — slowapi's `Limiter` constructor calls `self.enabled = get_app_config(C.ENABLED, self.enabled)` at `extension.py:234` — reads the env var and silently OVERRIDES the constructor's explicit `enabled=True`. The chunk-3b `test_rate_limit.py:rate_limit_client` fixture had to toggle the env var around Limiter construction (and the new `headers_on_429_client` fixture in `test_security_headers.py` for Fix 1 too). Captured in CLAUDE.md Critical Gotcha #18.
  - **Drive-by bug fixes during chunk-3b integration tests** (not Copilot-flagged): (1) `api/health.py` manifest field key was `indexed_at_utc` per a stale spec reference — actual field per `scripts/build_index.py` is `built_at`. Caught by `test_ready_manifest_includes_build_fields_when_local_manifest_present` reading the real `backend/manifest.json`. Fixed in chunk 3b alongside the other integration tests. (2) DuckDB connection attributes are READ-ONLY (CPython extension class), so `monkeypatch.setattr(con, "execute", boom)` raises `AttributeError`. Tests that simulate duckdb subsystem failure swap the whole `app.state.db` attribute with a `_RaisingConnection` stub instead. Documented in `test_ready.py` docstring; not a CLAUDE.md gotcha since it's test-only.
  - **Config package conversion path resolution** (chunk 2) — original PROGRESS.md said `backend/config/starter_prompts.py` (outside the importable package); the spec at `context/05-api-and-backend.md:354` said `customs_agent.config.starter_prompts` (inside the package). Resolved by treating PROGRESS.md as a typo and landing the package conversion to honor the spec's import path. All 3 existing importers of `from customs_agent.config import settings` continue to work via re-export in `config/__init__.py`. The singleton `settings = Settings()` instantiation also moved here, with the `MANIFEST_PATH` module constant resolving Docker `/app/manifest.json` first and walk-up local fallback. PROGRESS.md path corrected in this session's admin sweep.
  - **Test fakes extraction** (chunk 3a) — moved `FakeAnthropicClient` + 5 supporting dataclasses (`FakeTextBlock`, `FakeToolUseBlock`, `FakeUsage`, `FakeResponse`, `_FakeMessagesAPI`) from `tests/unit/agent/conftest.py` to `tests/_fakes.py` so the integration suite + future eval suite can reuse them without cross-subdir conftest imports. Agent conftest re-imports + re-exports to preserve existing test imports. Future Day-4 eval suite will use the same fakes.
  - **Local uvicorn smoke test pattern** — `uvicorn customs_agent.main:app --port 8080` in background, `curl --retry-connrefused --retry 20 --retry-delay 1 /health` to wait for boot, then `/ready` + `/docs` + `/openapi.json`. macOS doesn't ship GNU `timeout`, so background uvicorn is killed via `lsof -ti:8080 | xargs kill -TERM` after the curls. Public endpoints work without an API key; `/chat` requires the key from `.env` (Claude can't read `.env`, so `/chat` is user-manual smoke).
- **Next session**: Day 4 begins with `chore/dockerfile-fly` (multi-stage Dockerfile with `uv` + BuildKit secrets per Fork 41, `fly.toml` with iad region + shared-cpu-1x 1GB always-on per Forks 36/37, `flyctl launch` + `fly secrets set` for all backend env vars, verify `/health` + `/ready` on deployed URL). After that, `feat/web-mvp` (Next.js scaffolding) and `chore/ci-cd` (real ci.yml + deploy.yml). Day 4 also unlocks `feat/remaining-tools-and-eval` (3 more tools + eval suite + EVALUATION.md generator), `feat/observability-base` (full structured logging replacing the interim `api/_request_id.py`), and `feat/api-contract` (OpenAPI snapshot + frontend codegen via G3).

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
