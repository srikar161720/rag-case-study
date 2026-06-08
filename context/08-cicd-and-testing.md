# CI/CD and Testing

Authoritative source for the GitHub Actions workflows, the three-layer
test pyramid (unit / integration / eval), the two-axis pass-criteria
grading (Fork 46), the API-contract drift check (G3), the frontend
Vitest setup (G2), and the PR + rebase-merge workflow via VS Code
Source Control (G4).

Load this file when working on `.github/workflows/`, `backend/tests/`,
`frontend/src/lib/*.test.ts`, or the PR / merge process.

---

## Overview

Three GitHub Actions workflows, three test layers, two CI cost tiers:

| Workflow | When it runs | Cost | What it does |
|---|---|---|---|
| `ci.yml` | Every PR + every push to `main` | $0 (no LLM) | Lint, typecheck, unit tests, integration tests (mocked LLM), frontend Vitest, secret scan, API contract drift |
| `eval.yml` | PRs touching agent code + nightly cron + manual + `eval-on-pr` label | ~$0.06/run with caching (~$3-5/month total) | Real-LLM evaluation against `ground_truth.json` |
| `deploy.yml` | Push to `main` (post-merge) | $0 | Build + push Docker image to Fly; deploy; smoke-test `/ready` |

Three test layers map to the workflows:

| Layer | Path | LLM | Runs in | Catches |
|---|---|---|---|---|
| **Unit** | `tests/unit/`, `frontend/src/lib/*.test.ts` | None | `ci.yml` every PR | Pure-function bugs (tools, views, validators, RAG, SSE parser, storage) |
| **Integration** | `tests/integration/` | Mocked via `StubLLM` | `ci.yml` every PR | Agent loop control flow (tool selection, iteration cap, dedup, refusal, citation validation, SSE event ordering) |
| **Eval** | `tests/eval/` | **Real** Anthropic | `eval.yml` path-triggered + nightly | End-to-end LLM correctness on the 11 graded questions + 5 out-of-scope cases |

---

## Test Pyramid (Fork 45)

### Layer 1 — Unit (every PR, fast, $0)

**Pure-function tests with no LLM and no agent loop.** Run in <10
seconds combined; backbone of the fast PR feedback loop.

**Backend** (`backend/tests/unit/`):

```
tests/unit/
├── data/
│   ├── test_load.py            # CAST schema, NULLIF behavior, type coercion
│   ├── test_views.py           # entries_v + entry_lines_v aggregation correctness
│   └── test_validation.py      # boot-time validator assertions
├── tools/
│   ├── test_filters.py         # EntryFilters Pydantic Literal enforcement
│   ├── test_effective_duty_rate.py
│   ├── test_total_duty_breakdown.py    # MPF cap correctness
│   ├── test_hold_summary.py            # 5%/8% threshold logic
│   ├── test_top_hts_by_duty.py         # ordering + HTS format
│   ├── test_qbr_summary.py
│   ├── test_compare_customers.py
│   ├── test_query_entries.py           # column allowlist enforcement
│   └── test_lookup_knowledge.py
├── rag/
│   ├── test_chunker.py         # section-header split + section_kind tagging
│   ├── test_retriever.py       # RRF fusion + HTS tokenization
│   └── test_always_on.py       # deterministic ordering
└── agent/
    ├── test_refusal_classifier.py
    ├── test_marker_validator.py        # orphan [N] stripping
    └── test_prompt_snapshot.py         # PROMPT_VERSION drift guard
```

**Frontend** (`frontend/src/lib/*.test.ts`, G2):

```
frontend/src/lib/
├── sse.test.ts          # parser: chunk boundary buffering, all event types, malformed dispatch
├── storage.test.ts      # localStorage round-trip, quota handling, Private Mode fallback
├── citations.test.ts    # marker resolution, orphan handling, kind classification
└── api.test.ts          # ApiError construction, error code mapping, network failure synthesis
```

**Session-scoped fixtures** (loaded once per test session for speed):

```python
# backend/tests/conftest.py
import duckdb, pytest
from hashlib import sha256
from pathlib import Path

@pytest.fixture(scope="session")
def db_con():
    """In-memory DuckDB with full schema + views — shared by all backend tests."""
    from customs_agent.data.load import load_entries
    from customs_agent.data.views import create_views
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    yield con
    con.close()

@pytest.fixture(scope="session")
def ground_truth():
    """Loaded ground_truth.json (Fork 43) with dataset SHA-256 drift guard."""
    import json
    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    actual = sha256(CSV_PATH.read_bytes()).hexdigest()
    if gt["dataset_sha256"] != actual:
        pytest.fail(
            f"Dataset drifted since ground truth was generated.\n"
            f"  Fixture SHA: {gt['dataset_sha256'][:12]}…\n"
            f"  Live    SHA: {actual[:12]}…\n"
            f"  Regenerate: cd backend && uv run python -m tests.ground_truth"
        )
    return gt
```

