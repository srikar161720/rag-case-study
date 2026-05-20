# ─────────────────────────────────────────────────────────────────────────────
# Customs Analytics Agent — root Makefile
#
# Canonical workflow entry point. Run `make help` for the full target list.
# Every target either delegates into backend/ (uv) or frontend/ (pnpm).
#
# Conventions:
#   - Targets self-document via the trailing `## description` comment.
#   - .PHONY declared once at the top.
#   - `make eval-md` is USER-INVOKED ONLY (overwrites EVALUATION.md, a
#     committed deliverable). Never run automatically.
# ─────────────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help

.PHONY: help install install-backend install-frontend setup \
        dev-backend dev-frontend \
        test test-backend test-frontend eval \
        ground-truth openapi types-frontend types eval-md \
        build \
        lint lint-backend lint-frontend \
        typecheck typecheck-backend typecheck-frontend \
        ci-local clean

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

install: install-backend install-frontend ## Install all deps (uv backend + pnpm frontend)

install-backend: ## Install backend Python deps via uv
	cd backend && uv sync --frozen

install-frontend: ## Install frontend deps via pnpm
	cd frontend && pnpm install --frozen-lockfile

setup: ## Interactive first-time setup (tool checks, .env scaffolding, install)
	./scripts/setup.sh

# ─────────────────────────────────────────────────────────────────────────────
# Development
# ─────────────────────────────────────────────────────────────────────────────

dev-backend: ## Start FastAPI on :8080 with autoreload
	cd backend && uv run uvicorn customs_agent.main:app --reload --port 8080

dev-frontend: ## Start Next.js on :3000 with HMR
	cd frontend && pnpm dev

# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

test: test-backend test-frontend ## Run unit + integration tests (no real LLM cost)

test-backend: ## Backend unit + integration tests
	cd backend && uv run pytest tests/unit tests/integration -v

test-frontend: ## Frontend Vitest tests
	cd frontend && pnpm test --run

eval: ## Real-LLM eval suite (requires API keys; consumes credits)
	cd backend && uv run pytest tests/eval -v

# ─────────────────────────────────────────────────────────────────────────────
# Code generation
# ─────────────────────────────────────────────────────────────────────────────

ground-truth: ## Regenerate backend/tests/ground_truth.json from SQL
	cd backend && uv run python -m tests.ground_truth

openapi: ## Export backend OpenAPI snapshot to openapi.json (G3)
	cd backend && uv run python -m scripts.export_openapi > ../openapi.json

types-frontend: ## Regenerate frontend TS types from openapi.json
	cd frontend && pnpm gen:types

types: openapi types-frontend ## Regenerate OpenAPI snapshot + frontend TS types

eval-md: ## ⚠ USER-INVOKED ONLY — regenerate EVALUATION.md (G5)
	@echo "⚠  Regenerating EVALUATION.md — this overwrites a committed deliverable."
	@echo "   Make sure the deployed backend is healthy before submitting."
	cd backend && uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md

# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────

build: ## Build the backend Docker image locally (linux/amd64)
	cd backend && docker build \
		--platform linux/amd64 \
		--secret id=openai_key,env=OPENAI_API_KEY \
		-t customs-agent:local .

# ─────────────────────────────────────────────────────────────────────────────
# Quality (lint + typecheck + composite ci-local)
# ─────────────────────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────

clean: ## Remove all build artifacts (.venv, node_modules, RAG index)
	rm -rf \
		backend/.venv \
		backend/chroma_db \
		backend/bm25.pkl \
		backend/manifest.json \
		frontend/node_modules \
		frontend/.next

# ─────────────────────────────────────────────────────────────────────────────
# Help (self-documenting; scans `## description` trailers on target lines)
# ─────────────────────────────────────────────────────────────────────────────

help: ## Display this help
	@printf "\n  \033[1mCustoms Analytics Agent — Makefile targets\033[0m\n\n"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@printf "\n  Run \033[36mmake <target>\033[0m to execute.\n\n"
