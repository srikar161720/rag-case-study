# Infrastructure

Authoritative source for repository layout, region pinning, Fly machine
configuration, secrets routing, the multi-stage Dockerfile, environment
promotion strategy, the canonical `Makefile`, the first-time setup
script, version pinning via `.tool-versions`, package-manager choices
(`uv` for backend, `pnpm` for frontend), local development parity, and
manual deploy rollback procedures.

Load this file when working on `Makefile`, `scripts/setup.sh`,
`backend/Dockerfile`, `backend/fly.toml`, `frontend/vercel.json`, or
any deployment / package-management concern. The CI/CD workflow
mechanics (GitHub Actions workflows, PR + rebase-merge process) live in
`08-cicd-and-testing.md`.

---

## Repository Structure (Fork 35)

Monorepo at the existing repo root. `data/` and `knowledge/` are
**moved into `backend/`** (per Fork 35's final choice — completed as
part of `chore/scaffold-monorepo`):

```
interview-case-study/                       ← repo root
├── .git/
├── .gitignore                              ← Python + Node + generated artifacts
├── .gitattributes                          ← marks api-types.ts as linguist-generated
├── .tool-versions                          ← Python 3.12, Node 20, pnpm 9 (for mise/asdf)
├── .dockerignore                           ← scoped to backend/ — see Dockerfile section
├── README.md                               ← Day 7 deliverable
├── CASE_STUDY.md                           ← provided brief
├── CLAUDE.md                               ← session-start backbone
├── PROGRESS.md                             ← phase checklist + session log
├── EVALUATION.md                           ← Day 7 deliverable (regen via scripts/generate_evaluation_md.py)
├── Makefile                                ← canonical workflow entry point
├── openapi.json                            ← G3 — generated from backend, committed
├── scripts/
│   └── setup.sh                            ← G6 — interactive first-time setup
├── .github/workflows/
│   ├── ci.yml                              ← lint + typecheck + tests + api-contract
│   ├── eval.yml                            ← real-LLM eval (path-triggered + nightly)
│   └── deploy.yml                          ← Fly deploy on push to main + /ready smoke test
├── context/                                ← 12 context files (load on demand)
│   └── 00-decisions-index.md (+ 01-11)
├── backend/
│   ├── data/                               ← CSV (moved from root)
│   │   └── customs_entries_oct2024_mar2025.csv
│   ├── knowledge/                          ← 4 KB text files (moved from root)
│   ├── pyproject.toml                      ← uv-managed; canonical deps + tool config
│   ├── uv.lock                             ← uv lockfile, committed
│   ├── Dockerfile                          ← multi-stage with uv + BuildKit secrets
│   ├── .dockerignore                       ← lives here (build context = backend/)
│   ├── fly.toml                            ← iad region, shared-cpu-1x 1GB always-on
│   ├── .env.example                        ← backend secret contract
│   ├── README.md                           ← quickstart + Makefile pointer + troubleshooting
│   ├── src/
│   │   └── customs_agent/                  ← src-layout Python package
│   │       ├── __init__.py
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── agent/
│   │       ├── api/
│   │       ├── data/
│   │       ├── observability/
│   │       ├── rag/
│   │       └── tools/
│   ├── prompts/                            ← 7 system prompt section files (Fork 27)
│   ├── scripts/
│   │   ├── build_index.py                  ← Fork 17 — build-time RAG indexing
│   │   ├── export_openapi.py               ← G3 — dump openapi.json
│   │   └── generate_evaluation_md.py       ← G5 — EVALUATION.md regenerator
│   └── tests/
│       ├── conftest.py
│       ├── _assertions.py
│       ├── ground_truth.py                 ← Fork 43
│       ├── ground_truth.json               ← committed fixture
│       ├── unit/ integration/ eval/        ← Fork 45 three-layer pyramid
└── frontend/
    ├── package.json                        ← packageManager: pnpm@9.x.x; engines.node >= 20
    ├── pnpm-lock.yaml
    ├── next.config.mjs
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── postcss.config.mjs
    ├── vitest.config.ts                    ← G2 — Vitest unit tests
    ├── vercel.json                         ← regions: ["iad1"]
    ├── .env.example                        ← frontend secret contract (server-side only)
    ├── README.md
    ├── public/
    │   ├── favicon.ico                     ← G22 — USER-PROVIDED
    │   └── og-image.png                    ← G22 — USER-PROVIDED
    └── src/
        ├── app/
        ├── components/
        └── lib/
```

### Why move `data/` and `knowledge/` into `backend/`

These are **backend concerns** — only the backend reads them. Putting
them at the repo root suggested shared ownership that doesn't exist.
Moving them inside `backend/` makes:

