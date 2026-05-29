# API and Backend

Authoritative source for the FastAPI app structure, middleware stack
wiring, endpoint inventory, streaming protocol (Fork 29), and error
response shapes.

Load this file when working on `backend/src/customs_agent/api/`,
`backend/src/customs_agent/main.py`, or any cross-cutting middleware.
For the deep security rationale of each middleware (threat model, why
each control exists), see `09-security.md`.

---

## App Structure

```
backend/src/customs_agent/
├── __init__.py
├── main.py                         ← FastAPI app + middleware wiring + lifespan
├── config.py                       ← AgentConfig, LLMConfig, RateLimitConfig, SafetyConfig
├── api/
│   ├── __init__.py
│   ├── _rate_limit.py              ← slowapi setup, composite bucket, 429 handler
│   ├── _security_headers.py        ← X-Content-Type-Options, X-Frame-Options, etc.
│   ├── auth.py                     ← require_api_key dependency
│   ├── chat.py                     ← ChatRequest/ChatResponse models, POST /chat, /chat/stream
│   ├── starter_prompts.py          ← GET /api/starter-prompts
│   └── health.py                   ← GET /health, /ready
├── agent/                          ← see 04-agent-and-tools.md
├── tools/                          ← see 04-agent-and-tools.md
├── rag/                            ← see 03-rag-layer.md
├── data/                           ← see 02-data-layer.md
└── observability/                  ← see 10-observability.md
```

The `_`-prefixed files are infrastructural (middleware, helpers) — they
import from the others but aren't themselves API routes.

---

## `main.py` — App Wiring

```python
# backend/src/customs_agent/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

from customs_agent.api import auth, chat, health, starter_prompts
from customs_agent.api._rate_limit import limiter, custom_rate_limit_handler
from customs_agent.api._security_headers import SecurityHeadersMiddleware
from customs_agent.data.load import load_entries
from customs_agent.data.views import create_views
from customs_agent.data.validation import validate_loaded_data
from customs_agent.observability.logging import configure_logging, request_logging_middleware
from customs_agent.rag.retriever import init_retriever
from customs_agent.config import settings

import duckdb
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot-time initialization (Forks 3, 17, 18, 19, 20)."""
    configure_logging()
    # 1. Load CSV → typed schema → views → validators
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)
    app.state.db = con

    # 2. Load RAG indexes from baked-in artifacts (Fork 17)
    app.state.retriever = init_retriever()

    yield
    con.close()


app = FastAPI(
    title="Customs Analytics Agent",
    version="1.0.0",
    lifespan=lifespan,
    # Hide /docs and /redoc in production if you'd prefer; for the demo,
    # leaving them enabled gives reviewers a free API doc surface.
)

# Middleware execution order on REQUEST (outer-to-inner):
#   1. SecurityHeadersMiddleware  ← adds defensive headers to every response
#   2. CORSMiddleware             ← origin allowlist (Fork 38)
#   3. SlowAPIMiddleware          ← rate limit enforcement (Fork 47)
#   4. request_logging_middleware ← request_id binding + stdout log lines (Fork 52)
#   5. (routes + Depends(require_api_key) for protected endpoints)
#
# CRITICAL: Starlette's app.add_middleware() does
# `self.user_middleware.insert(0, ...)` — every call PREPENDS. Net
# effect: the LAST add_middleware call wraps OUTERMOST and the FIRST
# call wraps INNERMOST among user middlewares. The add order below is
# therefore the REVERSE of the request execution order above:
# request_logging added first → innermost; SecurityHeadersMiddleware
# added last → outermost. A future refactor that re-adds middlewares
# in the "intuitive" outer-first order will silently re-introduce the
# PR #9 Copilot Comment 1 bug (429 responses + CORS preflight 200s
# ship without security headers). CLAUDE.md Critical Gotcha #14 +
# the integration test at
# `backend/tests/integration/test_security_headers.py::test_main_app_user_middleware_outermost_is_security_headers`
# are the canary.

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

# Middleware adds, in INNER → OUTER order (Starlette prepends):
app.middleware("http")(request_logging_middleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_exact_origins,
    allow_origin_regex=settings.cors_combined_regex,  # nullable
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    max_age=3600,
)
app.add_middleware(SecurityHeadersMiddleware)

# Routes
app.include_router(chat.router)
app.include_router(starter_prompts.router)
app.include_router(health.router)
```