### Layer 2 — Integration (every PR, fast, $0)

**Agent loop with mocked LLM via `StubLLM`.** Real tools, real RAG,
real DuckDB; only the LLM client is mocked. Catches agent control-flow
bugs that unit tests can't reach without paying for LLM tokens.

```python
# backend/tests/integration/stub_llm.py
from dataclasses import dataclass

@dataclass
class ToolUseTurn:
    tool: str
    args: dict

@dataclass
class TextTurn:
    text: str

class StubLLM:
    """Deterministic mock returning scripted responses to agent-loop LLM calls."""
    def __init__(self, script: list):
        self._iter = iter(script)

    def messages_create(self, **kwargs):
        try:
            return next(self._iter)
        except StopIteration:
            raise AssertionError(
                "Agent made more LLM calls than the script provided. "
                "Either extend the script or fix an unintended loop."
            )

@pytest.fixture
def stub_llm():
    return StubLLM
```

**Integration test scope**:

```
tests/integration/
├── test_tool_selection.py        # given canned LLM, agent invokes right tool with right args
├── test_iteration_cap.py         # Fork 23 — graceful degradation at 5 iterations
├── test_dedup.py                 # Fork 23 — same (tool, args) returns cached
├── test_budget_guard.py          # Fork 23 — token budget triggers graceful exit
├── test_refusal_routing.py       # Fork 25 — all 5 categories
├── test_citation_validation.py   # Fork 28 — orphan [N] stripping
├── test_sidecar_assembly.py      # Fork 28 — citations built from real history
├── test_ambiguity_pattern.py     # Fork 24 — default + state + cite
├── test_sse_streaming.py         # Fork 29 — event ordering
├── test_meta_block.py            # Fork 28 — meta fields populated
├── test_auth.py                  # Fork 48 — 401/403/200 paths
├── test_rate_limit.py            # Fork 47 — 429 path
├── test_prompt_injection.py      # Fork 49 — 5 representative cases
└── test_sql_safety.py            # Fork 50 — column allowlist + safe_execute
```

### Layer 3 — Eval (path-triggered + nightly, real LLM, ~$0.06/run)

**Real Anthropic Sonnet 4.6 against the 11 graded questions + 5
out-of-scope cases.** Parametrized over `ground_truth.json` (Fork 43);
graded with two-axis criteria (Fork 46).

```
tests/eval/
├── _grading.py             # Fork 46 — correctness + architecture grading
├── _report.py              # markdown report generator for EVALUATION.md
├── test_questions.py       # the 11 graded questions, parametrized
├── test_out_of_scope.py    # 5 refusal robustness cases (Fork 25)
└── test_meta_endpoints.py  # /health, /ready smoke tests on the deployed backend
```

```python
# backend/tests/eval/test_questions.py
import pytest
from tests.eval._grading import grade_question

@pytest.mark.parametrize("question", load_ground_truth()["questions"])
def test_question(question, agent_client):
    response = agent_client.ask(question["query"])
    correctness = check_correctness(question, response)
    architecture = check_architecture(question, response)
    record_result(question, response, correctness, architecture)

    # Hard fail on correctness; architecture mismatch is a warning logged for report
    assert correctness.all_pass, (
        f"Q{question['id']} correctness failed:\n"
        + "\n".join(f"  - {check}" for check in correctness.failures)
    )
```

---

## Pass Criteria — Two-Axis Grading (Fork 46)

**Correctness (must pass)** + **Architecture (warn-only)**.