- **Standard Docker idiom**: `cd backend && docker build .` just works
  (build context = `backend/`); no `--file` flag, no parent-context
  awkwardness.
- **Simpler `.dockerignore`**: lives in `backend/`, doesn't need to
  exclude `frontend/`.
- **Simpler `fly.toml`**: no `dockerfile = "backend/Dockerfile"` path-
  prefix needed; Fly defaults to `./Dockerfile` from the config's
  directory.
- **Honest separation of concerns**: `data/` and `knowledge/` are
  inputs to the agent, sitting next to the source that consumes them.

The case study's described ZIP layout has them at root — that
description is informational, not prescriptive. README's one-line
mention closes the discoverability concern: *"Provided dataset and
knowledge documents live under `backend/data/` and `backend/knowledge/`."*

---

## Region Pinning (Fork 36)

**Single-region, US East**: Fly `iad` (Ashburn) + Vercel `iad1`
(Ashburn server functions).

### Why `iad`

- **Lowest latency to Anthropic primary endpoint**. Anthropic serves
  the main US public API from AWS `us-east-1`; co-locating Fly there
  gives ~20-50ms RTT instead of 80-150ms from `ord` or `lax`.
- **Co-located with Vercel default `iad1`**. The Next.js server-side
  proxy (Fork 29) → Fly backend hop stays in-metro: ~<20ms.
- **Acceptable for US East / Central reviewers**, mildly worse for
  West Coast (~60-70ms transcontinental). The inverse (`lax` for an
  East Coast reviewer) is worse because reviewer-side + LLM-side
  latencies stack additively.

### `vercel.json`

```json
{
  "regions": ["iad1"]
}
```

`iad1` is already Vercel's default for most accounts, but pinning
explicitly:

1. Prevents accidental drift to a different region
2. Documents the intent for reviewers
3. Makes the recruiter-topic mapping to Azure (Day 7 README) easier:
   "this would be East US 2 in Azure Container Apps"

### Multi-region (future work)

For production traffic with global reach: `fly scale count 3
--region iad,ams,nrt` (US East, EU West, Asia East). Document the cost
implications (~3× Fly bill) and request-routing strategy (Fly's
anycast handles geo-routing automatically). Not pursued for the demo;
recruiter-topic Azure section in the README mentions the equivalent
Container Apps multi-region strategy.

---

## Fly Machine Configuration (Fork 37)

Single `shared-cpu-1x` 1GB machine, always-on (`auto_stop_machines =
false`), with burst-scaling enabled (`auto_start_machines = true`).
~$5/month. **No scale-to-zero.**

### Why always-on

Cold-start cost for Python + DuckDB + ChromaDB load + Anthropic SDK
initialization is ~10-25 seconds. A reviewer clicking the demo URL and
waiting 15s is a brutal first impression. ~$5/month is functionally
free for a 2-4 week demo window; scale-to-zero saves coffee money at
unacceptable UX cost.

### Memory sanity check

| Component | RSS estimate |
|---|---|
| Python interpreter | ~50 MB |
| FastAPI + uvicorn | ~30 MB |
| DuckDB + 4,574 loaded rows + views | ~40-60 MB |
| ChromaDB persistent client + 30 chunks | ~50 MB |
| BM25 pickled index | ~5 MB |
| Anthropic SDK + httpx + structlog + Langfuse | ~50 MB |
| Pydantic + other deps | ~30 MB |
| **Baseline RSS** | **~255-275 MB** |
| Per-concurrent-request working memory | ~50-80 MB |
| Python GC overhead headroom | ~50-100 MB |
| **Comfortable working ceiling** | **~500-700 MB** |

1 GB gives ~30% buffer. 512 MB would risk OOM-kill mid-streaming-Q9
under any concurrency.

### `backend/fly.toml`

```toml
app = "customs-agent-backend"
primary_region = "iad"

[build]
# Dockerfile auto-detected at ./Dockerfile relative to this file

[env]
PORT = "8080"
ENVIRONMENT = "production"

[http_service]
internal_port    = 8080
force_https      = true
auto_stop_machines  = false       # always-on per Fork 37
auto_start_machines = true        # allow burst scale-up
min_machines_running = 1
processes        = ["app"]

[http_service.concurrency]
type       = "requests"
soft_limit = 50                   # autoscale-up threshold
hard_limit = 100                  # request rejection threshold

[[vm]]
size   = "shared-cpu-1x"
memory = "1gb"

[[http_service.checks]]
grace_period = "30s"
interval     = "30s"
method       = "GET"
timeout      = "5s"
path         = "/health"
```

### Operational cost

| Item | Monthly cost (USD) |
|---|---|
| 1 × `shared-cpu-1x` 1GB always-on in `iad` | ~$5.70 |
| Outbound bandwidth (~5 GB/mo demo traffic) | ~$0.10 |
| Volumes / persistent disk | $0 (image-baked artifacts only) |
| **Total** | **~$5.80/month** |

