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

Body (when warranted) explains the **why**, not the **what** (the diff is
the what). Wrap body lines at 72 chars.

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
interview-case-study/
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
│   ├── eval.yml                    ← real-LLM eval (path-triggered + nightly + manual)
│   └── deploy.yml                  ← Fly deploy on merge to main
├── context/                        ← granular spec files (load on demand)
│   └── [12 files; see index below]
├── backend/                        ← Python + FastAPI
│   ├── data/                       ← synthetic CSV dataset (moved from root)
│   ├── knowledge/                  ← 4 knowledge text files (moved from root)
│   ├── src/customs_agent/          ← src-layout package
│   ├── prompts/                    ← system-prompt section files (Fork 27)
│   ├── scripts/
│   │   ├── build_index.py          ← build-time RAG indexing (Fork 17)
│   │   ├── export_openapi.py       ← OpenAPI snapshot generator (G3)
│   │   └── generate_evaluation_md.py  ← EVALUATION.md regenerator (G5)
│   ├── tests/
│   │   ├── ground_truth.py + ground_truth.json    ← canonical answer key (Fork 43)
│   │   └── unit/, integration/, eval/             ← 3-layer pyramid (Fork 45)
│   ├── pyproject.toml + uv.lock    ← uv-managed Python deps
│   ├── Dockerfile + .dockerignore  ← multi-stage build (Fork 41)
│   ├── fly.toml                    ← Fly.io deploy config (Forks 36, 37)
│   └── .env.example                ← backend secrets contract (Fork 39)
└── frontend/                       ← Next.js App Router on Vercel
    ├── src/app/                    ← App Router routes + server-side proxy
    ├── src/components/             ← UI primitives (shadcn/ui + custom)
    ├── src/lib/                    ← api, sse, storage, citations, errors, types
    ├── public/                     ← favicon.ico + og-image.png (user-provided)
    ├── package.json + pnpm-lock.yaml  ← pnpm 9.x managed
    ├── vercel.json                 ← region pin (iad1)
    └── .env.example                ← frontend secrets contract (Fork 39)
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
| Frontend package manager | `pnpm` 9.x via `packageManager` field + Corepack | Fork 35, G13 |

---

## Critical Gotchas

These are the landmines that will silently corrupt accuracy or behavior if
forgotten. Every session must remember them.

1. **MPF cap per entry** ($31.67 minimum, $614.35 maximum). Never sum
   line-level MPF without applying the cap at entry grain. Encoded in
   `entries_v.total_mpf_capped` (Fork 19). Tools use this, not the raw sum.
2. **Section 301 only on CN-origin lines**: `section_301_duty` is `NULL` for
   non-CN lines (Fork 18). Use `COALESCE(SUM(...), 0)` to handle the NULL.
3. **IEEPA only on Release Date ≥ 2025-02-01**: `ieepa_duty` is `NULL` for
   earlier entries (Fork 18). Same COALESCE pattern.
4. **Citation marker integrity**: the LLM writes `[N]` markers in prose; the
   backend builds the citations array from real retrieval and tool-call
   history (Fork 28). Orphan markers (referencing a non-existent N) must be
   stripped server-side before returning to the client.
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
   intentionally when `prompts/*` changes; otherwise leave it alone.
9. **Dataset SHA-256 pin**: `ground_truth.json` carries the SHA of the CSV it
   was generated against; eval tests fail fast on drift (Fork 43).
10. **No raw SQL surface**: the agent has 8 typed tools (Fork 22). There is
    no `execute_sql(query)` tool. Parameterized `?` placeholders for values
    + Pydantic-enforced column-name allowlists for `group_by` / `aggregations`
    / `order_by` (Fork 50).

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
- **File modification**: prefer `Edit` for targeted changes; use `Write` only
  for new files or complete rewrites.
- **Verification before commit**: after any significant change, suggest the
  user run `make ci-local` to confirm lint + typecheck + tests pass before
  committing.
- **Stuck on conflicting context**: when two `context/` files seem to
  disagree, the **authoritative file** is the one whose scope matches the
  decision (see the Index table above). The other file should reference the
  authoritative one rather than duplicate the fact.
