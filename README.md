# Customs Analytics Agent

> **The Oracle Problem: Building a Conversational Agent That Actually Knows Things.**
> Take-home engineering project for **Pedestal AI**.

A conversational Q&A agent over U.S. customs entry data, grounded in a domain
knowledge layer. The agent answers questions about duties, fees, holds, customer
performance, and tariff impacts using a synthetic dataset of ~4,500 customs
entries and four hand-curated knowledge documents.

> The full project brief lives in [`CASE_STUDY.md`](CASE_STUDY.md).

---

## Provided dataset

The synthetic dataset and domain knowledge files live under the `backend/`
directory:

- [`backend/data/customs_entries_oct2024_mar2025.csv`](backend/data/customs_entries_oct2024_mar2025.csv) — ~4,500 customs entries (Oct 2024 – Mar 2025)
- [`backend/knowledge/`](backend/knowledge/) — 4 text files:
  - `customs_core_concepts.txt`
  - `data_dictionary.txt`
  - `duties_fees_tariffs.txt`
  - `customer_profiles_qbr_metrics.txt`

---

## Documentation

| Document | Purpose |
|---|---|
| [`CASE_STUDY.md`](CASE_STUDY.md) | The take-home brief — requirements and evaluation criteria |
| [`CLAUDE.md`](CLAUDE.md) | Session-start protocol, hard workflow rules, repo layout |
| [`PROGRESS.md`](PROGRESS.md) | Phase checklist and session log (the source of truth for build status) |
| [`context/`](context/) | 12 granular spec files (architecture, data, RAG, agent, API, frontend, infra, CI/CD, security, observability, deliverables) |
| `EVALUATION.md` | Static evaluation snapshot (regenerated on Day 7 via `make eval-md`) |

---

## Prerequisites

- **Python 3.12** — `uv` will install it independently of your system Python
- **Node.js ≥ 20** — current LTS recommended (22.x works)
- **pnpm ≥ 9** — pinned per-project via Corepack
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Docker** — optional, only needed for `make build` (Fly.io can remote-build instead)
- **[flyctl](https://fly.io/docs/flyctl/install/)** — optional, only needed to deploy from your machine

`.tool-versions` documents the project's exact pins for `mise` / `asdf` users.

---

## Quick start

```bash
# 1. One-time interactive setup (tool checks, .env scaffolding, dependency install)
./scripts/setup.sh

# 2. Run the app in two terminals
make dev-backend     # FastAPI on http://localhost:8080
make dev-frontend    # Next.js  on http://localhost:3000

# 3. Open the chat UI
open http://localhost:3000
```

---

## Workflow entry point

The root [`Makefile`](Makefile) is the canonical entry point for every common
operation. Run `make help` for the full list:

```bash
make help
```

Common targets:

| Target | What it does |
|---|---|
| `make install` | Install all dependencies (uv + pnpm) |
| `make dev-backend` / `make dev-frontend` | Local development servers |
| `make test` | Unit + integration tests (no LLM cost) |
| `make eval` | Real-LLM eval suite (requires API keys, consumes credits) |
| `make types` | Regenerate `openapi.json` + frontend TS types |
| `make ci-local` | Same checks CI runs on PR — run before pushing |

---

## Repository layout

```
.
├── backend/           Python + FastAPI (uv-managed)
│   ├── data/          Synthetic customs dataset (CSV)
│   ├── knowledge/     Domain knowledge text files
│   ├── src/           Python package (src-layout)
│   ├── prompts/       System-prompt section files
│   ├── scripts/       Build-time scripts (RAG indexing, OpenAPI export)
│   └── tests/         Unit / integration / eval (3-layer pyramid)
├── frontend/          Next.js App Router + Tailwind + shadcn/ui (pnpm-managed)
├── context/           Granular spec files (architecture, security, etc.)
├── scripts/           Repo-level scripts (setup.sh)
├── .github/workflows/ CI / Eval / Deploy workflows
└── Makefile           Canonical workflow entry point
```

See [`CLAUDE.md`](CLAUDE.md) for the full repo-layout reference.

---

## License & contact

License — TBD.
Contact — TBD.