Plus Langfuse Cloud (free tier sufficient per Fork 53), Anthropic /
OpenAI API usage (~$3-5/month per Fork 44 + 55), Vercel (free tier),
GitHub Actions (free for public repos). **Total project cost: ~$10-15
for the entire interview window.**

---

## Secrets Routing (Fork 39)

Platform-native secret stores; no centralized secrets manager. Every
secret lives in exactly the platforms that need it.

### The full audit table

| Secret | Local (`.env`) | Fly Secrets (backend runtime) | Vercel Env (frontend server-side) | GitHub Actions Secrets (build + CI) |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | ✅ | — | ✅ (eval workflow) |
| `OPENAI_API_KEY` | ✅ | — (build-time only per Fork 17) | — | ✅ (Docker BuildKit secret) |
| `BACKEND_API_KEY` | ✅ both `.env` files | ✅ (validates) | ✅ (injects via server route) | — |
| `LANGFUSE_PUBLIC_KEY` | ✅ | ✅ | — | ✅ (eval traces) |
| `LANGFUSE_SECRET_KEY` | ✅ | ✅ | — | ✅ |
| `LANGFUSE_HOST` | ✅ | ✅ | — | ✅ |
| `ALLOWED_ORIGINS` | ✅ | ✅ | — | — |
| `BACKEND_URL` | ✅ `frontend/.env.local` | — | ✅ | — |
| `FLY_API_TOKEN` | — | — | — | ✅ (deploy workflow) |

### Key isolation rules

1. **LLM provider keys (Anthropic, OpenAI, Langfuse) stay on backend.**
   Frontend never holds them; if Vercel is ever compromised, the LLM
   bill is not on the table.
2. **`BACKEND_API_KEY` lives in two places by necessity**: backend
   validates (Fly Secret), Next.js server route injects (Vercel Env).
   **Frontend client-side never sees it** — never `NEXT_PUBLIC_*`.
3. **`OPENAI_API_KEY` is build-time only** thanks to Fork 17 (Docker
   bakes embeddings into the image). The runtime Fly container never
   has it. Smaller credential surface.
4. **`FLY_API_TOKEN` lives only in GitHub Actions Secrets**, never
   anywhere else.

### Generating `BACKEND_API_KEY`

```bash
openssl rand -base64 32
```

32 bytes of CSPRNG randomness → 44-char base64 string. The same value
goes into both Fly Secrets and Vercel Env. Documented in
`backend/.env.example` as a comment.

### Setting Fly secrets (one-time, per env)

```bash
fly secrets set \
  ANTHROPIC_API_KEY="..." \
  BACKEND_API_KEY="..." \
  ALLOWED_ORIGINS="https://customs-agent.vercel.app,^https://customs-agent-[a-z0-9]+-[a-z0-9-]+\.vercel\.app$" \
  LANGFUSE_PUBLIC_KEY="..." \
  LANGFUSE_SECRET_KEY="..." \
  LANGFUSE_HOST="https://cloud.langfuse.com" \
  --app customs-agent-backend
```

Each `fly secrets set` triggers a redeploy (intentional — secret
changes propagate immediately).

### Setting Vercel env vars

Via dashboard (Project Settings → Environment Variables) or CLI:

```bash
echo "https://customs-agent-backend.fly.dev" | vercel env add BACKEND_URL production
echo "<key>" | vercel env add BACKEND_API_KEY production
# Repeat for Preview scope with same values (so PR previews work)
```

Make sure variables are NOT prefixed `NEXT_PUBLIC_` (that would bundle
them into the client JavaScript).

### Setting GitHub Actions Secrets

Via repo Settings → Secrets and variables → Actions, or `gh` CLI:

```bash
gh secret set ANTHROPIC_API_KEY  -b "<key>"
gh secret set OPENAI_API_KEY     -b "<key>"
gh secret set FLY_API_TOKEN      -b "<token from `flyctl auth token`>"
gh secret set LANGFUSE_PUBLIC_KEY -b "<key>"
gh secret set LANGFUSE_SECRET_KEY -b "<key>"
```

### `gitleaks` pre-commit / CI scan (Fork 39 freebie)

The CI workflow includes a gitleaks step that catches accidental secret
commits. ~10 lines of YAML; mentioned in detail in
`08-cicd-and-testing.md`.

### Rotation schedule (documented; manual)

