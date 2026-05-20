# Decisions Index

Fast lookup for every architectural decision locked during planning. For full
reasoning, trade-offs, and implementation notes, follow the **Detail in**
pointer to the authoritative context file. This index is the *shortcut*, not
the source of truth.

---

## Foundation (Forks 1–12)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 1 | Backend language | Python 3.12 + FastAPI | `05-api-and-backend.md` |
| Fork 2 | Agent pattern | Hybrid: RAG retrieves rules → LLM picks among 8 typed tools (no raw SQL surface) | `04-agent-and-tools.md` |
| Fork 3 | Data store | DuckDB load-to-memory at boot | `02-data-layer.md` |
| Fork 4 | Vector store | ChromaDB in-process, persisted to disk in Docker image | `03-rag-layer.md` |
| Fork 5 | LLM provider + model | `claude-sonnet-4-6` (Anthropic) for the main agent loop | `04-agent-and-tools.md` |
| Fork 6 | Frontend framework | Next.js App Router + Tailwind + shadcn/ui | `06-frontend.md` |
| Fork 7 | Conversation memory | Stateless backend + frontend `localStorage` (Phase 1 single-conversation; Phase 2 multi-conversation sidebar) | `06-frontend.md` |
| Fork 8 | Eval test design | Tier-hybrid: numeric assertions T1/T2/T4, LLM-as-judge for Q9, structured sidecar is the primary assertion surface | `08-cicd-and-testing.md` |
| Fork 9 | Security implementations | 8 controls (2 primary + 6 defense-in-depth) — see G7 for consolidated framing | `09-security.md` |
| Fork 10 | Observability | Two-layer: structlog (stdout JSON) + Langfuse Cloud (LLM traces) | `10-observability.md` |
| Fork 11 | CSV-in-deployment | Committed to repo at `backend/data/customs_entries_oct2024_mar2025.csv` (after Fork 35 move) | `02-data-layer.md` |
| Fork 12 | Citation attribution | Inline color-coded `[N]` pills + expandable "Sources & Computation" panel; backend builds the citations array | `06-frontend.md` |

## RAG Layer (Forks 13–17)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 13 | Embedding model | OpenAI `text-embedding-3-small` (build-time only; not needed at runtime) | `03-rag-layer.md` |
| Fork 14 | Chunking strategy | Section-header split with doc title + `section_kind` metadata; ~30 chunks total | `03-rag-layer.md` |
| Fork 15 | Always-on vs retrieval | Hybrid: Business Rules + Quirks + customer codes + schema + 4 metric definitions always-on; topical knowledge via retrieval | `03-rag-layer.md` |
| Fork 16 | Retrieval strategy | Hybrid BM25 + semantic with Reciprocal Rank Fusion, top-K = 5 (2K candidates per retriever before fusion) | `03-rag-layer.md` |
| Fork 17 | Reindex trigger | Build-time inside Dockerfile with BuildKit `--mount=type=secret,id=openai_key`; ChromaDB + BM25 + manifest baked into image | `03-rag-layer.md` |

## Data Layer (Forks 18–21)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 18 | Type coercion | Explicit CAST on load: `DECIMAL(18,2)` for money, `DATE` for dates, `BOOLEAN` for Yes/No, `NULLIF('', col)` for Section 301 / IEEPA, snake_case renames, derived: `port_of_entry_code`/`name`, `entry_type_code`, `is_china_origin` | `02-data-layer.md` |
| Fork 19 | Materialized views | `entry_lines_v` (line grain + period helpers) + `entries_v` (entry grain with capped MPF + multi-origin awareness + `is_shell` flag) | `02-data-layer.md` |
| Fork 20 | Shell-entry filter | `is_shell` flag in `entries_v` + `include_shell: bool = False` parameter across tools; threshold tightened to `LENGTH(entry_number) != 11 OR COALESCE(SUM(entered_value), 0) = 0` (data verified: 0 shells in current dataset) | `02-data-layer.md` |
| Fork 21 | Schema-as-context | Pydantic `Literal` enums for known dimensions (customer, country, port) + auto-generated schema fingerprint in `query_entries` tool description + concise Data Overview in always-on system prompt | `04-agent-and-tools.md` |

