# Deliverables

Authoritative source for the Day 7 documentation pass: README
structure with all required + bonus sections; EVALUATION.md format
(per G5); recruiter-topic documentation hooks (Azure equivalents +
Graphite stacked-PR pattern); future-work organization by category
(G26); and the submission-readiness checklist.

Load this file when working on `README.md`, `EVALUATION.md`,
`backend/README.md`, `frontend/README.md`, or any documentation
author/polish task — primarily on the `docs/final-polish` branch in
Day 7 per Fork 57.

---

## Case Study Mandated Deliverables

Per `CASE_STUDY.md`, four deliverables are explicitly required:

1. **GitHub Repository** with all source, Dockerfile, GitHub Actions, docs
2. **Deployed Demo URL** (Vercel frontend + Fly backend per Fork 36)
3. **`README.md`** with:
   - Architecture overview with diagram
   - How the knowledge layer works (embedding strategy, retrieval approach, prompt design)
   - Infrastructure decisions (why Vercel/Fly.io, how CI/CD works)
   - Security considerations and what we implemented
   - Known limitations and what we'd improve with more time
4. **`EVALUATION.md`** with the 11 evaluation questions, agent's
   answers, and notes on any struggles

This file is the authoring spec for items 3 and 4.

---

## README Structure

The README is the single most important Communication-rubric (10%)
deliverable. Reviewers scan it first; everything else (code, EVALUATION,
deployed demo) follows from the README's framing.

### Structure (proposed section order)

```markdown
# Customs Analytics Agent

> Conversational Q&A agent over U.S. customs entry data, grounded in a
> domain knowledge layer. Take-home project for **Pedestal AI**.

[![Live demo](badge-url)](https://customs-agent.vercel.app)
[![CI](badge-url)](https://github.com/.../actions/workflows/ci.yml)
[![Eval](badge-url)](https://github.com/.../actions/workflows/eval.yml)

---

## 1. Demo

- **Live URL**: https://customs-agent.vercel.app
- **Backend health**: https://customs-agent-backend.fly.dev/ready (shows
  current `prompt_version` + `model` + manifest)

Try one of the starter chips on the empty state, or ask anything
about MHF / PCA / SAG customs entries over Oct 2024 – Mar 2025.

## 2. Quick start (local)

[Setup instructions: `./scripts/setup.sh`, `make dev-backend`,
 `make dev-frontend`. See `07-infrastructure.md` for full Makefile reference.]

## 3. Architecture

[Architecture diagram (Mermaid). See `01-architecture.md` for the
 full diagram source.]

Key design principles:
1. **Rules in code, not in prose** — tools encode business rules; LLM picks tools
2. **LLM owns narrative, backend owns facts** — citations built from real history
3. **Fail-secure by typing** — Pydantic Literal enums + parameterized SQL
4. **Deterministic where possible, defensive where not** — temperature 0 + sidecar assertions
5. **Observable by default** — every request gets a trace

## 4. How the knowledge layer works

[Brief narrative covering chunking (Fork 14), embedding (Fork 13),
 hybrid retrieval (Fork 16), always-on context (Fork 15), and prompt
 design (Fork 27). See `03-rag-layer.md` for full detail.]

## 5. Infrastructure decisions

[Vercel (`iad1`) + Fly (`iad`, shared-cpu-1x 1GB always-on) rationale
 (Forks 36, 37). Why Docker multi-stage with uv + BuildKit secrets
 (Fork 41). How CI/CD works (3 workflows per Fork 44).]

### How we'd ship this on the team (recruiter-topic notes)

[Azure Container Apps equivalent mapping; Graphite stacked-PR pattern
 as team-scale upgrade — see "Recruiter Topic Documentation Hooks"
 below.]

## 6. Security considerations

[Threat model + 8-control table (2 primary + 6 defense-in-depth, per
 G7 + Fork 51). See `09-security.md` for full detail.]

## 7. Testing strategy

[Three-layer pyramid (Fork 45): unit (no LLM) + integration (mocked
 LLM) + eval (real LLM). Frontend Vitest (G2). API contract drift
 check (G3). See `08-cicd-and-testing.md` for full detail.]

## 8. Observability

[Two-layer: structlog stdout JSON (Fly logs) + Langfuse Cloud agent
 traces (Forks 10, 52, 54). Cookbook with `fly logs | jq` + Langfuse
 filter recipes. See `10-observability.md`.]

## 9. Cost optimization

[Anthropic prompt caching (Fork 55) — ~7× cost reduction on eval
 suite. Measured cache hit rate from latest EVALUATION.md. Per-Q
 cost. Single-model decision (Fork 56). Total demo cost: ~$10-15/mo.]

## 10. Performance budgets

[Table from G14: FCP < 1.5s, TTFT < 2s p50, Tier 1 < 3s, Tier 3 < 6s,
 etc. Measured numbers from latest EVALUATION.md.]

## 11. Known limitations

[G15 browser support; G23 background SSE; trace-link 30-day expiration
 (Fork 53); shared-key auth model (Fork 48 demo posture); single-machine
 (no Redis-backed rate-limit storage); 0 shell entries in current data
 set (the include_shell filter is dead-code-in-this-data per Fork 20).]

## 12. Future work

[Category-grouped per G26 — see "Future Work Organization" below.]

## 13. Project journey (optional)

[One-paragraph build narrative referencing the 7-day phased plan
 (Fork 57). Optional but earns Communication points by showing
 deliberate scoping. See `PROGRESS.md` for the actual phase-by-phase
 record.]

---

## Repository layout

[Compressed tree from `CLAUDE.md` — full version is in CLAUDE.md.]

## License / Acknowledgements

[Optional — case study materials credit, etc.]
```