### Middleware ordering reasoning

FastAPI / Starlette middleware is **outer-first on request, inner-first
on response**. The order above is deliberate:

1. **`SecurityHeadersMiddleware` outermost** so its headers attach to
   *every* response, including 401/403/429/5xx error responses generated
   by inner middleware.
2. **`CORSMiddleware` next** so preflight (`OPTIONS`) returns *before*
   the rate-limit check fires — browser preflights would otherwise
   trip rate limits unnecessarily.
3. **`SlowAPIMiddleware`** after CORS so legitimate cross-origin
   requests count against the bucket but rejected-origin requests
   don't.
4. **Request-logging middleware innermost** so the `request_id` context
   var is set *before* any route or dependency runs (`require_api_key`
   reads from it).

`Depends(require_api_key)` is per-route, not middleware — that's how
`/health` and `/ready` stay exempt (Fork 40).

---

## Configuration (`config.py`)

```python
# backend/src/customs_agent/config.py
import re
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # === LLM ===
    anthropic_api_key: str
    openai_api_key: str = ""   # build-time only; runtime ignores

    # === Auth (Fork 48) ===
    backend_api_key: str       # required; openssl rand -base64 32

    # === CORS (Fork 38) ===
    allowed_origins: str       # comma-separated; ^…$ entries treated as regex

    # === Observability (Fork 10) ===
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    environment: str = "development"     # "production" switches structlog to JSONRenderer (Fork 54)

    # === Agent tuning (Fork 23) ===
    agent_max_iterations: int = 5
    agent_max_input_tokens_per_turn: int = 50_000
    agent_max_output_tokens_per_turn: int = 8_000

    # === LLM tuning (Fork 26, Fork 5/G1) ===
    llm_model: str = "claude-sonnet-4-6"
    llm_judge_model: str = "gpt-4o-mini"
    llm_embedding_model: str = "text-embedding-3-small"
    llm_temperature: float = 0.0
    llm_seed: int = 42

    # === Rate limit (Fork 47) ===
    ratelimit_enabled: bool = True
    ratelimit_chat_per_minute: int = 20
    ratelimit_starter_prompts_per_minute: int = 60

    # === Safety (Fork 49) ===
    safety_max_user_message_chars: int = 2000
    safety_output_sanity_check_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Derived properties: parse CORS env var into exact + regex pieces
    @property
    def cors_exact_origins(self) -> list[str]:
        entries = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        return [o for o in entries if not (o.startswith("^") and o.endswith("$"))]

    @property
    def cors_combined_regex(self) -> str | None:
        entries = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        patterns = [o for o in entries if o.startswith("^") and o.endswith("$")]
        return "|".join(f"({p})" for p in patterns) if patterns else None


settings = Settings()  # module-level singleton; raises at import if required vars missing
```

Loading from env vars only — never hardcoded keys. See
`07-infrastructure.md` for the platform routing of these vars across
local / Fly / Vercel / GitHub Actions (Fork 39).

---

## Endpoint Inventory

| Endpoint | Method | Auth | Rate limit | Streams? | Body shape | Purpose |
|---|---|---|---|---|---|---|
| `/chat` | POST | ✅ `X-API-Key` | 20/min | No | `ChatRequest` → `ChatResponse` | Non-streaming chat (fallback for SSE-incompatible clients; primary path for eval tests) |
| `/chat/stream` | POST | ✅ `X-API-Key` | 20/min | Yes (SSE) | `ChatRequest` → SSE events terminating in `event: complete` | Primary path for the browser (Fork 29) |
| `/api/starter-prompts` | GET | ✅ `X-API-Key` | 60/min | No | `→ list[StarterPrompt]` | Frontend empty state chips (Fork 30) |
| `/health` | GET | ❌ public | none | No | `→ {"status": "ok"}` | Fly polls every 30s |
| `/ready` | GET | ❌ public | none | No | `→ ReadinessResponse` | CI smoke test post-deploy; manifest exposes deployed version |