| Secret | Cadence | Process |
|---|---|---|
| `BACKEND_API_KEY` | Semi-annually | Generate new; `fly secrets set …`; update Vercel env; redeploy both |
| `ANTHROPIC_API_KEY` | Quarterly or on suspected leak | Rotate in Anthropic Console; update Fly Secrets + GHA Secrets |
| `OPENAI_API_KEY` | Quarterly | Rotate in OpenAI dashboard; update GHA Secrets only (build-time) |
| `LANGFUSE_*` | As needed | Rotate in Langfuse dashboard; update Fly + GHA |
| `FLY_API_TOKEN` | Annually or on team change | `flyctl auth tokens create`; update GHA |

---

## Dockerfile (Fork 41)

Multi-stage with `uv` (10-100× faster than pip) + BuildKit cache + secret
mounts. Non-root runtime user. `python:3.12-slim` base. ~310 MB final
image.

### Why multi-stage

| Reason | Detail |
|---|---|
| Build tools (uv, headers) stay in builder stage | Smaller runtime image (~30 MB savings) |
| Layer cache reuses dep-install when source changes | 10× faster CI iteration after first build |
| BuildKit secret mount for OpenAI key | Never lands in any image layer (Fork 39) |
| Non-root user in runtime | Standard security hardening |

### Full Dockerfile

```dockerfile
# syntax=docker/dockerfile:1.7
# backend/Dockerfile — multi-stage Python build for the Customs Analytics Agent.
# Build context: backend/ (per Fork 35 — data/ and knowledge/ live inside backend/)

# ============================================================================
# Stage 1: Builder — install Python deps + build RAG index (Fork 17)
# ============================================================================
FROM python:3.12-slim AS builder

# Install uv (10-100x faster than pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install deps first — this layer caches when pyproject.toml/uv.lock unchanged
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Copy source and resources
COPY src/      ./src/
COPY scripts/  ./scripts/
COPY prompts/  ./prompts/
COPY data/     ./data/
COPY knowledge/ ./knowledge/

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Build the RAG index (Fork 17) — OpenAI key via BuildKit secret, NEVER in layers
RUN --mount=type=secret,id=openai_key \
    OPENAI_API_KEY=$(cat /run/secrets/openai_key) \
    .venv/bin/python scripts/build_index.py \
        --out-chroma /app/chroma_db \
        --out-bm25 /app/bm25.pkl \
        --out-manifest /app/manifest.json

# ============================================================================
# Stage 2: Runtime — minimal final image
# ============================================================================
FROM python:3.12-slim AS runtime

# Non-root user
RUN useradd --create-home --uid 1000 --shell /bin/bash app

WORKDIR /app

# Copy venv + built RAG artifacts from builder
COPY --from=builder --chown=app:app /app/.venv         /app/.venv
COPY --from=builder --chown=app:app /app/chroma_db     /app/chroma_db
COPY --from=builder --chown=app:app /app/bm25.pkl      /app/bm25.pkl
COPY --from=builder --chown=app:app /app/manifest.json /app/manifest.json
COPY --from=builder --chown=app:app /app/data          /app/data
COPY --from=builder --chown=app:app /app/knowledge     /app/knowledge

# Copy source + prompts (small late layers; change frequently in dev)
COPY --chown=app:app src/     /app/src/
COPY --chown=app:app prompts/ /app/prompts/

# OCI labels (traceability for production registries)
LABEL org.opencontainers.image.source="https://github.com/<user>/interview-case-study" \
      org.opencontainers.image.description="Customs analytics conversational agent" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

USER app

EXPOSE 8080

# HEALTHCHECK mirrors /health endpoint for local docker ps visibility
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; \
                   sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health',timeout=3).status==200 else 1)" \
    || exit 1

CMD ["uvicorn", "customs_agent.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### `.dockerignore` (lives in `backend/`)

```dockerignore
# Python caches
__pycache__/
**/__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# Build artifacts — regenerated inside Docker, must not leak from local dev
chroma_db/
bm25.pkl
manifest.json
.venv/
dist/
build/
*.egg-info/

# Tests not needed in runtime image
tests/

# Env / secrets
.env
.env.*
!.env.example

# IDE / OS
.idea/
.vscode/
.DS_Store
Thumbs.db
*.swp
```

Critical: the `chroma_db/`, `bm25.pkl`, and `manifest.json` exclusions
prevent stale local development artifacts from overriding the freshly
built ones during `docker build`.

### Image-size budget (~310 MB final)

| Layer | Approx size |
|---|---|
| `python:3.12-slim` base | ~50 MB |
| `.venv/` (FastAPI, DuckDB, ChromaDB, Anthropic SDK, etc.) | ~245 MB |
| `chroma_db/` (30 chunks × 1536-dim float32 + sqlite overhead) | ~5 MB |
| `bm25.pkl` | ~2 MB |
| `data/` (CSV) | ~1.5 MB |
| `knowledge/` (4 text files) | <50 KB |
| `src/` + `prompts/` | ~2 MB |
| `manifest.json` | <1 KB |
| **Total** | **~305-315 MB** |

Pulls in 10-15s on a fresh Fly machine.

### Local build invocation

```bash
# From backend/ directory
cd backend
docker build --secret id=openai_key,env=OPENAI_API_KEY -t customs-agent:local .