### Section authoring rules

- **One diagram, not five.** A single architecture Mermaid (system
  flow) is sufficient. A second sequence diagram for the agent loop
  is optional but worth doing if time permits (`01-architecture.md`
  has both planned).
- **Cross-reference, don't duplicate.** Each context file is the deep
  source; README is the public-facing summary. README links to the
  deployed `/ready` endpoint for the live manifest rather than
  duplicating numbers.
- **Measured numbers, not estimates.** Cost figures, cache hit rate,
  latency percentiles, eval pass rate — all sourced from the latest
  `EVALUATION.md`. Regenerate EVALUATION.md before submission so the
  README's numbers match.
- **Honest scoping.** "Known limitations" + "Future work" lists are
  not weaknesses — they're maturity signals. Reviewers actively look
  for these as evidence of deliberate engineering judgment.
- **No filler.** If a section has nothing project-specific to say,
  cut it. Generic best-practices paragraphs ("we follow SOLID
  principles") add zero signal.

---

## EVALUATION.md (G5)

**Static snapshot at submission time, regeneratable via
`make eval-md`.** Reviewers receive the file as-submitted; the
script lets the candidate regenerate against the live deployed
backend whenever agent behavior changes.

### Full template

```markdown
# EVALUATION.md

> **Snapshot generated**: 2026-MM-DDTHH:MM:SSZ
> **Last regenerated by**: `make eval-md` (runs
> `cd backend && uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md`)

This file is the canonical record of the agent's behavior at submission
time. The generator script is committed and reproducible.

---

## Run Metadata

| Field | Value |
|---|---|
| `PROMPT_VERSION` (Fork 27) | `1.0.0` |
| Main agent model | `claude-sonnet-4-6` |
| Eval judge model (Q9 rubric) | `gpt-4o-mini` |
| Embedding model | `text-embedding-3-small` |
| Temperature | `0` |
| Seed (OpenAI judge) | `42` |
| Dataset SHA-256 | `<sha…>` |
| Build manifest | [`backend/manifest.json`](backend/manifest.json) |
| Frontend deployed URL | https://customs-agent.vercel.app |
| Backend deployed URL | https://customs-agent-backend.fly.dev |

### Reproducibility

The agent is deterministic at temperature=0 (Fork 26). To regenerate
this file against the currently deployed backend:

```bash
cd backend
export ANTHROPIC_API_KEY=... BACKEND_API_KEY=... \
       BACKEND_URL=https://customs-agent-backend.fly.dev \
       LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=...
uv run python -m scripts.generate_evaluation_md > ../EVALUATION.md
```

### Trace-link freshness

Langfuse trace URLs in this file expire 30 days after generation
(free-tier retention, per Fork 53). The numeric answers, SQL excerpts,
filter args, citation chunk IDs, and judge rubric scores embedded here
provide **standalone verification** — they don't require Langfuse
access. Trace URLs are a convenience artifact; regenerate via the
command above for fresh links.

---

## Summary

| Metric | Value |
|---|---|
| Questions evaluated | 11/11 |
| **Correctness** passes (Fork 46) | 11 |
| **Architecture** passes (no warnings) | 11 |
| Correctness passes with architecture warning | 0 |
| Q9 rubric score | 4/4 |
| Total cost (Anthropic + judge) | $0.061 |
| Median question latency | 1.8s |
| p95 question latency | 3.2s |
| Cached input tokens % (across run) | 78% |

---

## Per-Question Results

| # | Tier | Question | Correctness | Architecture | Trace |
|---|------|----------|-------------|--------------|-------|
| 1 | T1 | PCA entries Jan 2025 | ✅ 142 (exp 142) | ✅ `query_entries` | [view](<langfuse-url>) |
| 2 | T1 | SAG entered value Q1 2025 | ✅ $X (within ±0.1%) | ✅ `query_entries` | [view](<...>) |
| 3 | T1 | Top port overall | ✅ 2704 (LA) | ✅ `query_entries` | [view](<...>) |
| 4 | T2 | Section 301 Dec 2024 | ✅ $X · CN-only cited | ✅ `total_duty_breakdown` | [view](<...>) |
| 5 | T2 | MHF/CN effective rate Q1 2025 | ✅ X% · formula cited | ✅ `effective_duty_rate` | [view](<...>) |
| 6 | T2 | Hold rate vs benchmark | ✅ status="warrants_investigation" | ✅ `hold_summary` | [view](<...>) |
| 7 | T3 | IEEPA % across customers | ✅ MHF highest (X%) | ✅ `compare_customers` | [view](<...>) |
| 8 | T3 | PCA top 5 HTS from CN | ✅ Set match · amounts ±0.1% | ✅ `top_hts_by_duty` | [view](<...>) |
| 9 | T3 | SAG Q1 2025 QBR | ✅ Rubric 4/4 | ✅ `qbr_summary` | [view](<...>) |
| 10 | T4 | Date field for January | ✅ "Release Date" + Rule 1 cited | ✅ `lookup_knowledge` | [view](<...>) |
| 11 | T4 | MHF entry vs line count Nov 2024 | ✅ Both correct + difference | ✅ 2× `query_entries` | [view](<...>) |

---

## Detailed Results

[For each Q, expand to show full answer prose, SQL excerpts, sidecar
 fields, latency, cost, trace link. Generator produces ~10-20 lines per
 Q. See `02-data-layer.md` for the SQL patterns; `04-agent-and-tools.md`
 for the sidecar shape; `08-cicd-and-testing.md` for the grading logic.]

### Q1 (Tier 1, ✅ PASS) — Pacific Coast Apparel entries in January 2025

**Expected** (from `tests/ground_truth.json`): `entry_count = 142`
**Actual**: 142 ✅ (exact — Tier 1 tolerance: `0`)

**Agent's answer**:
> Pacific Coast Apparel filed **142 customs entries** in January 2025 [1] [2].
>
> This count uses Release Date for the January filter [3] and excludes
> shell entries per Business Rule 5 [4] (0 shell entries present in this
> dataset).

**Architecture check**:
- Tool called: `query_entries` ✅
- Args: `{view: "entries_v", filters: {customer_code: "PCA", release_year_month: "2025-01"}, aggregations: ["count_distinct_entries"]}` ✅

**Citations**:
- `[3]` → `rule_1_date_filtering` ✅
- `[4]` → `rule_5_shell_entries`

**SQL executed**:
```sql
SELECT COUNT(*) AS entry_count FROM entries_v
WHERE customer_code = ? AND release_year_month = ? AND NOT is_shell
```
Parameters: `["PCA", "2025-01"]` · Rows inspected: 142 · Shell entries excluded: 0

**Performance**: 1.4s · 4521 in (3502 cached, 77%) · 320 out · est. $0.0118

**Trace**: [view in Langfuse](https://cloud.langfuse.com/trace/<id>) — expires 30 days post-generation

[...Q2 through Q11...]

---

## Self-Assessment

[Required by case study: "Note any questions where the agent struggled
 and explain why."]

The agent passed all 11 questions on the correctness axis with no
architecture warnings. Q9's rubric judge scored a full 4/4 — the QBR
prose explicitly included monthly volumes, full duty breakdown by
program, top sourcing countries, and the hold rate as a percentage.

### Where the agent could be stronger

[Per-question commentary on any warnings or partial passes; honest
 scoping notes about what would improve with more time. Pattern:
 problem → why → mitigation.]

### What we'd improve with more time

See the "Future work" section of the README for the full category-
grouped list (~30+ items).

---

## Build Journal (optional)

[Reverse-chronological summary of the 7-day phased plan (Fork 57) +
 PRs merged + key decisions. Sources from PROGRESS.md.]

The project was built across 7 days following the phased plan in Fork 57.
~20 PRs were merged to `main` via rebase-merge (per G4); each PR
contains 2-3 logical-chunk commits per Fork 58.

| Day | Phase | Branches merged | Cumulative commits |
|---|---|---|---|
| 1 | Foundation | `chore/scaffold-monorepo`, `feat/data-layer`, `test/ground-truth` | 6 |
| 2 | Agent core | `feat/rag-pipeline`, `feat/prompts-and-tools`, `feat/agent-loop`, `test/backend-units` | 16 |
| 3 | Deploy + MVP | `feat/fastapi-backend`, `chore/dockerfile-fly`, `feat/web-mvp`, `chore/ci-cd` | 28 |
| 4 | Accuracy hardening | `feat/remaining-tools-and-eval`, `feat/observability-base`, `feat/api-contract` | 35 |
| 5 | Bonuses | `feat/langfuse-traces`, `feat/citations-panel`, `feat/empty-state-chips`, `feat/security-hardening`, `feat/error-boundary` | 42 |
| 6 | Streaming + extras | `feat/streaming`, `feat/conversation-sidebar`, `feat/frontend-tests`, `chore/mobile-responsive` | 48 |
| 7 | Documentation | `docs/final-polish` | 54 |

Full commit history: `git log --oneline main`. All PRs in the GitHub repo's "Closed Pull Requests" tab.
```

### Generator script (Fork 43 + 46 + G5)

`backend/scripts/generate_evaluation_md.py` runs each question against
the configured `BACKEND_URL`, applies Fork 46 grading, runs the Q9
rubric judge, and emits Markdown matching the template above.
Implementation responsibilities are in `08-cicd-and-testing.md`.

> **As-built note (`feat/remaining-tools-and-eval`)**: the generator
> shipped this branch — it POSTs each question to the deployed `/chat`
> via `httpx`, reuses the eval suite's grader (`tests/eval/_grading.py`,
> incl. the Q9 judge), and per-question grading is wrapped so a judge /
> network hiccup can't lose the whole file. Its pure markdown-assembly
> functions are unit-tested (`tests/unit/eval/test_generate_evaluation_md.py`,
> no network). **`EVALUATION.md` itself is NOT generated yet** — by design
> it's a Day-7 / pre-submission snapshot (regenerated within ~24h of
> submission for trace-link freshness per Fork 53).