Public endpoints (`/health`, `/ready`) deliberately bypass both auth and
rate limit — Fly's health checker can't easily carry the API key, and
self-DoS via polling your own infrastructure is a non-goal.

---

## Per-Endpoint Detail

### `POST /chat` — non-streaming

```python
# backend/src/customs_agent/api/chat.py
#
# Per the implementation locked on `feat/agent-loop`: the FULL set of
# wire-level Pydantic types (Message, ChatRequest, Citation,
# ToolCallTrace, Assumption, RefusalCategory, ResponseMeta, ChatResponse)
# lives in `customs_agent.agent.contracts`. This module is a thin
# FastAPI router that imports the contracts and binds them to the
# routes; PROGRESS.md's "api/chat.py — ChatRequest / ChatResponse"
# checklist item is honored by the re-export shim that also lives in
# `api/chat.py` so callers that want only the request/response surface
# can `from customs_agent.api.chat import ChatRequest, ChatResponse`.

from fastapi import APIRouter, Depends, Request

from customs_agent.agent.bootstrap import AgentContext
from customs_agent.agent.contracts import ChatRequest, ChatResponse
from customs_agent.agent.loop import run_agent
from customs_agent.api._rate_limit import limiter
from customs_agent.api.auth import require_api_key
from customs_agent.config import settings

router = APIRouter()


@router.post("/chat", dependencies=[Depends(require_api_key)])
@limiter.limit(f"{settings.ratelimit_chat_per_minute}/minute")
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    request_id = request.state.request_id   # set by request_logging_middleware
    ctx: AgentContext = request.app.state.agent_ctx   # built once at startup
    return run_agent(
        ctx,
        user_message=body.messages[-1].content,
        history=body.messages[:-1],
        request_id=request_id,
    )
```

(The non-streaming `run_agent` shipped sync on `feat/agent-loop`; the
async streaming variant lands on `feat/streaming` per Fork 29 Phase 1.)

### `POST /chat/stream` — SSE streaming (Fork 29)

Streaming delivered in two phases per Fork 29 + Fork 57. **Phase 0**
(non-streaming JSON) always works as a fallback. **Phase 1** adds final-
answer token streaming. **Phase 2** adds tool-trace events for live
"show your work" population.

#### SSE event taxonomy