| Tier | Questions | Correctness checks (must pass) | Architecture checks (warn-only) |
|---|---|---|---|
| **T1** | Q1-3 | Numeric/label match within `tolerance`; `refused == False` | `expected_tool_name` was called; `expected_tool_args_partial` ⊆ actual args |
| **T2** | Q4-6 | T1 + all `expected_citations` chunk_ids present in `knowledge_citations[]`; status string equals expected (Q6) | T1 architecture checks |
| **T3** | Q7 | Numeric correctness on `highest_customer_code` (exact) AND `ieepa_pct` of winning customer (within tolerance); ranking order matches | `compare_customers` called |
| **T3** | Q8 | Top-5 HTS code SET matches expected (tie-breaking variance allowed); each `total_duty` within tolerance; HTS format `XXXX.XX.XXXX` in prose | `top_hts_by_duty` called with `limit=5` |
| **T3** | Q9 | LLM-as-judge rubric ≥ 3/4; each numeric subfield within tolerance | `qbr_summary` called |
| **T4** | Q10 | All `expected_phrases` present in prose ("Release Date", "Rule 1"); `rule_1_date_filtering` cited; `refused == False` | `lookup_knowledge` called OR no tool call (both acceptable) |
| **T4** | Q11 | Numeric correctness on `entry_count` AND `line_count` AND `difference`; prose contains both "entry" and "line"; `rule_2_entry_vs_line_count` cited | Two `query_entries` calls (one per grain) |

### Grading helpers

```python
# backend/tests/eval/_grading.py
from typing import Any
import re

def grade_question(question: dict, response: ChatResponse) -> QuestionResult:
    correctness = _check_correctness(question, response)
    architecture = _check_architecture(question, response)
    status = "PASS" if correctness.all_pass else "FAIL"
    if status == "PASS" and not architecture.all_pass:
        status = "PASS (warn)"
    return QuestionResult(status=status, correctness=correctness, architecture=architecture)


def _check_correctness(q, r):
    checks = [_check_refused(q, r), _check_numeric(q, r),
              _check_phrases(q, r), _check_citations(q, r)]
    if q.get("rubric"):
        checks.append(_run_rubric_judge(q, r))
    return CorrectnessReport(checks=checks)


def assert_close(actual, expected, tolerance):
    if tolerance == 0 or tolerance is None:
        return actual == expected, f"expected {expected!r}, got {actual!r}"
    kind, value = tolerance
    if kind == "abs":
        ok = abs(actual - expected) <= value
        return ok, f"|{actual} - {expected}| > {value}" if not ok else ""
    if kind == "rel":
        ok = abs(actual - expected) / expected <= value
        return ok, f"|{actual} - {expected}| / {expected} > {value}" if not ok else ""
```

### Q9 LLM-as-judge prompt (Fork 8)

```python
# backend/tests/eval/_grading.py
JUDGE_PROMPT = """You are grading an AI agent's response to a QBR question.

QUESTION:
{question}

EXPECTED COMPONENTS:
1. entry_volume_by_month: monthly entry counts for Jan, Feb, Mar 2025
2. duty_breakdown_by_program: primary, Section 301, IEEPA, MPF, HMF totals
3. top_countries: sourcing countries listed
4. hold_rate: hold rate stated as a percentage

AGENT'S RESPONSE:
{response_prose}

For each component, score 1 (clearly present) or 0 (missing/unclear).
Return JSON ONLY (no commentary):
{"entry_volume_by_month": 0|1, "duty_breakdown_by_program": 0|1,
 "top_countries": 0|1, "hold_rate": 0|1}
"""

def _run_rubric_judge(question, response) -> Check:
    client = OpenAI(api_key=settings.openai_api_key)
    resp = client.chat.completions.create(
        model=settings.llm_judge_model,      # gpt-4o-mini per Fork 8
        temperature=0,
        seed=settings.llm_seed,              # 42 per Fork 26
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(
            question=question["query"], response_prose=response.answer)}],
        response_format={"type": "json_object"},
    )
    scores = json.loads(resp.choices[0].message.content)
    total = sum(scores.values())
    threshold = 3  # ≥ 3/4 to pass per Fork 46
    return Check(passed=total >= threshold, message=f"Rubric: {total}/4")
```

**Pass threshold ≥ 3/4** — one minor omission shouldn't fail an
otherwise-correct QBR.

### Grader as-built notes (`feat/remaining-tools-and-eval`)