## Agent (Forks 22–29)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 22 | Tool surface | 8 tools across 3 layers: Layer 1 specialized (`effective_duty_rate`, `total_duty_breakdown`, `hold_summary`, `top_hts_by_duty`, `qbr_summary`, `compare_customers`) + Layer 2 builder (`query_entries`) + Layer 3 (`lookup_knowledge`) | `04-agent-and-tools.md` |
| Fork 23 | Max iterations | 5 with per-turn token budgets (50K input / 8K output) + same-(tool, args) dedup; graceful degradation on cap with sidecar `meta.iteration_limit_hit` | `04-agent-and-tools.md` |
| Fork 24 | Ambiguity handling | Default + state assumption + cite rule (never ask for routine ambiguities); narrow exception list for unparseable / out-of-range / multi-defensible | `04-agent-and-tools.md` |
| Fork 25 | Out-of-scope | 5-category system prompt block: off-domain, out-of-range, unmapped, meta (in-scope), adversarial; `refused: bool` + `refusal_category` on response | `04-agent-and-tools.md` |
| Fork 26 | Determinism | `temperature=0` everywhere; `seed=42` on OpenAI judge calls (Anthropic doesn't expose seed); residual non-determinism handled via Fork 43 tolerances + Fork 8 sidecar assertions | `04-agent-and-tools.md` |
| Fork 27 | System prompt | Templated: 7 modular section files in `backend/prompts/`, concatenated into stable cached prefix; `PROMPT_VERSION` constant rotates the cache when bumped | `04-agent-and-tools.md` |
| Fork 28 | Output format | Prose + markdown + structured sidecar with split authorship: LLM emits `[N]` markers, backend builds `knowledge_citations[]` + `tool_calls[]` + `assumptions[]` + `meta` from real history; orphan markers stripped | `04-agent-and-tools.md` |
| Fork 29 | Streaming | Phased SSE: Phase 1 token events, Phase 2 tool-trace events (`knowledge_retrieved`, `tool_call_started/completed`); non-streaming JSON fallback always available | `05-api-and-backend.md` |

## Frontend UX (Forks 30–34)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 30 | Empty state | 6 starter prompt chips covering all 4 tiers + meta; chip list shared with Fork 25 refusal suggestions; sourced from `/api/starter-prompts` | `06-frontend.md` |
| Fork 31 | Show agent's work | Collapsible per-message disclosure with 3 sections (Knowledge Sources / Computations / Assumptions) + Run Info footer | `06-frontend.md` |
| Fork 32 | Citations display | Inline color-coded pill markers (blue = knowledge, green = computation) sharing the Fork 28 number space; hover preview + click-to-jump-and-highlight | `06-frontend.md` |
| Fork 33 | Conversation reset | Phased: Phase 1 "+ New chat" button + single-conversation localStorage persistence; Phase 2 collapsible sidebar with multi-conversation list, auto-prune at 50 | `06-frontend.md` |
| Fork 34 | Mobile responsive | Basic Tailwind breakpoint approach + dedicated 30-min mobile pass on Day 6 (`100dvh`, safe-area-inset, single-column chips, slide-over sidebar) | `06-frontend.md` |

## Infrastructure (Forks 35–42)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 35 | Repo structure | Monorepo at existing root; `backend/` + `frontend/` as siblings; `data/` + `knowledge/` **moved into `backend/`** for cleaner Docker build context | `07-infrastructure.md` |
| Fork 36 | Region pinning | Fly `iad` (Ashburn) + Vercel `iad1` server functions; co-located with Anthropic primary endpoint | `07-infrastructure.md` |
| Fork 37 | Fly machine | `shared-cpu-1x` 1GB always-on (`auto_stop_machines = false`); `auto_start_machines = true` with `soft_limit = 50` for burst | `07-infrastructure.md` |
| Fork 38 | CORS allowlist | Env-var driven (`ALLOWED_ORIGINS`); exact production URL + project-scoped regex for Vercel previews (`customs-agent-*.vercel.app`); `allow_credentials = false` | `09-security.md` |
| Fork 39 | Secrets routing | Platform-native: GitHub Actions Secrets (build-time + CI) / Vercel Env (frontend server-side) / Fly Secrets (backend runtime) / local `.env` (committed `.env.example` only) | `07-infrastructure.md` |
| Fork 40 | Health endpoints | `/health` cheap liveness (Fly polls every 30s) + `/ready` deep readiness with build manifest (`prompt_version`, `embedding_model`, `chunk_count`, `built_at`) for CI smoke tests | `05-api-and-backend.md` |
| Fork 41 | Dockerfile | Multi-stage with `uv` from GHCR + BuildKit cache + secret mounts; non-root `app` user; `python:3.12-slim` base; ~310 MB final image; HEALTHCHECK mirrors `/health` | `07-infrastructure.md` |
| Fork 42 | Environment promotion | Vercel auto-previews on every PR (via GitHub integration) + main-only Fly deploys via GitHub Actions; per-PR Fly previews documented as future work | `08-cicd-and-testing.md` |

## Testing & Eval (Forks 43–46)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 43 | Ground truth | `backend/tests/ground_truth.py` computes all 11 canonical answers via SQL against the runtime views; emits `tests/ground_truth.json` fixture (committed) with dataset SHA-256 pin and per-Q tolerance + expected phrases/citations/tool_name | `02-data-layer.md` |
| Fork 44 | CI eval strategy | Three layers: unit + integration (mocked LLM) on every PR; real-LLM eval **path-triggered + nightly + manual + label-based** with content-hash cache + nightly drift-issue auto-open | `08-cicd-and-testing.md` |
| Fork 45 | Test pyramid | Three layers: `tests/unit/` (pure functions, no LLM), `tests/integration/` (`StubLLM` mocks, real tools/RAG/DB), `tests/eval/` (real LLM, parametrized over ground truth) | `08-cicd-and-testing.md` |
| Fork 46 | Pass criteria | Two-axis grading: Correctness (must pass — numeric tolerance + phrases + citations) + Architecture (warn-only — `expected_tool_name` + args partial-match); tier-specific assertion shapes; Q9 LLM-as-judge with 3/4 rubric pass threshold | `08-cicd-and-testing.md` |

## Security (Forks 47–51)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 47 | Rate limiting | `slowapi` with composite `(first 8 chars of API key, IP)` bucket; 20/min on `/chat` and `/chat/stream`, 60/min on `/api/starter-prompts`, none on `/health` and `/ready`; in-memory storage (single-machine); custom 429 with `Retry-After` | `09-security.md` |
| Fork 48 | Auth | Static `X-API-Key` validated at Fly via `secrets.compare_digest`; key injected server-side by Next.js proxy (browser never holds it); `/health` + `/ready` public | `09-security.md` |
| Fork 49 | Prompt-injection defense | 5 layers: (1) request-size cap (Pydantic `max_length=2000`), (2) system-prompt adversarial routing, (3) typed `Literal` tool args, (4) citation marker validator, (5) output sanity scrubber with full-response redaction on prohibited-pattern match | `09-security.md` |
| Fork 50 | SQL safety | No raw SQL surface (typed tools only — no `execute_sql` exists) + parameterized `?` values + column-name allowlists for `group_by`/`aggregations`/`order_by` (Pydantic validators) + SELECT-only `safe_execute` guardrail wrapping every `con.execute` | `09-security.md` |
| Fork 51 | Security headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security: max-age=63072000; includeSubDomains` via FastAPI middleware | `09-security.md` |

## Observability + Cost (Forks 52–56)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 52 | Log schema | Full trace per request; stdout JSON for app-level events (`request.received/completed/failed`, auth, rate-limit, refusal, redaction, SQL safety, CORS); Langfuse for agent reasoning (spans: `rag.retrieve`, `llm.call`, `tool.*`, `output.validation`); same `request_id` joins both | `10-observability.md` |
| Fork 53 | PII & retention | Demo posture: full traces in Langfuse 30d (free-tier default), Fly stdout ~5d (platform default), API keys logged as 8-char prefix only, system prompts NOT stored per-request (PROMPT_VERSION fingerprint only), user-message previews capped at 80 chars on refusal events only, structlog secret-shape scrubber | `10-observability.md` |
| Fork 54 | Log sinks | stdout JSON → `fly logs` + Langfuse Cloud for agent traces; dev/prod renderer split via `ENVIRONMENT` env var (ConsoleRenderer locally, JSONRenderer in prod) | `10-observability.md` |
| Fork 55 | Prompt caching | Anthropic `cache_control: ephemeral` on the entire stable system prefix (~2,880 tokens) + tool definitions (~1,100 tokens) = ~3,980 cached tokens; reduces eval-suite cost ~7× | `10-observability.md` |
| Fork 56 | Model routing | Single model for the main agent (`claude-sonnet-4-6`); three models partitioned by function: Sonnet (agent) + `gpt-4o-mini` (Q9 judge) + `text-embedding-3-small` (build-time embeddings) | `04-agent-and-tools.md` |

## Process (Forks 57–58)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| Fork 57 | MVP + cut list | 7-day phased plan: Day 1 Foundation → Day 2 Agent core → Day 3 Deploy + MVP → Day 4 Accuracy hardening → Day 5 Bonuses → Day 6 Streaming + extras → Day 7 Documentation; explicit cut list (streaming Phase 2 → sidebar Phase 2 → streaming Phase 1 → mobile pass → diagram → EVAL.md narrative depth) | `PROGRESS.md` |
| Fork 58 | Commit hygiene | Conventional Commits (`type(scope): subject`); ~54 commits across ~20 PRs; rebase-merge only; **no co-author attribution ever**; manual commits at logical chunks via VS Code Source Control | `CLAUDE.md` |

---

## Gap-Scrutiny Items (G1–G26)

### Critical (G1–G6)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| G1 | LLM provider lock | `claude-sonnet-4-6` (resolved together with Fork 5 lock) | `04-agent-and-tools.md` |
| G2 | Frontend testing | Vitest unit tests for `frontend/src/lib/` pure-function modules only (SSE parser, storage, citations, api client); no component tests, no Playwright E2E for the demo | `08-cicd-and-testing.md` |
| G3 | Type sharing | FastAPI emits `openapi.json` (via `backend/scripts/export_openapi.py`) → `openapi-typescript` generates `frontend/src/lib/api-types.ts`; both files committed; `api-contract` CI job verifies drift | `08-cicd-and-testing.md` |
| G4 | PR workflow | Feature branches per Fork 57 phase + PR + **rebase-merge** to `main` (squash and merge-commit disabled at repo level); VS Code Source Control as the user's commit interface | `08-cicd-and-testing.md` |
| G5 | EVALUATION.md production | Static snapshot committed at submission, **regeneratable** via `backend/scripts/generate_evaluation_md.py`; header contains `prompt_version` + `model` + `dataset_sha` + reproducibility command + trace-link freshness disclaimer | `11-deliverables.md` |
| G6 | First-time setup | Root `Makefile` (canonical entry; `make help` for self-doc) + `scripts/setup.sh` (interactive first-run, idempotent) + `.tool-versions` (Python 3.12, Node 20, pnpm 9 for mise/asdf users) | `07-infrastructure.md` |

### Important (G7–G13)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| G7 | Security control count | Use Fork 51's 8-control list as canonical (retire Fork 9's earlier "3 controls" framing); README presents two-tier structure: 2 Primary (auth + rate limit) + 6 Defense-in-depth | `09-security.md` |
| G8 | API versioning | No URL or header versioning for the demo (single consumer); production future work is URL versioning + RFC 8594 `Sunset` header + 6-month deprecation policy | `05-api-and-backend.md` |
| G9 | History pruning | Token-budget-driven (50K threshold), oldest-turn-pair-first eviction; preserve current user msg + retrieved chunks + last 2 turn pairs minimum; `meta.history_truncated_turns` signal to UI | `04-agent-and-tools.md` |
| G10 | Auth-failure UX | Unified `ApiError` shape returned by `lib/api.ts` + single `<ErrorToast>` component + mapping table covering 401 / 403 / 422 / 429 (with `retry_after` countdown) / 5xx / network failure / SSE disconnection | `06-frontend.md` |
| G11 | Cost-tracking constants | `backend/src/customs_agent/observability/pricing.py` — TypedDict-shaped `PRICING` dict + `estimate_cost()` helper; manual quarterly verification with date comment in docstring | `10-observability.md` |
| G12 | Backend dependency mgmt | `uv` everywhere — no `pip`, no exceptions (except the Dockerfile line that bootstraps `uv` itself via GHCR); `uv.lock` committed; `uv lock --check` in CI prevents drift | `07-infrastructure.md` |
| G13 | Frontend package mgr | `pnpm` 9.x pinned via `"packageManager": "pnpm@9.x.x"` in `package.json` (Corepack enforces) + `"engines": {"node": ">=20"}` + `.tool-versions` entry | `07-infrastructure.md` |

### Minor (G14–G26)

| # | Topic | Decision | Detail in |
|---|---|---|---|
| G14 | Performance budgets | Codified budget table in README (FCP < 1.5s, TTFT < 2.0s p50, Tier 1 < 3s, Tier 3 < 6s, `/health` < 100ms p99, eval suite < 3 min); tracked via Langfuse, not enforced in CI | `11-deliverables.md` |
| G15 | Browser support | One-line statement: "Modern evergreen (Chrome / Edge / Firefox / Safari, last 2 versions). Mobile Safari supported with SSE-throttling caveat (G23)." | `11-deliverables.md` |
| G16 | Custom domain | **Skipped** — using default `*.vercel.app` and `*.fly.dev` URLs | — |
| G17 | Auto-rollback | Manual via `flyctl releases rollback` (backend) / Vercel dashboard or `vercel rollback` (frontend); commands documented in `backend/README.md` under "Troubleshooting → Deploy issues" | `07-infrastructure.md` |
| G18 | Local dev parity | Primary path is `make dev-backend` (uvicorn with reload — 10× faster iteration); `make build && docker run …` for pre-push verification against the actual production image | `07-infrastructure.md` |
| G19 | Provider cost alerts | Manual dashboard configuration before submission (Anthropic + OpenAI monthly soft caps at $20 each) + one-line README "Operations" note; no programmatic alerting | `10-observability.md` |
| G20 | Frontend error boundary | One top-level `<ErrorBoundary>` wrapping `<Chat>` in `app/layout.tsx` with graceful fallback UI; per-component boundaries + Sentry trip capture + "Reload conversation" button = future work | `06-frontend.md` |
| G21 | Accessibility overall audit | **Skipped** — relying on shadcn/ui defaults + per-feature aria/keyboard attention from Forks 30–34 | — |
| G22 | SEO / page metadata | Minimal: `metadata` export in `app/layout.tsx` with title, description, OG image, favicon; **user provides assets** at the relevant chunk (Claude will prompt): `frontend/public/favicon.ico` + `frontend/public/og-image.png` (1200×630) | `06-frontend.md` |
| G23 | Background SSE | Accept the browser tab-throttling limitation; one-line README "Known limitations" note; Service Worker buffering = future work | `06-frontend.md` |
| G24 | OpenAI `system_fingerprint` | Capture in Langfuse trace metadata for judge calls only (~3 lines); skipped for Anthropic (no equivalent field exposed) | `10-observability.md` |
| G25 | `PROMPT_VERSION` drift badge | `<MessageBubble>` reads `message.meta.prompt_version`; if different from `CURRENT_PROMPT_VERSION`, shows a subtle `v1.0.0`-style badge with tooltip explanation | `06-frontend.md` |
| G26 | Future-work organization | README "Future Work" section grouped by 10 categories matching Fork 58 commit scopes (Security, Observability, Data layer, RAG, Agent, Frontend, Infrastructure, Compliance, Cost optimization, Documentation); consolidation pass during Day 7 docs | `11-deliverables.md` |

---

## Recruiter Topic Documentation Hooks

The recruiter flagged five topics to be aware of. These are **interview-prep
signals** — no plan change, no code change. Documented as trade-off awareness
in the Day 7 README pass (`docs/final-polish` branch).

| Topic | Coverage in our plan | README placement |
|---|---|---|
| Vercel deployments | ✅ Fully implemented (Forks 6, 36, 38, 39, 42) | "Infrastructure decisions" section |
| Fly.io | ✅ Fully implemented (Forks 36, 37, 39, 41, 42) | "Infrastructure decisions" section |
| Azure Container App Jobs | ❌ Not implemented — **substituted by Fly.io** | "Infrastructure decisions" section: explicit Fly ↔ Azure Container Apps equivalent mapping table (note: "Container App **Jobs**" is the batch/scheduled variant; the always-on HTTP equivalent is "Container Apps") |
| GitHub integration with above | ✅ Vercel + Fly via GitHub Actions; Azure not wired | "How CI/CD works" section |
| Graphite for code push & deployments | ❌ Plain git + GitHub PRs with rebase-merge — **substituted by GitHub PRs** | "How we'd ship this on the team" subsection: Graphite stacked-PR pattern as team-scale upgrade |

---

## Skipped Items (explicit transparency)

| Item | Reason | Future work? |
|---|---|---|
| G16 — Custom domain | $12/year for marginal polish; default URLs read as "demo" appropriately | No |
| G21 — Accessibility overall audit | shadcn/ui defaults + per-feature attention in Forks 30–34 suffice for demo scale | No |
| Fork 17 — Cache pre-warm at deploy | Anthropic prompt cache TTL is 5 min; reviewers typically arrive >5 min post-deploy | Mentioned in `10-observability.md` |
| Per-PR Fly preview apps (Fork 42 option c) | Hours of plumbing for marginal demo benefit | Documented in `08-cicd-and-testing.md` |

Plus ~30 other deferred items consolidated in the README "Future Work" section
(Day 7 polish per `docs/final-polish` branch). See `11-deliverables.md` for the
category-grouped organization plan.