| Event name | Payload | Emitted by | Phase |
|---|---|---|---|
| `event: token` | `{"delta": "Pacific"}` | LLM streaming (last LLM call's text content) | 1 |
| `event: knowledge_retrieved` | `{"chunks": [{chunk_id, doc, section}, …]}` | RAG retriever, before first LLM call | 2 |
| `event: tool_call_started` | `{"id": 1, "name": "query_entries", "args": {…}}` | Agent loop, before invoking tool | 2 |
| `event: tool_call_completed` | `{"id": 1, "result_summary": "142", "latency_ms": 8}` | Agent loop, after tool returns | 2 |
| `event: complete` | full `ChatResponse` JSON | Agent loop, after final answer + sidecar assembled | always |
| `event: error` | `{"code": "...", "message": "...", "retry_after"?: N}` | Any uncaught error path | always |

`event: complete` is the source of truth — even if a client misses
earlier events, the final payload reconciles state. The frontend's SSE
consumer (`lib/sse.ts`, see `06-frontend.md`) uses this as the
authoritative state on `complete` and overrides any progressive UI
state with it.

#### Implementation pattern

```python
# backend/src/customs_agent/api/chat.py (streaming endpoint)
import json
from fastapi.responses import StreamingResponse


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/stream", dependencies=[Depends(require_api_key)])
@limiter.limit(f"{settings.ratelimit_chat_per_minute}/minute")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    request_id = request.state.request_id

    async def event_generator():
        try:
            async for ev in run_agent_streaming(
                user_message=body.messages[-1].content,
                history=[m.model_dump() for m in body.messages[:-1]],
                conversation_id=body.conversation_id,
                request_id=request_id,
            ):
                yield _sse(ev.type, ev.payload)
        except Exception as e:
            log.exception("chat_stream.unhandled_error", request_id=request_id)
            yield _sse("error", {"code": "internal_error",
                                 "message": "An unexpected error occurred."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",         # disable nginx-style buffering at Fly's proxy
            "Connection": "keep-alive",
        },
    )
```

The agent's streaming generator (`run_agent_streaming`) wraps Anthropic's
streaming API and re-emits typed events at each agent-loop transition.
See `04-agent-and-tools.md` for the agent loop structure.

### `GET /api/starter-prompts` (Fork 30)

```python
# backend/src/customs_agent/api/starter_prompts.py
from fastapi import APIRouter, Depends, Request
from customs_agent.api.auth import require_api_key
from customs_agent.api._rate_limit import limiter
from customs_agent.config import settings
from customs_agent.config.starter_prompts import STARTER_PROMPTS

router = APIRouter()


@router.get("/api/starter-prompts", dependencies=[Depends(require_api_key)])
@limiter.limit(f"{settings.ratelimit_starter_prompts_per_minute}/minute")
async def get_starter_prompts(request: Request):
    return [p.model_dump() for p in STARTER_PROMPTS]
```

The same `STARTER_PROMPTS` list is imported by the Fork 25 off-domain
refusal handler — single source of truth for "what can the agent answer
about?"

### `GET /health` (Fork 40) — cheap liveness

```python
# backend/src/customs_agent/api/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}
```

No auth, no rate limit, no DB query, no LLM call. Fly polls this every
30 seconds. Returns in <10ms.

### `GET /ready` (Fork 40) — deep readiness + manifest

```python
# backend/src/customs_agent/api/health.py (continued)
import json
from pathlib import Path
from time import perf_counter
from fastapi import Request, Response
from customs_agent.config import settings
from customs_agent.agent.prompt import PROMPT_VERSION

MANIFEST_PATH = Path("/app/manifest.json")   # baked in at Docker build (Fork 17)


@router.get("/ready")
async def ready(request: Request, response: Response):
    t0 = perf_counter()
    checks = {}
    overall_ok = True
    con = request.app.state.db
    retriever = request.app.state.retriever

    # DuckDB
    try:
        n = con.execute("SELECT COUNT(*) FROM entries_v").fetchone()[0]
        checks["duckdb"] = {"ok": True, "entries_count": n}
    except Exception as e:
        checks["duckdb"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # ChromaDB
    try:
        chunk_count = retriever._chroma.count()
        checks["chroma"] = {"ok": chunk_count > 0, "chunk_count": chunk_count}
        if chunk_count == 0:
            overall_ok = False
    except Exception as e:
        checks["chroma"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # BM25 + manifest
    checks["bm25"] = {"ok": retriever._bm25 is not None}
    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}

    checks["manifest"] = {
        "ok": True,
        "prompt_version":  PROMPT_VERSION,
        "model":           settings.llm_model,
        "embedding_model": manifest.get("embedding_model"),
        "chunk_count":     manifest.get("chunk_count"),
        "built_at":        manifest.get("built_at"),
        "agent_max_iterations": settings.agent_max_iterations,
        "temperature":     settings.llm_temperature,
    }

    duration_ms = int((perf_counter() - t0) * 1000)
    if not overall_ok:
        response.status_code = 503

    return {
        "status": "ready" if overall_ok else "degraded",
        "checks": checks,
        "duration_ms": duration_ms,
    }
```

#### Why `/ready` is the canonical "what's deployed?" tool

The response carries `prompt_version`, `model`, `embedding_model`,
`built_at`, `chunk_count`, `temperature`, `agent_max_iterations`. One
curl answers "what version of the agent is currently live?" — useful for
EVALUATION.md run metadata (G5) and post-deploy verification.

**Security note**: `/ready` exposes operational metadata only (counts,
version strings, build timestamp). No secrets, no customer data, no
internal state. Public exposure is intentional and safe.

---

## Middleware Stack

Each middleware is documented in detail in `09-security.md`. Quick
reference of what each does + which fork owns it:

| Middleware | File | Fork | Behavior |
|---|---|---|---|
| `SecurityHeadersMiddleware` | `api/_security_headers.py` | Fork 51 | Adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Strict-Transport-Security: max-age=63072000; includeSubDomains` to every response |
| `CORSMiddleware` (FastAPI built-in) | wired in `main.py` | Fork 38 | Allowlist via `ALLOWED_ORIGINS` env var; exact strings + project-scoped regex for Vercel previews; `allow_credentials=False`; `max_age=3600` for preflight cache |
| `SlowAPIMiddleware` | `api/_rate_limit.py` | Fork 47 | Composite bucket `(api_key_prefix[:8], client_ip)` for authenticated traffic; `anon:<ip>` for anonymous; per-route limits via `@limiter.limit` decorator; custom 429 handler with `Retry-After` header |
| `request_logging_middleware` | `observability/logging.py` | Fork 52 | Generates `request_id` UUID; binds to `ContextVar`; emits `event: request.received` / `request.completed` / `request.failed` stdout JSON lines |

Plus per-route `Depends(require_api_key)` (Fork 48) on protected
endpoints (everything except `/health` and `/ready`).

### `auth.py` (Fork 48)

```python
# backend/src/customs_agent/api/auth.py
from secrets import compare_digest
from fastapi import Header, HTTPException, status
from customs_agent.config import settings


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_api_key",
                    "message": "X-API-Key header required."},
            headers={"WWW-Authenticate": 'ApiKey realm="customs-agent"'},
        )
    if not compare_digest(x_api_key, settings.backend_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "invalid_api_key",
                    "message": "Invalid API key."},
        )
    return x_api_key