**Claude must NEVER run `make eval-md`** — the user invokes it
manually before submission (per G5). The generator emits to stdout;
the user redirects to `EVALUATION.md` and commits.

---

## Recruiter Topic Documentation Hooks

The recruiter flagged five topics. None of them change the plan or
the code — they're **interview-prep signals**. Documented as trade-off
awareness in the Day 7 README pass.

### Topic 1: Vercel deployments ✅ Fully implemented

Coverage:
- Fork 6 — Next.js App Router on Vercel
- Fork 36 — `iad1` server-function region pin
- Fork 38 — CORS allowlist regex for Vercel preview URLs
- Fork 39 — Vercel env vars for `BACKEND_URL` + `BACKEND_API_KEY`
- Fork 42 — Vercel git integration handles auto-previews per PR + main → Production

Placement: README "Infrastructure decisions" section.

### Topic 2: Fly.io ✅ Fully implemented

Coverage:
- Fork 36 — `iad` region
- Fork 37 — shared-cpu-1x 1GB always-on, autoscale on burst
- Fork 39 — Fly Secrets for backend runtime
- Fork 41 — multi-stage Dockerfile with `uv` + BuildKit secrets
- Fork 42 — `deploy.yml` GHA workflow + `/ready` smoke test

Placement: README "Infrastructure decisions" section.

