# Customs Analytics Agent — Pedestal AI Take-Home

Conversational Q&A agent over U.S. customs entry data, grounded in a domain
knowledge layer. Take-home project for **Pedestal AI** following the brief in
[`CASE_STUDY.md`](CASE_STUDY.md).

> **Time budget**: 5–7 days from start. **Submission**: GitHub repository
> (public or invite-only) with a deployed demo URL.

---

## Session-Start Protocol

At the start of every Claude Code session in this project:

1. **Read this file** (`CLAUDE.md`) — already loaded.
2. **Read [`PROGRESS.md`](PROGRESS.md)** — check current phase, current branch,
   last session log, and the next checklist item.
3. **Identify the task** from the user request or the next checklist item.
4. **Load only the matching [`context/`](context/) file(s)** for the task —
   never load all of them. See the index at the bottom of this file.

The `context/` files are loaded **on demand**, not at session start, to keep
the context window lean.

---

## Hard Workflow Rules

These are non-negotiable across every session.

### Commits

- **Claude must NEVER run `git`, `gh`, or any history/PR-modifying command.**
  The user runs all git operations manually via VS Code Source Control
  (Cmd+Shift+G G on macOS).
- **No co-author attribution on any commit, ever.** Suggested commit messages
  must never include `Co-Authored-By:` or any AI-attribution trailer.
- **Manual commits at logical chunk boundaries.** When Claude finishes a
  self-contained piece of work (typically 30–90 minutes, 1–15 files touched),
  it pauses with a structured "🛑 LOGICAL CHUNK COMPLETE" message and waits
  for the user to commit before continuing.

### Branches & PRs

- **Never commit directly to `main`.** All work happens on feature branches.
- **Exception — tracking docs go straight to `main`.** `CLAUDE.md`,
  `PROGRESS.md`, and `context/*.md` updates are administrative and
  commit directly to `main` (no branch, no PR). All code and config
  changes still follow the branch + PR workflow.
- **Timing for tracking-doc edits**: edits to `CLAUDE.md`,
  `PROGRESS.md`, and any file under `context/` happen at the END of a
  session only, when the user explicitly asks for the admin sweep.
  Individual sessions stay focused on code work; the closing admin
  commit batches all tracking-doc updates so the session boundary is
  clean. If a code chunk would otherwise diverge from a `context/*.md`
  spec snippet (e.g., the middleware-order correction from PR #9
  Copilot Comment 1), call out the spec drift in the chunk-completion
  message and DEFER the spec edit to the end-of-session sweep.
- **Branch naming**: `<type>/<short-kebab-name>` where `<type>` matches the
  dominant Conventional Commits type for the branch
  (e.g., `feat/data-layer`, `chore/dockerfile-fly`, `docs/final-polish`).
- **One PR per Fork 57 phase or sub-phase** — roughly 2–3 logical-chunk
  commits per PR. See `PROGRESS.md` for the planned branch list.
- **Merge strategy: rebase-merge only.** Preserves linear per-chunk history.
  Squash and merge-commit modes are disabled at the repo level.
- **When a phase completes** (no more planned items on the current branch),
  Claude outputs a "🚀 PHASE COMPLETE" message with a drafted PR title and
  body for the user to copy or refine, plus VS Code Source Control
  instructions for pushing and opening the PR.

### Commit Message Format

Conventional Commits: `<type>(<scope>): <subject>`.

- **Types**: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`,
  `build`, `ci`
- **Scopes**: `data`, `rag`, `tools`, `agent`, `prompts`, `api`, `web`,
  `infra`, `ci`, `obs`, `security`, `eval`

Body (when warranted) explains the **why**, not the **what** (the diff
is the what). Write paragraphs and bullets as single unwrapped lines —
the editor / git client handles soft wrapping. Same content renders
identically in GitHub PRs but stays readable in narrow terminals when
wrapped by the client rather than baked into the diff. (Previous
sessions wrapped at 72 chars; the no-wrap convention is locked from
2026-05-29 onward.)

**Forbidden in commit messages and PR bodies**: build-phase or "Day N"
references. `PROGRESS.md` is the only place where Day-N labels live;
commits and PRs are the public git history and must not reference the
internal planning calendar.

### EVALUATION.md handling

`EVALUATION.md` at the repo root is a **static snapshot deliverable**. Claude
must NEVER auto-regenerate it. Regeneration is **user-invoked only**:

```bash
cd backend && uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md
```

When changes affect agent behavior (anything under `prompts/`, `tools/`,
`agent/`, `rag/`, `data/`, or a `PROMPT_VERSION` bump), Claude reminds the
user at the chunk-completion message that EVALUATION.md should be
regenerated before the next submission-quality commit.

### Documentation hygiene

- **No build status / progress lines in `README.md`.** Tracking the
  project's build state lives exclusively in `CLAUDE.md` and
  `PROGRESS.md` so the README doesn't go stale between updates.
  Reserve the README for evergreen content (architecture, setup,
  deliverables).

### User assets to flag

When work reaches the `feat/empty-state-chips` or `chore/mobile-responsive`
branch (Day 5–6 per `PROGRESS.md`), Claude must prompt the user to place
these assets in `frontend/public/` before wiring metadata:

- `favicon.ico` (16×16 minimum)
- `og-image.png` (1200×630)

---

## Pause Templates

### 🛑 LOGICAL CHUNK COMPLETE

Used after each self-contained piece of work, on every branch.

```
🛑 LOGICAL CHUNK COMPLETE — awaiting your commit on `<branch-name>`