```

`compare_digest` is constant-time — prevents timing attacks. Don't
replace with `==` ever.

### Rate limit bucket function (Fork 47)

```python
# backend/src/customs_agent/api/_rate_limit.py
from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from customs_agent.config import settings


def composite_key(request: Request) -> str:
    """Bucket per (API key prefix, client IP) when authenticated;
       by client IP alone when anonymous."""
    api_key = request.headers.get("X-API-Key", "")
    ip = request.client.host if request.client else "unknown"
    return f"{api_key[:8]}:{ip}" if api_key else f"anon:{ip}"


limiter = Limiter(
    key_func=composite_key,
    default_limits=[],                  # opt-in per route via @limiter.limit
    enabled=settings.ratelimit_enabled,
    storage_uri="memory://",            # single-machine; switch to redis:// at multi-machine
)


async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    retry_after = int(getattr(exc, "retry_after", 60))
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        content={
            "error":       "rate_limited",
            "message":     f"Too many requests. Retry in {retry_after} seconds.",
            "retry_after": retry_after,
        },
    )
```

### Security headers (Fork 51)

```python
# backend/src/customs_agent/api/_security_headers.py
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defensive HTTP response headers (Fork 51).

    Server-to-server callers ignore these; browsers honor them and the
    headers close minor attack vectors (MIME sniffing, clickjacking,
    referrer leakage, protocol downgrade).
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"]    = "nosniff"
        response.headers["X-Frame-Options"]           = "DENY"
        response.headers["Referrer-Policy"]           = "no-referrer"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