### Topic 3: Azure Container App Jobs ❌ Not implemented — substituted by Fly.io

The case study allows "Vercel and Fly.io, **or an equivalent split**"
— we chose Fly. Azure Container Apps is the equivalent that wasn't
pursued.

**Important nuance**: "Container App **Jobs**" is specifically the
**batch / scheduled / event-driven** variant — distinct from
"Container Apps" (the always-on HTTP service variant). The always-on
HTTP equivalent for our backend would be **Container Apps**, not Jobs.
Document this distinction in the README.

Placement: README "Infrastructure decisions" → subsection "Azure
equivalent mapping". Include this mapping table:

| Our choice (Fly) | Azure equivalent | Why each works |
|---|---|---|
| Fly.io `shared-cpu-1x` 1GB always-on, `iad` | Azure Container Apps (Consumption plan, single revision, East US 2) | Both: container-native, auto-scale, HTTPS edge, regional |
| `flyctl deploy --remote-only` via GHA | `az containerapp up` or `azure/container-apps-deploy-action@v1` | Both: build + deploy from a Dockerfile; both via GitHub Actions |
| `fly secrets set` | `az containerapp secret set` + Key Vault references | Both: platform-native secret stores |
| `fly logs --tail` | `az containerapp logs tail` or Azure Log Analytics | Both: stdout JSON consumed by platform log infrastructure |
| `auto_stop_machines = false` | Container Apps `minReplicas: 1` (no scale-to-zero) | Both expose the same trade-off |
| Build-time RAG indexing inside Dockerfile (Fork 17) | Same — OR Azure Container App **Job** as a one-shot pre-deploy step | Jobs would be the Pedestal-native way to do build-time indexing |
| GitHub Actions deploy workflow (Fork 42) | Same workflow shape; swap `superfly/flyctl-actions` for `azure/login` + `azure/container-apps-deploy-action` | One-line provider swap |

