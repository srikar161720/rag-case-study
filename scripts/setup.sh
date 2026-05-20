#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# scripts/setup.sh — Customs Analytics Agent first-time setup
#
# Idempotent: safe to re-run; only creates files that don't already exist
# and skips steps whose inputs (.env.example / pyproject.toml / package.json)
# haven't landed yet on the current branch.
#
# Cross-platform: sed inline edit uses the BSD/GNU-compatible `sed -i.bak`
# pattern, then `rm *.bak` cleans up.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Run from repo root regardless of where the script is invoked
cd "$(dirname "$0")/.."

# ANSI color helpers
if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
    RED=$'\033[31m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi

step()   { printf "\n${BOLD}→ %s${RESET}\n" "$1"; }
ok()     { printf "  ${GREEN}✓${RESET} %s\n" "$1"; }
info()   { printf "  ${CYAN}ℹ${RESET} %s\n" "$1"; }
warn()   { printf "  ${YELLOW}⚠${RESET} %s\n" "$1"; }
fail()   { printf "  ${RED}✗${RESET} %s\n" "$1" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
cat <<'BANNER'

  ╔═══════════════════════════════════════════════════════════════╗
  ║   Customs Analytics Agent  —  First-Time Setup                ║
  ║   Pedestal AI take-home                                       ║
  ╚═══════════════════════════════════════════════════════════════╝

BANNER

# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — required tool checks
# ─────────────────────────────────────────────────────────────────────────────
step "Checking required tools"

check_required() {
    local name="$1" install_hint="$2"
    if command -v "$name" >/dev/null 2>&1; then
        ok "$name found ($(command -v "$name"))"
    else
        fail "$name not found. $install_hint"
    fi
}

check_optional() {
    local name="$1" install_hint="$2"
    if command -v "$name" >/dev/null 2>&1; then
        ok "$name found ($(command -v "$name"))"
    else
        warn "$name not found — optional. $install_hint"
    fi
}

check_required "uv"     "Install: https://docs.astral.sh/uv/getting-started/installation/"
check_required "pnpm"   "Install: corepack enable && corepack prepare pnpm@latest --activate"
check_required "node"   "Install: https://nodejs.org/  (requires Node 20+)"
check_required "python" "Install: https://www.python.org/  (uv can also install Python 3.12 itself: uv python install 3.12)"
check_optional "docker" "Needed for 'make build'. Fly.io can also remote-build."
check_optional "flyctl" "Install: https://fly.io/docs/flyctl/install/  (needed for 'fly deploy')"

# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — backend/.env scaffolding (guarded; skips before Day 3)
# ─────────────────────────────────────────────────────────────────────────────
step "Backend environment file"

if [ -f backend/.env ]; then
    ok "backend/.env already exists (not overwriting)"
elif [ ! -f backend/.env.example ]; then
    info "Skipping — backend/.env.example doesn't exist on this branch yet"
    info "  (lands on feat/fastapi-backend, Day 3)"
else
    cp backend/.env.example backend/.env
    # openssl produces base64 of 32 bytes (44 chars; A-Z a-z 0-9 + / =).
    # Command substitution strips the trailing newline. The `|` sed delimiter
    # is safe for base64 since `|` isn't in the base64 alphabet.
    GENERATED_KEY=$(openssl rand -base64 32)
    sed -i.bak "s|^BACKEND_API_KEY=.*|BACKEND_API_KEY=${GENERATED_KEY}|" backend/.env
    rm -f backend/.env.bak
    ok "Created backend/.env with auto-generated BACKEND_API_KEY"
    info "Add ANTHROPIC_API_KEY + OPENAI_API_KEY + LANGFUSE_* (optional) before running the agent"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — frontend/.env.local scaffolding (guarded; skips before Day 3)
# ─────────────────────────────────────────────────────────────────────────────
step "Frontend environment file"

if [ -f frontend/.env.local ]; then
    ok "frontend/.env.local already exists (not overwriting)"
elif [ ! -f frontend/.env.example ]; then
    info "Skipping — frontend/.env.example doesn't exist on this branch yet"
    info "  (lands on feat/web-mvp, Day 3)"
else
    cp frontend/.env.example frontend/.env.local
    if [ -f backend/.env ]; then
        BACKEND_KEY=$(grep '^BACKEND_API_KEY=' backend/.env | cut -d'=' -f2-)
        sed -i.bak "s|^BACKEND_API_KEY=.*|BACKEND_API_KEY=${BACKEND_KEY}|" frontend/.env.local
        rm -f frontend/.env.local.bak
        ok "Created frontend/.env.local (BACKEND_API_KEY synced with backend)"
    else
        warn "Created frontend/.env.local but couldn't sync BACKEND_API_KEY (backend/.env missing)"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — install dependencies (guarded; runs only if manifests exist)
# ─────────────────────────────────────────────────────────────────────────────
step "Installing dependencies"

if [ -f backend/pyproject.toml ] || [ -f frontend/package.json ]; then
    info "Running 'make install' (first run may take a few minutes)"
    if [ -f backend/pyproject.toml ]; then
        ( cd backend && uv sync --frozen ) && ok "backend deps installed"
    else
        info "Skipping backend install — backend/pyproject.toml not on this branch yet"
    fi
    if [ -f frontend/package.json ]; then
        ( cd frontend && pnpm install --frozen-lockfile ) && ok "frontend deps installed"
    else
        info "Skipping frontend install — frontend/package.json not on this branch yet"
    fi
else
    info "Skipping 'make install' — neither dependency manifest exists yet"
    info "  (backend/pyproject.toml lands on feat/data-layer; frontend/package.json lands on feat/web-mvp)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — next steps
# ─────────────────────────────────────────────────────────────────────────────
step "Setup complete"

cat <<'NEXTSTEPS'

  Next steps:

    1. Add provider API keys to backend/.env:
         ANTHROPIC_API_KEY      https://console.anthropic.com/
         OPENAI_API_KEY         https://platform.openai.com/   (embeddings + eval judge)
         LANGFUSE_PUBLIC_KEY    https://cloud.langfuse.com/    (optional)
         LANGFUSE_SECRET_KEY    https://cloud.langfuse.com/    (optional)

    2. (Optional) Regenerate the ground-truth fixture from the dataset:
         make ground-truth

    3. (Optional) Sync OpenAPI types between backend and frontend:
         make types

    4. Run the app (two terminals):
         Terminal 1:  make dev-backend     # FastAPI on http://localhost:8080
         Terminal 2:  make dev-frontend    # Next.js  on http://localhost:3000

    5. Open http://localhost:3000

  For all available commands:  make help

NEXTSTEPS