```

No CSP — backend serves JSON/SSE, not HTML. If we ever serve HTML
directly from Fly (we don't — frontend is on Vercel), CSP becomes
relevant.

---

## Unified Error Response Shapes

Every error path returns a structured JSON body. Frontend `lib/errors.ts`
maps each shape to a toast variant via the G10 table.

| HTTP status | `error.code` | Body | When raised |
|---|---|---|---|
| 401 | `missing_api_key` | `{"error": "missing_api_key", "message": "X-API-Key header required."}` | `require_api_key` — header absent |
| 403 | `invalid_api_key` | `{"error": "invalid_api_key", "message": "Invalid API key."}` | `require_api_key` — header value mismatched |
| 422 | (Pydantic detail) | FastAPI default Pydantic validation error | `ChatRequest` / `EntryFilters` validation fails (e.g., user message > 2000 chars, invalid `customer_code`) |
| 429 | `rate_limited` | `{"error": "rate_limited", "message": "...", "retry_after": N}` + `Retry-After` header | slowapi bucket exceeded |
| 500 | `internal_error` | `{"error": "internal_error", "message": "An unexpected error occurred."}` | Any uncaught exception in the route or agent loop |
| 503 | `not_ready` | from `/ready` body when checks fail | Boot-time subsystem failure (DuckDB / ChromaDB / BM25 not loaded) |

All security headers from `SecurityHeadersMiddleware` apply to every
error response (it's the outermost middleware).

### SSE error events (separate from HTTP status)

For `/chat/stream`, errors mid-stream are surfaced as
`event: error` SSE payloads while the HTTP 200 stays open. This lets the
frontend show a partial response + error toast simultaneously. The
event payload mirrors the HTTP error body shape:

```
event: error
data: {"code": "iteration_limit", "message": "Reached computation budget."}
```

---

## Composition with Other Layers

- **`04-agent-and-tools.md`** — `chat.py` delegates to `run_agent()` /
  `run_agent_streaming()`; the agent owns the response sidecar
  assembly. `ChatResponse` Pydantic model lives in
  `agent/contracts.py`.
- **`02-data-layer.md`** — `lifespan()` calls `load_entries()` →
  `create_views()` → `validate_loaded_data()` at boot; DB connection
  attached to `app.state.db`.
- **`03-rag-layer.md`** — `lifespan()` calls `init_retriever()` which
  loads the baked-in `/app/chroma_db/` + `/app/bm25.pkl`; retriever
  attached to `app.state.retriever`.
- **`06-frontend.md`** — Next.js server-side proxy at
  `app/api/chat/[stream]/route.ts` injects `X-API-Key` and forwards to
  these endpoints. Browser never calls these endpoints directly.
- **`07-infrastructure.md`** — Fly serves this app at
  `customs-agent-backend.fly.dev:8080`; `fly.toml` wires the `/health`
  check; Dockerfile entrypoint is `uvicorn customs_agent.main:app`.
- **`08-cicd-and-testing.md`** — CI smoke tests `/ready` after each
  deploy; the manifest payload from `/ready` is the canonical "what's
  deployed?" surface used in EVALUATION.md.
- **`09-security.md`** — full threat model and per-middleware rationale
  for everything wired here.
- **`10-observability.md`** — `request_logging_middleware` emits stdout
  JSON; `@observe` decorators on the agent loop produce Langfuse traces.

---

## API Versioning (G8)

**No URL or header versioning for the demo.** All endpoints sit at bare
paths (`/chat`, `/chat/stream`, etc.) — not `/v1/chat`. The OpenAPI
contract (G3) regenerated and committed on every change *is* the
version mechanism today; URL versioning becomes valuable when external
API consumers exist and backward compatibility becomes a hard
constraint.

Documented in README's "Design decisions" as a deliberate choice — the
single-consumer architecture (Next.js frontend, server-side proxied)
doesn't need versioning surface. Production future work: `/v1/` prefix
on the FastAPI router, deprecation policy of 6 months minimum, RFC 8594
`Sunset` header on deprecated endpoints, changelog entries cross-
referenced from the OpenAPI spec.

---

## FastAPI Built-in Docs

`/docs` (Swagger UI) and `/redoc` are auto-generated from the OpenAPI
spec. Useful side benefits:

- Reviewers can hit `/docs` to see the full API surface without
  reading code (Communication-rubric win)
- Bench-test endpoints by clicking "Try it out" in Swagger
- Becomes the canonical source for the `openapi.json` snapshot
  exported by `scripts/export_openapi.py` for G3 codegen

For production with sensitive APIs, you'd disable these
(`FastAPI(docs_url=None, redoc_url=None)`). For the demo, leaving them
enabled adds zero risk (the API surface is already disclosed via the
committed `openapi.json`) and earns Communication points.

---

## Future Work

| Item | Trigger |
|---|---|
| URL versioning (`/v1/...`) with `Sunset` header + deprecation policy (G8) | When external API consumers exist |
| `/admin/...` endpoints (e.g., right-to-be-forgotten cascade per Fork 53) | Multi-tenant production |
| `/metrics` Prometheus exporter | When ops adopts Prometheus stack |
| WebSocket transport as SSE alternative | Background-tab throttling becomes a real complaint (G23) |
| Per-request idempotency keys | If retries against `/chat` become routine and side-effects ever appear |
| GraphQL or tRPC endpoints | Multi-frontend product (not applicable here) |
| Server-Sent Events with reconnection / Last-Event-ID | Production-grade streaming reliability |
| Disable `/docs` and `/redoc` in production via env var | Multi-tenant production with sensitive API surface |