The shipped grader (`tests/eval/_grading.py`) reads numeric answers
**structurally from `ChatResponse.tool_calls[].result`** (never parsed
from prose) and resolves citations against `knowledge_citations[]` ∪ the
always-on chunk set. Two robustness fixes landed after the first real
`eval.yml` run surfaced grader-only false-failures (all guarded by new
`tests/unit/eval/test_grading.py` regressions — see CLAUDE.md Gotcha #26):

- **Decimals serialize as JSON strings.** `ground_truth.json` stores
  `Decimal` money as strings (`"59949493.45"`) while tools return real
  `Decimal`s. The grader compares them NUMERICALLY via the tolerance loop;
  the string-label check fires only when the *actual* value is itself a
  `str` (true labels like port code / status), so Decimal money is never
  compared `Decimal == str` (which had masked correct Q2/Q4/Q5).
- **`line_count` is grain-sensitive.** `count_lines` (`COUNT(*)`) is the
  true tariff-line count only on `entry_lines_v`; on `entries_v` it counts
  entries. `_extract_scalar(..., prefer_view="entry_lines_v")` reads the
  grain-correct value so a redundant `count_lines`-on-`entries_v` call
  can't shadow it (Q11).

The eval record (and `REPORT.md`) capture a per-tool-call summary
(name / view / args / result) so a failing question is self-diagnosing from
the report alone. `_report.py` writes the compact PR-comment report +
`.last-result.json` cache; the full submission-grade `EVALUATION.md` is a
separate artifact from `scripts/generate_evaluation_md.py` (G5).

---

## CI Workflow: `ci.yml`

> **As-built note (`chore/ci-cd`, 2026-06-02)**: the YAML below is the
> *eventual 5-job target*. What shipped on `chore/ci-cd` is **3 jobs**
> — `backend`, `frontend`, `secret-scan`. The `api-contract` job (G3)
> lands on `feat/api-contract` and `evaluation-freshness` on
> `feat/remaining-tools-and-eval` (Day 4) — both depend on files that
> don't exist yet (`openapi.json`, `api-types.ts`, `gen:types`,
> `EVALUATION.md`), so including them now would make CI red. Branch
> protection currently requires the 3 shipped checks; add
> `api-contract` to the required list when it lands. Concrete deltas
> from the snapshot below (action versions verified current via
> Context7 + WebSearch, June 2026):
> - **`astral-sh/setup-uv@v3` → `@v6`**.
> - **Backend lockfile: `uv sync --locked`** (installs AND asserts
>   `uv.lock` currency in one step) replaces the two-step `uv sync
>   --frozen` + `uv lock --check`. Keeps G12's drift guard.
> - **`pnpm/action-setup@v3` `version: 9` → `@v4` `version: 11.1.3`**
>   (matches `package.json`'s `packageManager`; the spec's `9` causes a
>   Corepack mismatch).
> - **`actions/setup-node` `node-version: "20"` → `"22"`** — pnpm 11.x
>   requires Node ≥ 22.13 (`node:sqlite` builtin); Node 20 dies with
>   `ERR_UNKNOWN_BUILTIN_MODULE` (CLAUDE.md Gotcha #21).
> - **Backend job builds the RAG index before `pytest`** (a
>   `scripts/build_index.py` step with `OPENAI_API_KEY`), because the
>   integration suite boots the full app via lifespan and the gitignored
>   `chroma_db/`+`bm25.pkl` are absent on a fresh checkout (Gotcha #22).
>   So the backend CI job is NOT secret-free — it needs `OPENAI_API_KEY`.
> - **Frontend job runs lint + typecheck + build only** (no `pnpm
>   test`) — the test script is a no-op until Vitest on
>   `feat/frontend-tests` (Day 6, G2).
> - **`pnpm install --frozen-lockfile`** relies on
>   `frontend/pnpm-workspace.yaml` `allowBuilds` (sharp, unrs-resolver)
>   or it fails `ERR_PNPM_IGNORED_BUILDS` (Gotcha #21).
> - **gitleaks**: `GITHUB_TOKEN` only — `GITLEAKS_LICENSE` is org-repos
>   only, not this user-account repo.

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with: { python-version: "3.12" }
      - run: uv sync --frozen
      - name: Verify uv.lock not drifted
        run: uv lock --check
      - run: uv run ruff check .
      - run: uv run mypy src
      - run: uv run pytest tests/unit tests/integration -v

  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v3
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm typecheck
      - run: pnpm test --run
      - run: pnpm build

  secret-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
        env: { GITHUB_TOKEN: '${{ secrets.GITHUB_TOKEN }}' }

  api-contract:
    # G3 — verify openapi.json + api-types.ts are in sync with current code
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - uses: pnpm/action-setup@v3
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }

      - name: Verify openapi.json is up to date
        working-directory: backend
        run: |
          uv sync --frozen
          uv run python -m scripts.export_openapi > /tmp/openapi.expected.json
          if ! diff -q ../openapi.json /tmp/openapi.expected.json > /dev/null; then
            echo "::error::openapi.json is out of date. Run:"
            echo "  make openapi"
            diff ../openapi.json /tmp/openapi.expected.json | head -50
            exit 1
          fi

      - name: Verify api-types.ts is up to date
        working-directory: frontend
        run: |
          pnpm install --frozen-lockfile
          pnpm gen:types:check
        # gen:types:check generates to /tmp and diffs against committed src/lib/api-types.ts

  evaluation-freshness:
    # Advisory only — warns if EVALUATION.md was generated under an older PROMPT_VERSION
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - name: Check EVALUATION.md PROMPT_VERSION
        run: |
          CURRENT=$(grep -oP 'PROMPT_VERSION\s*=\s*"\K[^"]+' \
            backend/src/customs_agent/agent/prompt.py || echo "unknown")
          COMMITTED=$(grep -oP '`PROMPT_VERSION`.*`\K[^`]+' EVALUATION.md \
            | head -1 || echo "unknown")
          if [ "$CURRENT" != "$COMMITTED" ]; then
            echo "::warning::EVALUATION.md generated under PROMPT_VERSION $COMMITTED; current is $CURRENT. Consider regenerating before merge: make eval-md"
          fi
```

---

## CI Workflow: `eval.yml`

> **As-built note (`feat/remaining-tools-and-eval`)**: the YAML below is the
> planning sketch; the shipped `eval.yml` differs in a few ways (all verified
> against current GitHub Actions docs via Context7):
> - **Single valid `pull_request` trigger** — the sketch's two `pull_request:`
>   keys are invalid YAML (duplicate key, second wins). Shipped: one
>   `pull_request` with `types: [opened, synchronize, reopened, labeled]` +
>   `paths`, and a job-level `if` that gates the `labeled` action to the
>   `eval-on-pr` label (path/synchronize/nightly/manual always proceed).
> - **Secrets-present gate** — a `Check eval secrets are present` step sets a
>   step output; the build-index + eval steps gate on
>   `&& steps.secrets.outputs.present == 'true'` so forks / unconfigured repos
>   skip cleanly instead of failing at `build_index.py` with an empty key (the
>   "skips cleanly" promise otherwise only held at the pytest layer). Job-level
>   `permissions: { issues: write, pull-requests: write }`.
> - **Sticky PR comment** — instead of `createComment` per run (which would
>   accumulate one comment per run), the comment step finds a prior comment by
>   a hidden `<!-- customs-eval-report -->` marker and `updateComment`s it in
>   place, else creates it; on a cache hit (no `REPORT.md`) it no-ops (the
>   existing comment already reflects that content-hash).
> - **Content hash** also covers `tests/eval/*.py` (the grader); `setup-uv@v6`
>   + `uv sync --locked` match `ci.yml`.

```yaml
# .github/workflows/eval.yml — real-LLM evaluation
name: Eval (real LLM)
on:
  pull_request:
    branches: [main]
    paths:
      - 'backend/prompts/**'
      - 'backend/src/customs_agent/agent/**'
      - 'backend/src/customs_agent/tools/**'
      - 'backend/src/customs_agent/rag/**'
      - 'backend/src/customs_agent/data/**'
      - 'backend/scripts/build_index.py'
      - 'backend/tests/ground_truth.py'
      - 'backend/tests/ground_truth.json'
      - 'backend/pyproject.toml'
  pull_request:
    types: [labeled]                  # manual opt-in via `eval-on-pr` label
  schedule:
    - cron: '0 5 * * *'               # 5am UTC nightly
  workflow_dispatch:                  # manual button

jobs:
  eval:
    if: |
      github.event_name != 'pull_request' ||
      github.event_name == 'pull_request' && (
        github.event.action != 'labeled' || github.event.label.name == 'eval-on-pr'
      )
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen

      - name: Compute content hash for cache key
        id: hash
        run: |
          HASH=$( ( \
            find prompts src/customs_agent/agent src/customs_agent/tools \
                       src/customs_agent/rag src/customs_agent/data \
                 -type f \( -name '*.py' -o -name '*.md' -o -name '*.json' \) \
              | sort | xargs sha256sum; \
            sha256sum tests/ground_truth.json pyproject.toml uv.lock \
          ) | sha256sum | cut -d' ' -f1 )
          echo "hash=$HASH" >> "$GITHUB_OUTPUT"

      - name: Restore eval cache
        id: cache
        uses: actions/cache@v4
        with:
          key:  eval-result-${{ steps.hash.outputs.hash }}
          path: backend/tests/eval/.last-result.json

      - name: Build RAG index (needed for eval against this branch's chunks)
        if: steps.cache.outputs.cache-hit != 'true'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          uv run python scripts/build_index.py \
            --out-chroma ./chroma_db \
            --out-bm25 ./bm25.pkl \
            --out-manifest ./manifest.json

      - name: Run real-LLM eval
        if: steps.cache.outputs.cache-hit != 'true'
        env:
          ANTHROPIC_API_KEY:    ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY:       ${{ secrets.OPENAI_API_KEY }}
          LANGFUSE_PUBLIC_KEY:  ${{ secrets.LANGFUSE_PUBLIC_KEY }}
          LANGFUSE_SECRET_KEY:  ${{ secrets.LANGFUSE_SECRET_KEY }}
          LANGFUSE_HOST:        https://cloud.langfuse.com
        run: uv run pytest tests/eval -v --junitxml=tests/eval/.junit.xml

      - name: Comment results on PR
        if: github.event_name == 'pull_request' && always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            if (!fs.existsSync('backend/tests/eval/REPORT.md')) return;
            const report = fs.readFileSync('backend/tests/eval/REPORT.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo:  context.repo.repo,
              body:  report,
            });

      - name: Upload eval artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-results
          path: backend/tests/eval/

      - name: Open issue on nightly failure
        if: failure() && github.event_name == 'schedule'
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.issues.create({
              owner: context.repo.owner, repo: context.repo.repo,
              title: `Nightly eval failed ${new Date().toISOString().split('T')[0]}`,
              labels: ['eval-failure', 'drift'],
              body: 'Nightly eval regression on main. See workflow run for details. This may indicate provider-side model drift (Sonnet 4-6 snapshot rotation).'
            });
```

### Why the content-hash cache key

A SHA-256 over: `prompts/`, `src/customs_agent/{agent,tools,rag,data}/`,
`scripts/build_index.py`, `tests/ground_truth.{py,json}`,
`pyproject.toml`, `uv.lock`. If a no-op push lands (README typo, frontend-only
PR), the path filter skips this workflow entirely. If a push touches a
triggering path but the content hash matches a prior run, the cache hits
and we don't spend LLM dollars re-running the same eval.

### Why the nightly drift-issue auto-open

Catches provider-side model behavior changes when nothing in our repo
changes. If nightly fails when `main` hasn't changed, it's evidence
Anthropic rotated the Sonnet 4-6 snapshot — investigate before merging
anything.

---

## CI Workflow: `deploy.yml`

> **As-built note (`chore/ci-cd` + 2 post-merge hotfixes,
> 2026-06-02)**: `deploy.yml` can only be exercised on a push to
> `main`, so two bugs in the snapshot below surfaced as separate
> post-merge hotfixes:
> - **`flyctl deploy --config backend/fly.toml` (from repo root) fails**
>   `app does not have a Dockerfile or buildpacks configured` — Fly
>   resolves the Dockerfile relative to the **build-context /
>   working-directory**, not the `--config` path. Shipped form passes
>   `backend` as the workdir arg: **`flyctl deploy backend --config
>   fly.toml ...`**, replicating the manual `cd backend && fly deploy`.
> - **`setup-flyctl@master` → `@v1`** (Copilot review: don't float on
>   `@master`). NOTE: `@v1.5` does NOT exist — the repo's release
>   *titled* "v1.5" maps to a tag literally named `1.5`; `v1` is the
>   maintained major tag. (CLAUDE.md Gotcha #23.)
> - **Smoke test uses a retry loop, not `curl -sf` under `set -e`**
>   (Copilot review): `-f` exits non-zero on a non-2xx, which under
>   `set -e` aborts before the status check and turns a transient
>   rollout 503 into a hard failure. Shipped form polls `/ready` up to
>   5× capturing the HTTP code with `curl -s` (no `-f`).
>
> Rollback stays manual per G17. `OPENAI_API_KEY` is required here as a
> Docker build secret (Gotcha #19).

```yaml
# .github/workflows/deploy.yml — Fly deploy on merge to main
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - name: Deploy to Fly
        run: |
          flyctl deploy --config backend/fly.toml \
            --build-secret openai_key=$OPENAI_API_KEY \
            --remote-only \
            --app customs-agent-backend
        env:
          FLY_API_TOKEN:  ${{ secrets.FLY_API_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

      - name: Wait for new machine
        run: sleep 15

      - name: Smoke test /ready
        run: |
          set -e
          response=$(curl -sf -w "\n%{http_code}" \
            https://customs-agent-backend.fly.dev/ready)
          body=$(echo "$response" | head -n -1)
          status=$(echo "$response" | tail -n 1)
          if [ "$status" != "200" ]; then
            echo "::error::/ready returned $status"
            echo "$body"
            exit 1
          fi
          echo "✓ /ready passed"
          echo "$body" | jq .

      # Frontend: no action needed — Vercel git integration auto-deploys
      # main → Production on push, all other branches → Preview.
```

`--remote-only` builds on Fly's builder (BuildKit enabled by default),
keeping GitHub Actions runner time free. The smoke test gates the
"deploy succeeded" signal; manual rollback per `07-infrastructure.md`
if it fails.

---

## G3 — API Contract Drift Check

Generated TypeScript types stay in sync with backend Pydantic models via
`openapi.json` as the intermediary:

```
backend Pydantic models  →  app.openapi()  →  openapi.json  →  openapi-typescript  →  api-types.ts
       (source of truth)                     (committed)                              (committed, linguist-generated)
```

The `api-contract` job in `ci.yml` regenerates both files in CI and
diffs them against the committed versions. Drift fails with an
actionable error message: `make types` (i.e., `make openapi &&
pnpm gen:types`) regenerates both.

### Polymorphic `args` / `result` handling (G3 nuance)

`ToolCallTrace.args` and `ToolCallTrace.result` are typed as
`Record<string, unknown>` in the generated TS (Pydantic emits these as
`object` with no constrained properties in OpenAPI). Frontend code uses
type guards or explicit casts where it needs to render tool-specific
shapes. Per-tool discriminated unions are **future work** documented in
`04-agent-and-tools.md`.

---

## G2 — Frontend Testing

Vitest unit tests for `frontend/src/lib/` pure-function modules. No
component tests (RTL), no Playwright E2E for the demo. Detail in
`06-frontend.md`; here are the CI integration points.

```typescript
// frontend/vitest.config.ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals:     true,
    include:     ['src/**/*.test.{ts,tsx}'],
    coverage: {
      reporter:   ['text', 'json-summary'],
      include:    ['src/lib/**'],
      thresholds: undefined,         // measure, don't gate (Goodhart)
    },
  },
});
```

`pnpm test --run` is invoked in `ci.yml`'s frontend job alongside lint,
typecheck, and build.

### Why no component tests

shadcn/ui + semantic Next.js gets render-time errors caught by `pnpm
typecheck` and `pnpm build`. Vercel preview deploys (Fork 42) provide
per-PR visual verification. Component tests with RTL would duplicate
that coverage with significant brittleness (role/text queries break on
copy changes). Documented as future work in `06-frontend.md`.

---

## G4 — PR Workflow with VS Code Source Control

All work happens on feature branches; PRs merge to `main` via
**rebase-merge** (preserves Fork 58's per-chunk commit history). The
user performs every git/gh operation manually via VS Code Source
Control (Cmd+Shift+G G).

### Branch naming convention

`<type>/<short-kebab-name>` matching the dominant Conventional Commits
type for the branch:

- `feat/data-layer`, `feat/agent-loop`, `feat/streaming`
- `chore/scaffold-monorepo`, `chore/dockerfile-fly`, `chore/ci-cd`
- `fix/citation-marker-orphan`
- `docs/final-polish`
- `test/ground-truth`, `test/backend-units`

### Rebase-merge as the only allowed strategy

Repository settings → General → Pull Requests:

- ✅ Allow rebase merging
- ❌ Allow squash merging        (destroys Fork 58's commit hygiene)
- ❌ Allow merge commits         (adds noise; not strictly linear)

This is enforced at the repo level so the "Rebase and merge" button is
the only option on a PR.

### Branch protection (public repos only, free on GitHub Free)

If the repo is public:

- ✅ Require a pull request before merging
- ✅ Require status checks: all `ci.yml` jobs + `api-contract`
- ✅ Require branches to be up to date before merging (forces rebase if main moved)
- ✅ Require linear history (rejects merge commits)
- ❌ Required reviewers: 0 (solo project)

If the repo is private on GitHub Free, branch protection isn't
available — relies on discipline. Document the limitation in the README.

### Per-PR workflow (the loop the user runs)

```
1. Start phase / sub-phase
   - VS Code Source Control: "..." menu → Pull (sync main)
   - Source Control: "..." → Checkout to → Create new branch from
     → Type: feat/data-layer