What was done
- <1–3 bullets describing the change>

Files changed
- A/M/D <paths>

Suggested commit message (Conventional Commits)
─────────────────────────────────────────────────
type(scope): subject

Optional body explaining WHY, wrapped at 72 chars.
─────────────────────────────────────────────────

To commit (VS Code Source Control):
1. Open the Source Control panel (Cmd+Shift+G G)
2. Review changes; stage all (+ icon) or stage individual files
3. Paste the commit message above into the message box
4. Click ✓ Commit (or press Cmd+Enter)

When committed, reply "continue" and I'll proceed with the next chunk.
```

### 🚀 PHASE COMPLETE

Used when a branch has landed all its planned items and is ready for PR.

```
🚀 PHASE COMPLETE — branch `<branch-name>` is ready to push and open as a PR

This branch landed <N> commits across the following work:
- <commit subject 1>
- <commit subject 2>
- ...

Suggested PR title
─────────────────────────────────────────────────
type(scope): brief PR title
─────────────────────────────────────────────────

Suggested PR body
─────────────────────────────────────────────────
<draft body summarizing what shipped, decisions referenced,
 CI checks expected to fire>
─────────────────────────────────────────────────

To push and open the PR (VS Code Source Control):
1. Click the sync icon in the bottom-left status bar
   (first push: VS Code will prompt "Publish Branch")
2. After push, open the Command Palette (Cmd+Shift+P) →
   "GitHub Pull Requests: Create Pull Request"
   OR open the GitHub web UI to create the PR manually
3. After CI passes on the PR, click "Rebase and merge"
4. Pull main locally: Source Control → "..." → Pull