# Run locally to verify
docker run --rm -p 8080:8080 \
  --env-file .env \
  customs-agent:local
```

Or via Makefile target (G6): `make build` runs the above from any
directory.

### Apple Silicon → Fly platform note

Fly runs `linux/amd64`. If building on Apple Silicon, use
`docker build --platform linux/amd64 ...` to match production exactly.
The Makefile `build` target includes `--platform linux/amd64` for this
reason.

---

## Environment Promotion (Fork 42)

Three environments, two real deployment targets:

| Environment | Frontend | Backend | Trigger |
|---|---|---|---|
| **Production** | `customs-agent.vercel.app` | `customs-agent-backend.fly.dev` | Rebase-merge to `main` |
| **Preview** (per PR) | `customs-agent-<hash>-<user>.vercel.app` | shares production Fly backend | Every PR push (Vercel git integration) |
| **Development** | `http://localhost:3000` | `http://localhost:8080` | Local `make dev-*` |

### Vercel handles previews automatically

The Vercel GitHub integration spins up a preview deployment per PR
push. No CI step required. Each preview gets a unique URL; CORS
allowlist regex (Fork 38) admits the pattern. Per-PR Fly backend
previews are **future work** (Fork 42 future) — for the demo, all
preview frontends point at the production Fly backend.

### Cross-cutting consequence: merge backend first

When a PR changes both backend and frontend in incompatible ways:

1. Merge the backend change first (production deploys; new API surface
   becomes live)
2. Then merge the frontend change (Vercel preview now sees the new
   backend; production frontend updates)

For frontend-only or backend-only changes, order doesn't matter.
Document this in CONTRIBUTING.md or the README's "How to work on this"
section.

### CI workflow surfaces

| Workflow | Trigger | Outcome |
|---|---|---|
| `ci.yml` | Every PR + push to main | Lint, typecheck, unit + integration tests, `api-contract` drift check, secret scan |
| `eval.yml` | Path-triggered (agent/RAG/data changes) + nightly + manual + label-based | Real-LLM eval against ground truth (Fork 44) |
| `deploy.yml` | Push to `main` (post-merge) | Build + push Fly image; deploy; smoke-test `/ready` |

Details in `08-cicd-and-testing.md`.

---

## Makefile (G6) — Canonical Workflow Entry

The root `Makefile` is **the canonical interface** for every workflow.
`make help` self-documents. Most-used commands documented in
`CLAUDE.md`'s session-startup section; full reference here.

```makefile
# Makefile — root entry point for the Customs Analytics Agent
# Run `make help` for available targets.

.DEFAULT_GOAL := help

##@ Setup
.PHONY: install install-backend install-frontend setup
install: install-backend install-frontend ## Install all dependencies
install-backend: ## Install backend deps via uv
	cd backend && uv sync --frozen
install-frontend: ## Install frontend deps via pnpm
	cd frontend && pnpm install --frozen-lockfile
setup: ## Run interactive first-time setup script
	./scripts/setup.sh

##@ Development
.PHONY: dev-backend dev-frontend
dev-backend: ## Start FastAPI with autoreload on :8080
	cd backend && uv run uvicorn customs_agent.main:app --reload --port 8080
dev-frontend: ## Start Next.js with HMR on :3000
	cd frontend && pnpm dev

##@ Testing
.PHONY: test test-backend test-frontend eval
test: test-backend test-frontend ## Run unit + integration tests (no LLM cost)
test-backend: ## Backend unit + integration tests
	cd backend && uv run pytest tests/unit tests/integration -v
test-frontend: ## Frontend Vitest tests
	cd frontend && pnpm test --run
eval: ## Real-LLM eval suite (requires API keys + BACKEND_URL)
	cd backend && uv run pytest tests/eval -v

##@ Code Generation
.PHONY: ground-truth openapi types types-frontend eval-md
ground-truth: ## Regenerate backend/tests/ground_truth.json
	cd backend && uv run python -m tests.ground_truth
openapi: ## Export backend OpenAPI to ../openapi.json (G3)
	cd backend && uv run python -m scripts.export_openapi > ../openapi.json
types-frontend: ## Generate frontend TS types from openapi.json
	cd frontend && pnpm gen:types
types: openapi types-frontend ## Regenerate OpenAPI + frontend TS types (G3)
eval-md: ## USER-INVOKED ONLY — regenerate EVALUATION.md (G5)
	cd backend && uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md

##@ Build
.PHONY: build
build: ## Build the backend Docker image locally
	cd backend && docker build \
		--platform linux/amd64 \
		--secret id=openai_key,env=OPENAI_API_KEY \
		-t customs-agent:local .

##@ Quality
.PHONY: lint lint-backend lint-frontend typecheck typecheck-backend typecheck-frontend ci-local
lint: lint-backend lint-frontend ## Run all linters
lint-backend: ## Backend lint (ruff)
	cd backend && uv run ruff check .
lint-frontend: ## Frontend lint (eslint)
	cd frontend && pnpm lint
typecheck: typecheck-backend typecheck-frontend ## Run all typecheckers
typecheck-backend: ## Backend typecheck (mypy)
	cd backend && uv run mypy src
typecheck-frontend: ## Frontend typecheck (tsc)
	cd frontend && pnpm typecheck
ci-local: lint typecheck test ## Same checks CI runs on PR (run before pushing)

##@ Cleanup
.PHONY: clean
clean: ## Remove all build artifacts (.venv, node_modules, generated indexes)
	rm -rf backend/.venv backend/chroma_db backend/bm25.pkl backend/manifest.json
	rm -rf frontend/node_modules frontend/.next

##@ Help
.PHONY: help
help: ## Display this help
	@awk 'BEGIN {FS = ":.*##"; \
	  printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	  /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' \
	  $(MAKEFILE_LIST)
```