2. Work on Fork 57 items
   - Claude pauses at each logical chunk per Fork 58
   - User reviews diff in Source Control panel
   - User stages files (+ icon), pastes suggested commit message,
     clicks ✓ Commit (or Cmd+Enter)

3. Phase complete (Claude outputs "🚀 PHASE COMPLETE" message)
   - VS Code Source Control: sync icon (status bar) → push branch
     (first push: VS Code prompts "Publish Branch")
   - Command Palette (Cmd+Shift+P) → "GitHub Pull Requests:
     Create Pull Request"
     OR open GitHub web UI to create the PR manually
   - Paste Claude's suggested PR title and body

4. CI runs on the PR (ci.yml + api-contract + maybe eval.yml)
   - Vercel posts a preview URL comment within ~2 min
   - User reviews CI results

5. Merge
   - GitHub PR page → "Rebase and merge" (only option enabled)
   - PR auto-closes; branch optionally auto-deletes

6. Back to main
   - VS Code Source Control: "..." → Checkout to → main
   - Source Control: "..." → Pull
```

### Claude's pause messages prompt the user with these exact steps

The `🛑 LOGICAL CHUNK COMPLETE` template in `CLAUDE.md` includes the
"To commit (VS Code Source Control)" 4-step block. The
`🚀 PHASE COMPLETE` template includes the "To push and open PR" 4-step
block. Future Claude sessions just follow the templates.

---

## Composition with Other Layers

- **`02-data-layer.md`** — boot-time validators run in `lifespan()`
  (`05-api-and-backend.md`); unit tests in `tests/unit/data/`; ground-
  truth fixture is the canonical answer key for Layer 3 eval.
- **`03-rag-layer.md`** — RAG built at Docker build (Fork 17); eval
  workflow rebuilds the index from the branch's `prompts/` + chunker
  before running so the eval reflects the branch's RAG state.
- **`04-agent-and-tools.md`** — full agent control flow tested by
  Layer 2 integration tests with `StubLLM`; tool implementations
  tested at Layer 1.
- **`05-api-and-backend.md`** — endpoints + middleware exercised by
  Layer 2 integration tests; `/ready` smoke-tested by `deploy.yml`.
- **`06-frontend.md`** — frontend Vitest tests (G2) wired into
  `ci.yml` frontend job; `api-contract` job verifies `api-types.ts`
  in sync with backend Pydantic.
- **`07-infrastructure.md`** — Dockerfile + Fly + Vercel configured to
  match what `deploy.yml` invokes; secrets routing supplies the GHA
  Secrets used by all three workflows.
- **`09-security.md`** — gitleaks secret-scan in `ci.yml` enforces
  Fork 39 no-commits-with-secrets policy; integration tests cover
  every security control (auth, rate limit, injection, SQL safety).
- **`10-observability.md`** — Langfuse trace URLs surface in eval
  output for reviewer-friendly debugging; structured logs aid CI
  debugging via Fly tail.
- **`11-deliverables.md`** — `EVALUATION.md` generator is invoked
  manually before submission (`make eval-md`); the
  `evaluation-freshness` CI check is advisory.

---

## Cost Sanity (Fork 44 + Fork 55)

With Fork 55 prompt caching:

| Item | Per run | Per month |
|---|---|---|
| Nightly eval (30 days) | ~$0.06 | ~$1.80 |
| Path-triggered PR eval (~5/week, cached half the time) | ~$0.06 × 10 | ~$0.60 |
| Manual `workflow_dispatch` (~5/month) | ~$0.06 | ~$0.30 |
| Q9 rubric judge (gpt-4o-mini) per run | ~$0.001 | ~$0.04 |
| **Total real-LLM CI bill** | | **~$3-5/month** |

Without caching / filter: ~$60-90/month. Order-of-magnitude difference.

---

## Future Work

| Item | Trigger |
|---|---|
| `pytest-xdist` parallel test execution | When unit test count exceeds ~500 and serial runs slow PRs |
| React Testing Library component tests | When component-level regression risk grows |
| Playwright E2E smoke tests | When demo-URL outages must be caught before reviewer click |
| Auto-rollback on `/ready` smoke-test failure | Production-grade reliability |
| `dependabot` for npm + uv dependency updates | When deps fall out of date often enough to matter |
| Mutation testing (`mutmut`) for tool implementations | When confidence in test coverage becomes the bottleneck |
| Performance regression detection in eval | When latency targets become contractual |
| Multi-version A/B eval (compare `PROMPT_VERSION` 1.0.0 vs 1.1.0 outputs) | When prompt engineering becomes data-driven |
| `act` for running GitHub Actions locally | When CI iteration latency becomes painful |
| Code coverage as a CI gate (with carefully chosen threshold) | When team velocity warrants enforcing |
| Graphite stacked PRs replacing plain GitHub PRs | When team adopts stacked-PR culture (recruiter topic — README) |