Closing paragraph: *"Migration cost is roughly a one-line provider
swap in the GHA workflow plus rewriting `fly.toml` as an Azure Bicep
or Terraform file. The architectural choices (Docker, region pinning,
secrets routing, health endpoints, stdout JSON logs) all transfer."*

### Topic 4: GitHub integration with the above

Vercel + Fly + GHA integrations are all wired (Fork 39, 42, 44, G4).
Azure integration would be `azure/login` + `azure/container-apps-deploy-action`
in `deploy.yml` — documented as the migration path in the Azure mapping
above.

Placement: README "How CI/CD works" subsection.

### Topic 5: Graphite for code push and deployments ❌ Plain git + GitHub PRs

Our workflow uses plain `git` + GitHub PRs with rebase-merge (Fork 58 +
G4). Graphite ([graphite.dev](https://graphite.dev)) is a stacked-PR
tool — small dependent PRs that review independently while sharing
context. For team-scale production work, Graphite would naturally
extend our PR-per-Fork 57-phase workflow.

Placement: README "Infrastructure decisions" → subsection "How we'd
ship this on the team":

> *"For team production work, our PR-per-phase workflow extends to
> Graphite stacked PRs — small dependent PRs that review independently
> while sharing context (e.g., `01-data-layer` → `02-rag-pipeline` →
> `03-agent-loop`). Graphite's CLI manages the stack: rebases dependent
> PRs when an earlier one merges, prevents conflicts, surfaces
> dependencies in the GitHub UI. Worth introducing when (a) team size
> exceeds one, or (b) feature trains involve cohesive multi-PR changes
> that benefit from independent review. For a solo 7-day demo, plain
> GitHub PRs with rebase-merge cover the same workflow ground without
> the Graphite client install."*

---

## Future Work Organization (G26)

The accumulated future-work list across all 58 forks + 26 G-items is
50+ entries. Flat lists are unscannable. README's "Future Work" section
groups by **10 categories** matching Fork 58 commit scopes for
discoverability:

```markdown
## Future Work

### Security
- OAuth / SSO / per-user auth (Fork 48)
- API key rotation with overlap support (Fork 39 + 48)
- Per-caller keys (frontend / CI / admin separate)
- WAF / DDoS protection (Cloudflare in front of Fly)
- Tamper-evident audit log
- Per-customer data isolation (row-level security)
- Indirect-injection defense via tool-output sanitization (Fork 49)
- Guard-LLM call for injection classification (Fork 49)
- Multi-key rotation overlap support (Fork 48)
- IP truncation (last octet zeroed, Fork 53)

### Observability
- Sentry integration with breadcrumbs for client-side errors (G20)
- Self-host Langfuse (data residency / DPA control)
- OpenTelemetry collector for vendor-neutral export
- Datadog / Honeycomb APM for distributed traces
- Better Stack / Logflare stdout aggregation with alerting
- Live pricing-API integration (G11)
- Per-question cost dashboard aggregated from Langfuse
- Web Vitals reporting via Vercel Speed Insights
- Lighthouse CI with budget gating (G14)
- Anthropic `system_fingerprint` equivalent when exposed (G24)

### Data layer
- ETL → parquet at build time for faster boot (Fork 19)
- Monthly / quarterly customer rollup tables (Fork 19)
- HTS-level rollup tables (Fork 19)
- Read-only DuckDB connection sandbox (Fork 50)
- Per-query statement timeout (Fork 50)
- Query plan inspection (`EXPLAIN` gating) (Fork 50)

### RAG
- Cross-encoder reranker (`bge-reranker-base`) (Fork 16)
- Metadata-aware retrieval filtering by `section_kind` (Fork 16)
- Embedding model upgrade (Fork 13)
- Hybrid weight tuning (replace RRF with weighted sum) (Fork 16)
- Per-tool retrieval bypass (Fork 16)
- Live re-indexing endpoint (Fork 17)
- Vector store migration (pgvector / Pinecone) for multi-machine (Fork 4)

### Agent
- Plan-then-execute split (Sonnet plans, Haiku executes) (Fork 56)
- Classifier-based model routing (Fork 56)
- Fine-tuned customs-specific routing model (Fork 56)
- Provider-fallback router (Anthropic ↔ OpenAI) (Fork 56)
- Long-context model variant (Sonnet 1M-token variants) (Fork 56)
- LLM-summarized history compaction (G9 follow-on)
- Dated model pin (e.g., `claude-sonnet-4-6-YYYYMMDD`) for strict reproducibility (Fork 5 / G1)
- Discriminated unions for `ToolCallTrace.args/result` per tool (Fork 28 / G3)
- Pydantic-to-TypeScript build-time codegen (G21 future)

### Frontend
- React Testing Library component tests (G2)
- Playwright E2E smoke tests (G2)
- Per-message-bubble error boundaries (G20)
- Sentry integration for client errors (G20)
- "Reload conversation" button after error boundary trip
- Visual regression (Chromatic / Playwright screenshots) (G2)
- Service Worker SSE buffer for backgrounded tabs (G23)
- Per-conversation OpenGraph image generation (G22)
- Toast queue (Fork 28 / G10)
- Retry-with-exponential-backoff for transient errors (G10)
- `navigator.onLine` offline detection (G10)
- Per-tool discriminated unions in `ToolCallTrace` rendering
- BrowserslistDB + polyfill bundle for older browsers (G15)
- Storybook for component sandboxes
- MSW for richer `lib/api.ts` tests

### Infrastructure
- Per-PR Fly preview apps (Fork 42)
- Multi-region Fly (`iad,ams,nrt`) (Fork 36)
- Auto-rollback GHA step on smoke-test failure (G17)
- Branch protection on private repo (requires GitHub Pro) (G4)
- Docker Compose for local dev with Redis/Postgres (G18)
- VS Code Dev Container configuration (G6)
- Pre-commit hooks (lint + secret scan) (G6)
- `direnv` for auto-loading `.env` (G6)
- `act` for running GHA locally (G6)
- Managed secrets manager (Doppler / Infisical / AWS Secrets Manager) (Fork 39)
- `uv export --format requirements-txt` for Azure migration (G12)
- Multi-arch Docker builds (`linux/arm64`) (Fork 41)
- Fly log drain to S3/R2 for retention > 5 days (Fork 53)

### Compliance
- SOC 2 Type II
- GDPR DPA + data residency
- HIPAA BAA where applicable
- Tamper-evident audit log (Fork 53)
- Right-to-be-forgotten endpoint (Fork 53)
- Pseudonymized user-message hashing (Fork 53)
- Consent flow / ephemeral mode toggle (Fork 53)
- CMK encryption at rest (Fork 53)
- Data export endpoint (GDPR Art. 15) (Fork 53)

### Cost optimization
- Live pricing API integration (G11)
- Cheap-model classifier router (Fork 56)
- Response caching by `(prompt_version, model, question, dataset_sha)` (G5 generator)
- 3× majority-vote on Q9 rubric (Fork 8)
- Per-region pricing if expanding to EU
- Multi-version A/B eval (Fork 46)
- Anthropic / OpenAI dashboard programmatic alerts (G19)

### Documentation
- Architecture diagram in Excalidraw (alternative to Mermaid)
- API changelog when versioning is introduced (G8)
- Decision Records (ADRs) for major decisions
- Contributor guide
- Recipe cookbook for common questions
- HTML / PDF export of EVALUATION.md (G5)
- Build journal automation from git log
```

Total: ~70-80 items across 10 categories. Reviewers see the breadth of
deliberate scoping rather than ad-hoc deferrals.

### Authoring rule

When in doubt, **defer to future work** rather than implement. The
Communication-rubric reward for "we know what we'd improve" usually
exceeds the Accuracy-rubric reward for one more half-baked feature.

---

## Skipped Items (Explicit Transparency)

For full honesty, two G-items are explicitly skipped — not deferred,
but deliberately out-of-scope:

| Item | Reason | Future-work? |
|---|---|---|
| G16 — Custom domain | $12/year for marginal polish; default `*.vercel.app` + `*.fly.dev` URLs read as "demo" appropriately | No |
| G21 — Accessibility overall audit | shadcn/ui defaults + per-feature aria attention in Forks 30-34 suffice for demo scale | No |

Mention briefly in README "Known limitations" without emphasizing —
they're deliberate scope choices, not failures.

---

## Browser Support Statement (G15)

One-line section in README:

> *"Supported on modern evergreen browsers (Chrome / Edge / Firefox /
> Safari, last 2 versions). Mobile Safari is supported but may throttle
> background SSE streaming if the tab is backgrounded mid-response (see
> Known Limitations)."*

---

## Background SSE Caveat (G23)

In README "Known Limitations":

> *"Browsers throttle background tabs. Streaming responses may stall
> if the tab is backgrounded mid-stream. The frontend shows the partial
> response with a Retry button (Fork 29); re-submitting the question
> generates a fresh response."*

Service Worker buffering is documented as future work under the
Frontend category in G26.

---

## Day 7 Polish Checklist (Fork 57 item #52-57)

The `docs/final-polish` branch's PR should land all of this:

- [ ] README "Architecture" section with Mermaid diagram
- [ ] README "How the knowledge layer works" section
- [ ] README "Infrastructure decisions" section + **Azure equivalent mapping table**
- [ ] README "How we'd ship this on the team" subsection (Graphite mention)
- [ ] README "Security considerations" with 8-control table (G7)
- [ ] README "Testing strategy" section (Fork 45 three layers + G2 frontend)
- [ ] README "Observability" section with cookbook (`fly logs | jq` + Langfuse filters)
- [ ] README "Cost optimization" section with measured cache hit rate from latest EVALUATION.md
- [ ] README "Performance budgets" table (G14)
- [ ] README "Known limitations" section (G15 browser, G23 SSE throttling, trace expiration, etc.)
- [ ] README "Future Work" section grouped by 10 categories (G26)
- [ ] README "Quick start" + repo layout
- [ ] CI badges (CI / Eval / Deploy) linked to GitHub Actions
- [ ] `backend/README.md` — Makefile pointer + "Troubleshooting → Deploy issues" with G17 rollback commands + G18 local dev parity paragraphs
- [ ] `frontend/README.md` — Makefile pointer + pnpm/G13 note
- [ ] Anthropic + OpenAI dashboard alerts configured at $20 monthly cap (G19)
- [ ] Manual end-to-end smoke test: all 11 questions from fresh incognito browser at demo URL
- [ ] Final regeneration of `EVALUATION.md` via `make eval-md` against deployed backend
- [ ] Self-assessment paragraphs filled in for any rubric warnings in EVALUATION.md
- [ ] Final commit cleanup before push

---

## Pre-Submission Checklist

Before submitting the project (per Fork 57's "Pre-Submission Checks"):

- [ ] All 11 graded questions pass (correctness axis) per latest EVALUATION.md
- [ ] CI green on `main` (all jobs)
- [ ] Deployed demo URL functional end-to-end from fresh incognito browser
- [ ] `https://customs-agent-backend.fly.dev/ready` returns 200 with current manifest
- [ ] README has architecture diagram + all required deliverable sections
- [ ] `EVALUATION.md` regenerated within 24 hours of submission (trace-link freshness — Fork 53)
- [ ] Anthropic + OpenAI dashboard cost alerts configured (G19)
- [ ] All secrets confirmed in Fly Secrets + Vercel Env + GitHub Secrets
- [ ] Repo set to public OR invite-only with reviewer access granted
- [ ] Recruiter-topic documentation present (Azure equivalent mapping + Graphite mention)
- [ ] Submission email/form completed with repo URL + demo URL

---

## Composition with Other Layers

- **`00-decisions-index.md`** — every fork / G-item decision referenced
  here lives there with one-line outcome + pointer to detail file
- **`01-architecture.md`** — Mermaid diagram, design principles, and
  request-lifecycle narrative source the "Architecture" README section
- **`02-data-layer.md`** through **`10-observability.md`** — each
  README section references the detail file that owns the
  authoritative content
- **`PROGRESS.md`** — phase checklist sources the "Build journal"
  optional appendix in EVALUATION.md
- **`CLAUDE.md`** — workflow rules (no-co-author commits, branch
  naming, EVALUATION.md handling) reinforced in `docs/final-polish`
  branch operations

The README is the **only** file that synthesizes content from all 12
context files. Everywhere else, cross-referencing rather than
duplication is the rule.

---

## Future Work

| Item | Trigger |
|---|---|
| **Architecture diagram in Excalidraw** (alternative to Mermaid for richer styling) | When diagram complexity warrants beyond Mermaid's expressiveness |
| **API changelog** (`docs/api-changelog.md`) | When URL versioning is introduced (G8) |
| **Decision Records (ADRs)** for major decisions | When team scales and historical context needs surfacing |
| **Contributor guide** (`CONTRIBUTING.md`) | When external contributors are welcomed |
| **Recipe cookbook** for common questions | When the user community grows enough to want canonical query patterns |
| **HTML / PDF export** of EVALUATION.md | When archival / compliance needs arise (G5) |
| **Build journal automation** from `git log` + PR descriptions | When the manual journal update becomes routine drag |
| **Internationalized README** | When non-English-speaking reviewers / users matter |
| **Video walkthrough** of the demo | High-effort but high-engagement Communication artifact |
| **Public Langfuse project** for permanent trace links | When trace-link freshness beyond 30 days becomes a real concern |

All deferred. The Day 7 documentation pass keeps the README focused on
what's required + the high-leverage trade-off narratives.
