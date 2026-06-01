# Customs Analytics Agent — Frontend

Next.js (App Router) chat UI for the Customs Analytics Agent. Browser traffic
reaches the FastAPI backend through a same-origin server-side proxy
(`/api/chat`) that injects the backend API key — the key never reaches the
browser.

## Quickstart

Workflows run through the root `Makefile` (run `make help` from the repo root):

```bash
make install-frontend   # pnpm install --frozen-lockfile
make dev-frontend       # Next.js dev server on http://localhost:3000
```

Copy `.env.example` to `.env.local` (or run `./scripts/setup.sh` from the repo
root) and fill in the values. See `.env.example` for the variable contract.

Package manager: **pnpm** (see the `packageManager` field in `package.json`).