**Claude must NEVER run `make eval-md`** — it overwrites a committed
deliverable (G5). User-invoked only.

---

## `scripts/setup.sh` (G6) — Interactive First-Time Setup

```bash
#!/usr/bin/env bash
# scripts/setup.sh — interactive first-time setup
# Idempotent: safe to re-run; only creates files that don't exist.

set -euo pipefail
cd "$(dirname "$0")/.."   # run from repo root

cat <<'BANNER'

  Customs Analytics Agent — First-Time Setup
  ============================================

BANNER

# 1. Check required tools
check() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "❌ $1 not installed. $2"
    exit 1
  fi
  echo "✓ $1 available"
}

echo "→ Checking prerequisites..."
check uv     "See https://docs.astral.sh/uv/getting-started/installation/"
check pnpm   "Run: npm install -g pnpm  (or via corepack)"
check node   "See https://nodejs.org/ (requires v20+)"
check python "See https://www.python.org/ (requires 3.12+)"
command -v docker >/dev/null 2>&1 \
  && echo "✓ docker available" \
  || echo "⚠ docker not installed — required for 'make build' (Fly remote-builds otherwise)"

# 2. Backend .env
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  KEY=$(openssl rand -base64 32)
  sed -i.bak "s|BACKEND_API_KEY=.*|BACKEND_API_KEY=$KEY|" backend/.env && rm backend/.env.bak
  echo "✓ Created backend/.env with auto-generated BACKEND_API_KEY"
else
  echo "✓ backend/.env already exists (not overwriting)"
fi

# 3. Frontend .env.local — sync BACKEND_API_KEY with backend
if [ ! -f frontend/.env.local ]; then
  cp frontend/.env.example frontend/.env.local
  BACKEND_KEY=$(grep '^BACKEND_API_KEY=' backend/.env | cut -d= -f2-)
  sed -i.bak "s|BACKEND_API_KEY=.*|BACKEND_API_KEY=$BACKEND_KEY|" frontend/.env.local && rm frontend/.env.local.bak
  echo "✓ Created frontend/.env.local (BACKEND_API_KEY synced with backend)"
else
  echo "✓ frontend/.env.local already exists (not overwriting)"
fi

# 4. Install dependencies
echo ""
echo "→ Installing dependencies..."
make install

# 5. Done — print next steps
cat <<'NEXT'

✓ Setup complete!

Next steps:
  1. Edit backend/.env to add:
       ANTHROPIC_API_KEY      (https://console.anthropic.com/)
       OPENAI_API_KEY         (https://platform.openai.com/ — embeddings + eval judge)
       LANGFUSE_PUBLIC_KEY    (https://cloud.langfuse.com/, optional)
       LANGFUSE_SECRET_KEY    (https://cloud.langfuse.com/, optional)

  2. (Optional) Regenerate ground-truth fixture:
       make ground-truth

  3. (Optional) Sync OpenAPI types:
       make types

  4. Run the app (two terminals):
       Terminal 1:  make dev-backend
       Terminal 2:  make dev-frontend

  5. Open http://localhost:3000

For all available commands, run:  make help
NEXT
```

Cross-platform: `sed -i.bak ... && rm *.bak` works on both BSD/macOS
and GNU/Linux `sed`. Idempotent re-runs: skip `.env` files that
already exist; don't overwrite user customizations.