When merged, reply "continue" and tell me the next branch
(or let me suggest one from PROGRESS.md's plan).
```

---

## Repo Layout

```
rag-case-study/
├── CLAUDE.md                       ← session-start backbone (this file)
├── PROGRESS.md                     ← phase checklist + session log
├── README.md                       ← project README (Day 7 deliverable)
├── EVALUATION.md                   ← evaluation snapshot (Day 7, user-regenerated)
├── CASE_STUDY.md                   ← the brief (provided)
├── Makefile                        ← canonical workflow entry point (`make help`)
├── openapi.json                    ← FastAPI OpenAPI snapshot (G3, regenerated via `make openapi`)
├── .tool-versions                  ← Python / Node / pnpm pins (mise / asdf)
├── scripts/
│   └── setup.sh                    ← interactive first-time setup
├── .github/workflows/
│   ├── ci.yml                      ← lint + typecheck + tests + api-contract (on PR + push to main)
│   ├── eval.yml                    ← real-LLM eval (path/label/nightly/manual; content-hash cache; secrets-gated; sticky PR comment)
│   └── deploy.yml                  ← Fly deploy on merge to main
├── context/                        ← granular spec files (load on demand)
│   └── [12 files; see index below]
├── backend/                        ← Python + FastAPI
│   ├── data/                       ← synthetic CSV dataset (moved from root)
│   ├── knowledge/                  ← 4 knowledge text files (moved from root)
│   ├── src/customs_agent/          ← src-layout package
│   │   ├── main.py                 ← FastAPI app + lifespan + middleware stack (PR #9)
│   │   ├── config/                 ← package: __init__.py (singleton + MANIFEST_PATH) + _settings.py + starter_prompts.py
│   │   ├── api/                    ← auth.py + _rate_limit.py + _security_headers.py + _request_id.py + chat.py + health.py + starter_prompts.py
│   │   ├── agent/                  ← loop + bootstrap + refusal + validator + history + contracts + prompt + _dispatch
│   │   ├── tools/                  ← 8 typed tools (Fork 22 complete) + _filters + _allowlists + _shared
│   │   ├── rag/                    ← chunker + retriever + always_on + _tokenize
│   │   └── data/                   ← load + views + validation
│   ├── prompts/                    ← system-prompt section files (Fork 27)
│   ├── scripts/
│   │   ├── build_index.py          ← build-time RAG indexing (Fork 17)
│   │   ├── export_openapi.py       ← OpenAPI snapshot generator (G3)
│   │   └── generate_evaluation_md.py  ← EVALUATION.md regenerator (G5)
│   ├── tests/
│   │   ├── conftest.py             ← root env shim (5 setdefault: ANTHROPIC_API_KEY, BACKEND_API_KEY, ALLOWED_ORIGINS, OPENAI_API_KEY, RATELIMIT_ENABLED=false)
│   │   ├── _fakes.py               ← shared Anthropic SDK fakes + FakeRetriever (cross-conftest reuse for unit + integration + eval)
│   │   ├── ground_truth.py + ground_truth.json    ← canonical answer key (Fork 43)
│   │   ├── unit/                   ← api/ + data/ + agent/ + tools/ + rag/ + eval/ subdirs (per-subdir conftest)
│   │   ├── integration/            ← FastAPI app via TestClient (PR #9) + stub_llm.py + agent-loop tests (Day 4)
│   │   └── eval/                   ← real-LLM eval (Day 4): _grading + _report + conftest + test_questions + test_out_of_scope
│   ├── chroma_db/ + bm25.pkl + manifest.json  ← `make build-index` artifacts (gitignored; Docker bakes; CI builds before integration tests; /ready reads manifest.json)
│   ├── pyproject.toml + uv.lock    ← uv-managed Python deps
│   ├── Dockerfile + .dockerignore  ← multi-stage build (Fork 41; UV_PYTHON_DOWNLOADS=0 in builder)
│   ├── fly.toml                    ← Fly.io deploy config (Forks 36, 37; LIVE at customs-agent-backend.fly.dev)
│   └── .env.example                ← backend secrets contract (Fork 39)
└── frontend/                       ← Next.js App Router on Vercel (LIVE; Phase-1 chat MVP)
    ├── src/app/                    ← layout + page + globals.css + api/chat/route.ts (server proxy)
    ├── src/components/             ← Chat, MessageBubble, Header, ChatInput + ui/ (Button, Textarea)
    ├── src/lib/                    ← api, storage, errors, types, utils (sse/citations land later branches)
    ├── public/                     ← favicon.ico + og-image.png (user-provided, G22 — later branch)
    ├── package.json + pnpm-lock.yaml + pnpm-workspace.yaml  ← pnpm 11.1.3 managed (allowBuilds: sharp, unrs-resolver)
    ├── vercel.json                 ← region pin (iad1)
    └── .env.example                ← frontend secrets contract (BACKEND_URL + BACKEND_API_KEY, server-side only)
```

---

## Common Commands

The root `Makefile` is the canonical entry point. Run `make help` for the full
list. The most common targets:

| Command | Purpose |
|---|---|
| `make install` | Install all deps (uv backend + pnpm frontend) |
| `make dev-backend` | Start FastAPI on `:8080` with autoreload |
| `make dev-frontend` | Start Next.js on `:3000` with HMR |
| `make test` | Run unit + integration tests (no real LLM cost) |
| `make eval` | Run real-LLM eval suite (requires API keys) |
| `make ground-truth` | Regenerate `backend/tests/ground_truth.json` |
| `make types` | Regenerate OpenAPI + frontend TS types (G3) |
| `make eval-md` | **(user-invoked only)** Regenerate `EVALUATION.md` |
| `make ci-local` | Run lint + typecheck + tests (same as CI on PR) |
| `make build` | Build backend Docker image locally |

**Claude must NEVER run `make eval-md`** — it overwrites a committed
deliverable. User-invoked only per G5.

---

## Tech Stack

| Layer | Choice | Source fork |
|---|---|---|
| Backend language | Python 3.12 + FastAPI | Fork 1 |
| Main agent LLM | `claude-sonnet-4-6` (Anthropic) | Fork 5 |
| Eval judge LLM (Q9 rubric) | `gpt-4o-mini` (OpenAI) | Fork 8 |
| Embedding model (build-time only) | `text-embedding-3-small` (OpenAI) | Fork 13 |
| Data layer | DuckDB load-to-memory at boot | Fork 3 |
| Vector store | ChromaDB in-process (persisted in Docker image) | Fork 4 |
| Frontend | Next.js App Router + Tailwind + shadcn/ui | Fork 6 |
| Backend deploy | Fly.io (`iad` region, shared-cpu-1x 1GB always-on) | Forks 36, 37 |
| Frontend deploy | Vercel (`iad1` server functions, GitHub auto-deploy) | Forks 36, 42 |
| CI/CD | GitHub Actions (3 workflows: ci, eval, deploy) | Fork 44 |
| Observability | structlog (stdout JSON) + Langfuse Cloud | Fork 10 |
| Backend package manager | `uv` (everywhere) | Fork 41, G12 |
| Frontend package manager | `pnpm` 11.1.3 via `packageManager` field + Corepack | Fork 35, G13 |

> **pnpm version note**: the spec/G13 originally said "9.x", but `.tool-versions`
> pins the installed `pnpm 11.1.3` / `nodejs 22.22.3`, and `package.json`'s
> `packageManager` field matches. pnpm 11 requires **Node ≥ 22.13** (CI uses
> Node 22) and reads build-script approvals from `pnpm-workspace.yaml`
> (`allowBuilds`), not the `package.json` `pnpm` field. See Critical Gotcha #21.

---

## Critical Gotchas

These are the landmines that will silently corrupt accuracy or behavior if
forgotten. Every session must remember them.

1. **MPF cap per entry** ($31.67 minimum, $614.35 maximum). Never sum
   line-level MPF without applying the cap at entry grain. Encoded in
   `entries_v.total_mpf_capped` (Fork 19). Tools use this, not the raw sum.
2. **Section 301 only on CN-origin lines**: `section_301_code` is `NULL`
   for non-CN lines; `section_301_duty` is `0.00` there (Fork 18). The
   CODE column is the authoritative applicability signal — use
   `WHERE section_301_code IS NOT NULL` to filter "lines that had
   Section 301 applied", not `WHERE section_301_duty IS NOT NULL`. The
   `COALESCE(SUM(section_301_duty), 0)` pattern in views is defensive
   against future NULL-shaped data and harmless for the zero-filled
   actual data.
3. **IEEPA only on Release Date ≥ 2025-02-01**: `ieepa_code` is `NULL`
   for earlier entries; `ieepa_duty` is `0.00` there (Fork 18). Same
   code-column-is-the-signal pattern as Section 301.
4. **Citation marker integrity**: the LLM writes `[N]` markers in prose; the
   backend builds the citations array from real retrieval and tool-call
   history (Fork 28). Orphan markers (referencing a non-existent N) must be
   stripped server-side before returning to the client. The Fork-28
   assembly is now fully implemented (Gotcha #25): `knowledge_citations[]`
   merges RAG retrieval + invoked tools' declared citations +
   `lookup_knowledge` chunks, deduped by `chunk_id`.
5. **Release Date is the default date filter** (KB §Business Rule 1). Every
   tool's date filter defaults to `release_date`, never `entry_filed_date`
   or `summary_date`.
6. **Shell entries excluded by default** (KB §Rule 5). The
   `include_shell: bool = False` filter parameter is omnipresent across tools
   (Fork 20). Current dataset has zero shell entries but the filter still
   applies for future safety.
7. **HTS code format**: always `XXXX.XX.XXXX` (with dots) when displayed in
   prose. Per KB §1 HTS Code.
8. **`PROMPT_VERSION` bumps rotate the prompt cache** (Fork 55). Bump it
   intentionally when `prompts/*` changes; otherwise leave it alone. The
   snapshot test at `backend/tests/unit/agent/test_prompt_snapshot.py`
   enforces this — any edit to a file under `backend/prompts/` MUST
   land with both a `PROMPT_VERSION` bump AND a refresh of
   `backend/tests/snapshots/system_prompt.md` in the same commit, or
   the snapshot test fails. Regenerate via
   `cd backend && uv run python -m customs_agent.rag.always_on` when
   the always-on block changes, plus a one-liner to dump the assembled
   prompt to the snapshot path (documented in the snapshot test's
   docstring).
9. **Dataset SHA-256 pin**: `ground_truth.json` carries the SHA of the CSV it
   was generated against; eval tests fail fast on drift (Fork 43).
10. **No raw SQL surface**: the agent has 8 typed tools (Fork 22). There is
    no `execute_sql(query)` tool. Parameterized `?` placeholders for values
    + Pydantic-enforced column-name allowlists for `group_by` / `aggregations`
    / `order_by` (Fork 50). The view-compatibility `model_validator` on
    `QueryEntriesInput` also rejects line-grain filters / columns on
    `entries_v` (and entry-grain rollups on `entry_lines_v`) at the
    schema boundary, with error messages naming the correct view so the
    LLM can self-correct.
11. **`structlog` is intentionally unconfigured pre-`feat/observability-base`**.
    The data layer's `validation.py` already calls
    `structlog.get_logger()` and emits a boot-time INFO event using the
    library default (stderr console output). The proper boot
    configuration — dev vs. prod renderer split (Fork 54), secret-shape
    scrubber processor (Fork 53), request-context binding — lands on
    `feat/observability-base`. Until then, do not "fix" the unconfigured
    state; once that branch lands, existing callers pick up the full
    config automatically at module import.
12. **Refusal marker mechanism** (Fork 25, locked on `feat/agent-loop`).
    The agent loop detects refusals by parsing an HTML-comment marker
    at the start of the LLM's response:
    `<!-- refusal:<category> -->`. The system-prompt rule that teaches
    the agent to emit the marker lives in `backend/prompts/scope.md`
    ("Internal refusal marker rule" section). The backend regex
    (`agent/refusal.py:REFUSAL_MARKER_RE`) tolerates leading
    whitespace, internal whitespace, and case-insensitive `Refusal`.
    Categories: `off_domain` / `out_of_range` / `unmapped` /
    `adversarial`. **`meta` is in-scope** — questions like "what can
    you do?" get full normal answers without the marker. Unknown
    categories (e.g., `<!-- refusal:typo -->`) are logged at WARNING
    and treated as non-refusal so we never silently fabricate a category.
13. **`query_entries` tool description placeholders are filled at boot**
    (Fork 21, closed on `feat/agent-loop`). The static description in
    `backend/src/customs_agent/tools/query_entries.py` carries
    `{available_columns_entries_v}` and
    `{available_columns_entry_lines_v}` placeholder tokens.
    `agent/bootstrap.py:build_tool_definitions(con)` runs
    `information_schema.columns` against both views and substitutes the
    live column lists via
    `tools.__init__.format_query_entries_description(...)`. The
    Anthropic call uses the substituted definitions; the static
    placeholder is never sent. Do not hardcode the column list in the
    source — and never call the tool registration path without going
    through the bootstrap helper.
14. **Starlette `add_middleware` PREPENDS** — the LAST call wraps
    OUTERMOST (PR #9 Copilot Comment 1, fixed before merge).
    `Starlette.add_middleware()` does
    `self.user_middleware.insert(0, ...)` at
    `starlette/applications.py:101`. The intuitive read ("first added
    = outermost") is backwards. In `main.py`, add middlewares in
    INNER → OUTER order: `RequestIdMiddleware` first, then
    `SlowAPIMiddleware`, then `CORSMiddleware`, then
    `SecurityHeadersMiddleware` LAST so SEM ends up outermost. The
    misorder is silent — slowapi 429 responses + CORS preflight 200s
    short-circuit before reaching inner middleware, so SEM-as-inner
    means those responses ship without the 4 defensive headers. The
    `test_main_app_user_middleware_outermost_is_security_headers`
    integration test in
    `backend/tests/integration/test_security_headers.py` is the
    canary; any future refactor that re-introduces the bug fails here
    first.
15. **`AgentLoopSettings` must be built from `Settings` at lifespan**
    (PR #9 Copilot Comment 2, fixed before merge). The agent loop
    signature is `run_agent(ctx, user_message, history, request_id, *,
    settings=DEFAULT_LOOP_SETTINGS)`. Omitting the `settings=` kwarg
    makes the loop use HARDCODED defaults regardless of env
    overrides — `LLM_MODEL` / `AGENT_MAX_ITERATIONS` etc. silently
    no-op while `/ready` continues to advertise the env values
    (silent divergence). `main.py:lifespan` constructs an
    `AgentLoopSettings(model=settings.llm_model, ...)` from the live
    Settings, stashes on `app.state.loop_settings`, and
    `api/chat.py` forwards as `settings=app.state.loop_settings` to
    `run_agent`. The `test_chat_handler_forwards_loop_settings_to_run_agent`
    integration test spies the kwarg via monkeypatch and asserts
    object identity (not equality) so the canary survives a future
    refactor that constructs a fresh AgentLoopSettings per request.
16. **pydantic-settings does NOT auto-export to `os.environ`**
    (chunk 3c fix, surfaced during local smoke test). Reading `.env`
    populates the `Settings` model but leaves `os.environ` untouched.
    chromadb's `OpenAIEmbeddingFunction` reads `OPENAI_API_KEY` from
    `os.environ` directly at construction (chromadb 0.5+ raises
    `ValueError("CHROMA_OPENAI_API_KEY environment variable is not
    set")` on empty string), so a `.env`-only `OPENAI_API_KEY` makes
    `uvicorn` 500 at lifespan even when `Settings.openai_api_key` is
    correct. `main.py:lifespan` does
    `os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)`
    BEFORE constructing the retriever; `setdefault` respects existing
    values so production (Fly secrets sets env directly) is
    unaffected. Same pattern applies to any other third-party library
    that reads `os.environ` at construction without taking the key as
    a parameter.
17. **`secrets.compare_digest` requires ASCII-only `str` OR bytes**
    (PR #9 Copilot Comment 5, fixed before merge). Passing a
    non-ASCII `str` (e.g., `X-API-Key: tëst-key` containing umlauts)
    raises `TypeError` and propagates as a 500 instead of the
    documented 403 `invalid_api_key` response. `api/auth.py` encodes
    both args to UTF-8 bytes:
    `compare_digest(x_api_key.encode("utf-8"),
    settings.backend_api_key.encode("utf-8"))`. Bytes comparison
    preserves the constant-time semantics that are the whole point of
    `compare_digest` and trivially handles any header byte sequence.
    Never replace with `==` or remove the byte encoding.
18. **slowapi 0.1.9 reads `RATELIMIT_ENABLED` env var and silently
    OVERRIDES the constructor `enabled=` flag** at
    `slowapi/extension.py:234`:
    `self.enabled = self.get_app_config(C.ENABLED, self.enabled)`.
    The test suite's `tests/conftest.py` sets
    `RATELIMIT_ENABLED=false` for the whole suite (so the global
    limiter at `customs_agent.api._rate_limit.limiter` is no-op and
    most integration tests don't trip rate limits). Rate-limit
    integration tests need to construct their own `Limiter` with
    `enabled=True` — the fixture in
    `tests/integration/test_rate_limit.py:rate_limit_client` (and
    `headers_on_429_client` in `tests/integration/test_security_headers.py`)
    toggles `os.environ["RATELIMIT_ENABLED"] = "true"` around
    `Limiter()` construction and restores the prior value on
    teardown so other tests aren't polluted.
19. **`OPENAI_API_KEY` is a RUNTIME secret, not build-time-only**
    (`chore/dockerfile-fly`, surfaced on the first Fly deploy —
    contradicts the Fork 17/39 "build-time only" decision). Dense
    retrieval embeds **each user query** through OpenAI at request time
    (`rag/retriever.py` → chromadb's `OpenAIEmbeddingFunction` on the
    `query` path), so the running container needs the key — it isn't
    just baked into the image as embeddings. The first deploy
    crash-looped at lifespan with `chromadb ValueError:
    CHROMA_OPENAI_API_KEY environment variable is not set`; fixed by
    setting `OPENAI_API_KEY` as a Fly **runtime** secret (no code
    change — `main.py:lifespan` already mirrors it to `os.environ` per
    Gotcha #16). The same key is therefore needed in THREE places:
    Fly runtime secrets, `deploy.yml` (Docker build secret), AND
    `ci.yml`'s backend job (RAG-index build, Gotcha #22).
    `backend/.env.example` comments reflect the build-time + runtime
    duality.
20. **Dockerfile builder MUST set `ENV UV_PYTHON_DOWNLOADS=0`**
    (`chore/dockerfile-fly`; diverges from the
    `context/07-infrastructure.md` Dockerfile snippet, which omits it).
    uv defaults to `python-preference = managed` — it prefers a
    uv-DOWNLOADED interpreter. The runtime stage copies **only**
    `/app/.venv` from the builder, so if uv built the venv against a
    managed interpreter, the venv's `bin/python` symlink points at a
    Python that isn't in the final image → the container crash-loops on
    boot. Pinning `UV_PYTHON_DOWNLOADS=0` forces the system Python
    (present in `python:3.12-slim`) so the copied venv stays valid. The
    official uv Docker guide does exactly this for the copy-the-venv
    multi-stage pattern. Never remove it.
21. **pnpm 11 needs Node ≥ 22.13, and reads build approvals from
    `pnpm-workspace.yaml`** (`feat/web-mvp` + `chore/ci-cd`). Two
    distinct pnpm-11 landmines: (a) pnpm 11.1.3 uses the `node:sqlite`
    builtin (added in Node 22), so on Node 20 every `pnpm` invocation
    dies with `ERR_UNKNOWN_BUILTIN_MODULE: node:sqlite` — CI's
    `setup-node` MUST use `node-version: "22"` (matches
    `.tool-versions`). (b) pnpm 10+/11 blocks dependency lifecycle
    scripts by default; the `package.json` `pnpm.onlyBuiltDependencies`
    field is **no longer read** (pnpm warns and ignores it) — approvals
    live in `frontend/pnpm-workspace.yaml` under `allowBuilds:` (we
    approve `sharp` + `unrs-resolver`, both prebuilt-binary deps Next
    pulls in). Without this, `pnpm install --frozen-lockfile` (and even
    `pnpm <script>` via the `verify-deps-before-run` hook) fails with
    `ERR_PNPM_IGNORED_BUILDS`.
22. **CI's backend job must build the RAG index before pytest**
    (`chore/ci-cd`). The integration suite's session-scoped `client`
    fixture boots the full FastAPI app via lifespan, which calls
    `HybridRetriever.from_artifacts()` reading `chroma_db/` +
    `bm25.pkl`. Those are **gitignored** (baked at Docker build), so a
    fresh CI checkout doesn't have them → every integration test ERRORs
    with `chromadb NotFoundError: Collection [knowledge] does not
    exist`. `ci.yml`'s `backend` job runs `scripts/build_index.py`
    (with `OPENAI_API_KEY`, Gotcha #19) AFTER ruff/mypy and BEFORE
    pytest, mirroring `eval.yml`. Consequence: the backend CI job is
    NOT secret-free — it needs `OPENAI_API_KEY` set as a repo secret.
23. **`deploy.yml` must pass `backend` as the working-directory arg**,
    and `setup-flyctl` pins to `@v1` not `@v1.5` (`chore/ci-cd` + 2
    post-merge hotfixes). Two `flyctl` landmines, both only observable
    after a push to `main` (deploy.yml fires nowhere else): (a) Fly
    resolves the Dockerfile relative to the **build-context /
    working-directory**, NOT the `--config` path — so `flyctl deploy
    --config backend/fly.toml` from the repo root looks for
    `./Dockerfile` at root and fails `app does not have a Dockerfile or
    buildpacks configured`. Use `flyctl deploy backend --config
    fly.toml` (pass `backend` as the workdir arg), replicating the
    manual `cd backend && fly deploy`. (b) `superfly/flyctl-actions`
    has irregular tags — the GitHub release *titled* "v1.5" points to a
    tag literally named `1.5`; there is **no `v1.5` ref**. `v1` is the
    maintained major-version tag. Pin `setup-flyctl@v1`. Also: the
    `/ready` smoke test must NOT use `curl -f` under `set -e` (it would
    abort before the status check and treat a transient rollout 503 as
    a hard failure) — use a retry loop capturing the HTTP code with
    `curl -s`.
24. **The dataset CSV must stay `*.csv binary` with its original CRLF
    bytes** (`feat/remaining-tools-and-eval`, surfaced when the eval
    suite first ran in CI). `ground_truth.json`'s `dataset_sha256` is
    pinned to the CSV's byte-exact content. The CSV was first committed
    under `.gitattributes`'s `* text=auto` (BEFORE the later `*.csv
    binary` line), so its **blob was LF-normalized** while the local
    working tree kept its CRLF endings — the SHA was generated against
    the CRLF working-tree bytes (`1d6df8…`). A fresh CI checkout got the
    LF blob (`b9626d…`), so the Fork-43 drift guard ERRORed all 16 eval
    cases before any LLM call (~17s). Fix: `git add --renormalize
    backend/data/customs_entries_oct2024_mar2025.csv` so the blob honors
    `*.csv binary` and stores the CRLF bytes the pin targets — no
    `ground_truth.json` change (the data is byte-identical; only the
    line-ending representation was being pinned). Never let the CSV be
    text-normalized; the SHA pin assumes byte-exact storage. Cross-refs
    Gotcha #9.
25. **Fork-28 citation assembly is complete** (`feat/remaining-tools-and-eval`,
    "Option A"). `agent/loop.py:_build_citations` builds
    `knowledge_citations[]` from real history = RAG-retrieved chunks ∪
    each invoked tool's declared `ToolResult.citations` ∪
    `lookup_knowledge`'s returned chunks, deduped by `chunk_id` with
    sequential IDs sharing the `[N]` space with `tool_calls`. Before this
    branch the loop used RAG retrieval ONLY, so every tool's
    `citations=[...]` was dead code and the always-on rules/quirks/metrics
    (which the step-2 dedup removes from retrieval) never surfaced — they
    now do, via the owning tool's declaration (e.g., `quirk_1` via
    `total_duty_breakdown`). The always-on dedup of RAG retrieval is
    unchanged; only tool-declared + lookup citations are added. Citation
    CONTENT stays backend-authored (the split-authorship anti-hallucination
    property is intact). The remaining Fork-28 half — announcing the
    available `[N]` ids to the LLM in `tool_result` content — is deferred
    to `feat/citations-panel` (Day 5). Updates Gotcha #4.
26. **Eval grader: ground-truth Decimals are JSON strings + `line_count`
    is grain-sensitive** (`feat/remaining-tools-and-eval`, both surfaced
    on the first real eval run and now guarded by
    `tests/unit/eval/test_grading.py` regression tests). (a)
    `ground_truth.json` serializes `Decimal` money as JSON strings
    (`"59949493.45"`) while tools return real `Decimal`s — the grader
    compares them NUMERICALLY via the tolerance loop, NEVER string-equality;
    `_check_scalar` only string-matches a field when the ACTUAL value is
    itself a `str` (true labels like port code / status), so Decimal money
    is never spuriously failed (this masked correct answers for Q2/Q4/Q5).
    (b) `count_lines` (`COUNT(*)`) is the true tariff-line count ONLY on
    `entry_lines_v` — on `entries_v` it counts entries — so an agent can
    legitimately emit a misleading `line_count` on an entries_v call
    alongside the correct one (Q11); `_extract_scalar(...,
    prefer_view="entry_lines_v")` reads the grain-correct value regardless
    of call order. The eval record + `REPORT.md` now capture each tool
    call (name / view / args / result) so failures are self-diagnosing.

---

## `context/` Index

Load **only** the file(s) matching the current task. Each file is the
authoritative source for its scope; cross-references are by name, not
content duplication.

| File | When to load |
|---|---|
| [`context/00-decisions-index.md`](context/00-decisions-index.md) | Quick lookup: "what did we decide about Fork N / G-item M?" — always check here first for a one-line outcome |
| [`context/01-architecture.md`](context/01-architecture.md) | System overview, data flow, layering, request lifecycle, Mermaid diagrams |
| [`context/02-data-layer.md`](context/02-data-layer.md) | DuckDB load, typed schema, views (`entries_v` / `entry_lines_v`), shell filter, ground-truth fixture |
| [`context/03-rag-layer.md`](context/03-rag-layer.md) | Section-header chunking, ChromaDB, BM25, hybrid retrieval (RRF), always-on context, build-time indexing |
| [`context/04-agent-and-tools.md`](context/04-agent-and-tools.md) | 8-tool surface, Pydantic filters, agent loop, refusal routing, output sidecar, system prompt, injection defense, SQL safety |
| [`context/05-api-and-backend.md`](context/05-api-and-backend.md) | FastAPI app, endpoints (`/chat`, `/chat/stream`, etc.), middleware stack, health/ready |
| [`context/06-frontend.md`](context/06-frontend.md) | Next.js App Router, chat UI, citation pills, show-work panel, streaming consumer, localStorage, error handling, PROMPT_VERSION drift badge |
| [`context/07-infrastructure.md`](context/07-infrastructure.md) | Monorepo, Fly + Vercel deploy, Dockerfile, secrets routing, Makefile, setup.sh, local dev |
| [`context/08-cicd-and-testing.md`](context/08-cicd-and-testing.md) | GitHub Actions workflows, 3-layer test pyramid, eval grading, PR + rebase-merge flow, VS Code Source Control instructions |
| [`context/09-security.md`](context/09-security.md) | Threat model, 8-control inventory, per-control implementation detail, production roadmap |
| [`context/10-observability.md`](context/10-observability.md) | structlog JSON, Langfuse SDK, log schema, retention, pricing constants, cost tracking |
| [`context/11-deliverables.md`](context/11-deliverables.md) | README structure, EVALUATION.md format (G5), recruiter-topic mappings (Azure / Graphite), future-work organization (G26) |

---

## Decision Lock Summary

All 58 planning forks + 26 gap-scrutiny G-items are resolved. The plan is
fully locked. See [`context/00-decisions-index.md`](context/00-decisions-index.md)
for the authoritative outcome lookup.

**Two G-items explicitly skipped**: G16 (custom domain) and G21 (overall
accessibility audit) — both deliberately out of scope for the demo.

**Recruiter-topic documentation hooks** (Azure Container Apps mapping +
Graphite stacked-PRs workflow notes) are pinned to the Day 7 README pass —
see [`context/11-deliverables.md`](context/11-deliverables.md).

---

## When in Doubt

- **Tool calls Claude must never make**: any `git *`, any `gh *`,
  `make eval-md`, any deploy command, any history-rewriting operation.
- **Decision authority**: if a question arises that's not covered by the
  locked plan, **ask the user before proceeding**. Do not improvise on
  architectural decisions.
- **Pause on data-shape or spec-drift discoveries**: when investigating
  an unexpected condition reveals a real design decision (data
  semantics, spec drift, anything that mutates data or changes a
  documented invariant), **stop and present the options to the user
  for confirmation BEFORE implementing a fix**. Do not unilaterally
  pick the "obviously right" solution — the user may have context
  Claude doesn't (downstream tool design, customer constraints, data
  fidelity preferences). The Section 301 / IEEPA NULL-vs-`0.00`
  discovery during `feat/data-layer` is the worked example.
- **File modification**: prefer `Edit` for targeted changes; use `Write` only
  for new files or complete rewrites.
- **Verification before commit**: after any significant change, suggest the
  user run `make ci-local` to confirm lint + typecheck + tests pass before
  committing.
- **Stuck on conflicting context**: when two `context/` files seem to
  disagree, the **authoritative file** is the one whose scope matches the
  decision (see the Index table above). The other file should reference the
  authoritative one rather than duplicate the fact.