---

## `.tool-versions` (G6)

For users of `mise` or `asdf`:

```
python 3.12.7
nodejs 20.18.0
pnpm 9.12.0
```

Three-line file. Users not using these tools simply ignore it. Zero
downside for anyone; one less manual setup step for mise/asdf users.

---

## Package Managers

### Backend: `uv` (Fork 41 + G12)

**`uv` everywhere, no exceptions.** No `pip`, no `pip-tools`, no
`poetry`. The Dockerfile bootstraps `uv` from GHCR (no `pip install
uv` even for the bootstrap).

| Operation | Command |
|---|---|
| Lockfile (committed) | `uv.lock` |
| Manifest (authoritative) | `pyproject.toml` |
| Install in dev / CI | `uv sync --frozen` |
| Add a dependency | `uv add <pkg>` |
| Add a dev dependency | `uv add --dev <pkg>` |
| Run anything | `uv run <cmd>` (replaces `python -m`, `pytest`, etc.) |
| Lockfile drift check | `uv lock --check` (CI step) |
| Export for non-uv environments | `uv export --format requirements-txt --frozen` (future-work, e.g., Azure migration) |

`uv lock --check` runs in `ci.yml` to prevent `pyproject.toml` ↔
`uv.lock` drift.

### `pyproject.toml` (sketch — full version lands during build)

```toml
[project]
name = "customs-agent"
version = "0.1.0"
description = "Customs analytics conversational agent"
requires-python = ">=3.12"
dependencies = [
    "fastapi >= 0.115",
    "uvicorn[standard] >= 0.30",
    "pydantic >= 2.9",
    "pydantic-settings >= 2.5",
    "duckdb >= 1.1",
    "chromadb >= 0.5",
    "rank-bm25 >= 0.2",
    "anthropic >= 0.40",
    "openai >= 1.50",
    "langfuse >= 2.50",
    "structlog >= 24.0",
    "slowapi >= 0.1.9",
    "httpx >= 0.27",
]

[dependency-groups]
dev = [
    "pytest >= 8.3",
    "pytest-asyncio >= 0.24",
    "ruff >= 0.7",
    "mypy >= 1.13",
    "openapi-typescript >= 7.4",     # for G3 codegen — Node tool, but listed here for visibility
]

[tool.ruff]
line-length = 100
[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF"]

[tool.mypy]
strict = true
python_version = "3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers --tb=short"
markers = [
    "unit: pure-function tests, no LLM (fast)",
    "integration: agent loop with mocked LLM (fast)",
    "eval: end-to-end with real LLM (slow, costs money)",
]
```

### Frontend: `pnpm` 9.x (G13)

**`pnpm` 9.x pinned via `packageManager` field + Corepack.** No `npm`,
no `yarn`.

| Operation | Command |
|---|---|
| Lockfile (committed) | `pnpm-lock.yaml` |
| Manifest | `frontend/package.json` |
| Install in dev | `pnpm install` |
| Install in CI | `pnpm install --frozen-lockfile` |
| Add a dep | `pnpm add <pkg>` |
| Add a dev dep | `pnpm add --save-dev <pkg>` |
| Run a script | `pnpm <script>` |

### `frontend/package.json` (sketch — full version lands during build)

```json
{
  "name": "customs-agent-frontend",
  "version": "0.1.0",
  "private": true,
  "packageManager": "pnpm@9.12.0",
  "engines": { "node": ">=20" },
  "scripts": {
    "dev":            "next dev",
    "build":          "next build",
    "start":          "next start",
    "lint":           "next lint",
    "typecheck":      "tsc --noEmit",
    "test":           "vitest --run",
    "test:watch":     "vitest",
    "gen:types":      "openapi-typescript ../openapi.json -o src/lib/api-types.ts",
    "gen:types:check": "openapi-typescript ../openapi.json -o /tmp/api-types-check.ts && diff src/lib/api-types.ts /tmp/api-types-check.ts"
  },
  "dependencies": {
    "next":             "^15.0",
    "react":            "^19.0",
    "react-dom":        "^19.0",
    "tailwindcss":      "^3.4",
    "react-markdown":   "^9.0",
    "remark-gfm":       "^4.0",
    "swr":              "^2.2",
    "lucide-react":     "^0.460"
  },
  "devDependencies": {
    "typescript":       "^5.6",
    "@types/react":     "^19.0",
    "@types/node":      "^22.0",
    "openapi-typescript": "^7.4",
    "vitest":           "^2.1",
    "@vitejs/plugin-react": "^4.3",
    "@vitest/coverage-v8": "^2.1",
    "jsdom":            "^25.0"
  }
}
```

Plus shadcn/ui components copied into `src/components/ui/` (no runtime
dep).

---

## Local Development Parity (G18)

Two paths supported; document both in `backend/README.md`.

### Primary path — fast iteration

```bash
make dev-backend         # uvicorn with --reload, ~sub-second restart on save
make dev-frontend        # Next.js with HMR
```

Use this for day-to-day development. Saves ~10× iteration time vs
Docker.

### Pre-push verification — production parity

```bash
make build               # Multi-stage Docker build with BuildKit secret
docker run --rm -p 8080:8080 --env-file backend/.env customs-agent:local
```

Use this once before pushing to verify the deployed image actually
boots and `/ready` returns 200. Catches "works on my machine, doesn't
work on Fly" surprises.

### Why two paths

Docker matches Fly exactly but has slow iteration (~30s rebuild on
source change). `uv run uvicorn --reload` iterates in ~500ms. For
most work, the speed dominates; for pre-push, the parity dominates.

---

## Manual Rollback (G17)

When `/ready` smoke test fails post-deploy, or when a production issue
is identified, rollback is **manual** — no auto-rollback machinery for
this demo.

### Backend (Fly)

```bash
# List recent releases
flyctl releases --app customs-agent-backend

# Roll back to a specific release
flyctl releases rollback <release_id> --app customs-agent-backend

# Or roll back to the previous release
flyctl deploy --image registry.fly.io/customs-agent-backend:<prior-tag> --app customs-agent-backend
```

Documented in `backend/README.md` under "Troubleshooting → Deploy issues".

### Frontend (Vercel)

1. Open the Vercel project dashboard
2. Deployments → select the prior-good deployment
3. Click the "..." menu → "Promote to Production"

Or via CLI:

```bash
vercel rollback <deployment-url> --token <token>
```

### After rollback

1. Open a GitHub Issue documenting what failed (`/ready` smoke test
   output, error logs from `fly logs`, repro steps)
2. Branch from `main` to fix the issue: `fix/<short-description>`
3. Standard PR → CI → merge flow (per Fork 58 + G4) applies the fix
4. The rolled-back version stays in production until the fix merges

---

## Composition with Other Layers

- **`02-data-layer.md`** — CSV at `backend/data/` baked into Docker
  image via Fork 41 builder stage.
- **`03-rag-layer.md`** — knowledge files at `backend/knowledge/` +
  embeddings built at Docker build via Fork 17.
- **`05-api-and-backend.md`** — FastAPI app served by uvicorn (the
  Dockerfile entrypoint); `/health` polled by Fly check; `/ready`
  smoke-tested in `deploy.yml`.
- **`06-frontend.md`** — `vercel.json` pins `iad1`; `BACKEND_URL` env
  var points at the Fly URL; per-PR previews via Vercel git
  integration.
- **`08-cicd-and-testing.md`** — GitHub Actions workflows (ci.yml,
  eval.yml, deploy.yml) consume secrets from the audit table here;
  rebase-merge workflow per G4.
- **`09-security.md`** — `.dockerignore` + non-root user + BuildKit
  secret mounts are the infrastructure-level security controls;
  detailed in the security context file.
- **`10-observability.md`** — `fly logs --tail` is the primary
  inspection tool for stdout JSON; Langfuse credentials wired here.

---

## Future Work

| Item | Trigger |
|---|---|
| Per-PR Fly preview apps (Fork 42 option c) | When team size > 1 or backend changes need preview-deploy testing |
| Multi-region Fly (`fly scale count 3 --region iad,ams,nrt`) | When global latency becomes a real concern |
| Auto-rollback GitHub Actions step on smoke-test failure (G17 follow-on) | Production-grade reliability |
| Branch protection on `main` (requires public repo OR GitHub Pro for private) | When repo is private and team scales up |
| Docker Compose for local dev (backend + Redis + Postgres) | When multi-machine state becomes part of the architecture |
| Dev Container `.devcontainer/` configuration | For cloud-IDE / VS Code Codespaces onboarding |
| Pre-commit hooks (lint + typecheck + secret scan) | When team velocity warrants per-commit gates |
| `direnv` for auto-loading `.env` | Personal convenience; not project policy |
| `act` for running GitHub Actions locally | When CI feedback latency becomes the bottleneck |
| Managed secrets manager (Doppler / Infisical / AWS Secrets Manager) | When secret rotation needs automation + audit log |
| Build-time codegen for Pydantic Literal enums from DB (G21 future) | When the project scales and enum drift becomes a regression risk |
| `uv export --format requirements-txt` artifact for Azure Container Apps migration | If the recruiter-topic Azure path is ever pursued |
| Multi-arch Docker builds (linux/arm64 in addition to linux/amd64) | When target deployment platforms diversify |
| Fly log drain to S3/R2 for retention > 5 days | Production audit / compliance |
