"""FastAPI application — entry point for ``uvicorn customs_agent.main:app``.

Three responsibilities:

1. **Lifespan boot wiring**: load the CSV → DuckDB in-memory →
   materialize the analytical views → validate → instantiate the
   hybrid RAG retriever from the baked-in artifacts → instantiate the
   Anthropic client → assemble the singleton :class:`AgentContext`.
   All four artifacts attach to ``app.state`` so the route handlers
   read them via ``request.app.state.*`` without re-doing the boot
   work per request.

2. **Middleware stack** (outer → inner on request, reverse on
   response):

   - :class:`SecurityHeadersMiddleware` — 4 defensive headers on every
     response including 4xx/5xx error paths (Fork 51).
   - :class:`CORSMiddleware` — origin allowlist from
     ``settings.cors_exact_origins`` + ``cors_combined_regex``
     (Fork 38). ``allow_credentials=False`` since the proxy injects
     the API key server-side; ``max_age=3600`` caches preflight.
   - :class:`SlowAPIMiddleware` — rate limit enforcement per-route via
     ``@limiter.limit`` decorators (Fork 47). Limiter +
     ``RateLimitExceeded`` handler are wired alongside.
   - :class:`RequestLoggingMiddleware` — binds ``request_id`` to
     ``request.state`` + a structlog contextvar and emits the
     ``request.received`` / ``request.completed`` / ``request.failed``
     stdout events (Fork 52). Replaces the interim ``RequestIdMiddleware``.

3. **Router includes** — the 4 endpoint routers under ``api/``:
   ``chat`` (POST /chat), ``starter_prompts`` (GET /api/starter-prompts),
   ``health`` (GET /health + /ready).

The ``/chat/stream`` SSE variant (Fork 29) lands on ``feat/streaming``;
the streaming handler will register against the same ``chat`` router.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from anthropic import Anthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from customs_agent.agent.bootstrap import build_agent_context
from customs_agent.agent.loop import AgentLoopSettings
from customs_agent.api import chat, health, starter_prompts
from customs_agent.api._rate_limit import custom_rate_limit_handler, limiter
from customs_agent.api._security_headers import SecurityHeadersMiddleware
from customs_agent.config import settings
from customs_agent.data.load import load_entries
from customs_agent.data.validation import validate_loaded_data
from customs_agent.data.views import create_views
from customs_agent.observability.logging import (
    RequestLoggingMiddleware,
    configure_logging,
)
from customs_agent.rag.chunker import parse_chunks
from customs_agent.rag.retriever import HybridRetriever

# Configure structlog ONCE at import (CLAUDE.md Gotcha #11). Every
# ``structlog.get_logger()`` caller — including the boot-time
# ``data.validation.complete`` event emitted inside ``lifespan`` below —
# then picks up the dev/prod renderer split + secret scrubber +
# request-context binding automatically. ``ENVIRONMENT=production``
# (set in ``fly.toml``) renders one-line JSON for ``fly logs``; local dev
# renders pretty colored console output.
configure_logging(settings.environment)

# Resolve the build-artifact root. Docker bakes them at ``/app/``
# (Fork 17, ``chore/dockerfile-fly`` ships the COPY); locally the
# artifacts live under ``backend/`` next to ``manifest.json``. We
# pick the Docker path when present, walk up to ``backend/`` otherwise.
# ``main.py`` lives at ``backend/src/customs_agent/main.py`` → parents[2]
# is ``backend/``.
_DOCKER_ROOT = Path("/app")
_LOCAL_ROOT = Path(__file__).resolve().parents[2]
_ARTIFACT_ROOT: Path = (
    _DOCKER_ROOT if (_DOCKER_ROOT / "chroma_db").exists() else _LOCAL_ROOT
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot the in-memory data layer + RAG retriever + agent context.

    Runs once at app startup (Starlette's ``async with`` contract).
    Order matters: views require the base table; validation requires
    the views; the agent context requires the retriever and the
    Anthropic client.
    """
    # 1. Data layer — CSV → typed table → views → validation
    con = duckdb.connect(":memory:")
    load_entries(con)
    create_views(con)
    validate_loaded_data(con)
    app.state.db = con

    # 2. RAG retriever — load chunks + ChromaDB collection + BM25.
    # pydantic-settings reads ``.env`` into ``Settings`` but does NOT
    # export to ``os.environ``. chromadb's ``OpenAIEmbeddingFunction``
    # reads ``OPENAI_API_KEY`` from ``os.environ`` directly at
    # construction (and raises if absent), so we copy the value across
    # here. In production (Fly) the env var is set by ``fly secrets``
    # and this assignment is a no-op (setdefault respects existing
    # values).
    if settings.openai_api_key:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
    chunks = parse_chunks()
    retriever = HybridRetriever.from_artifacts(
        chunks=chunks,
        chroma_path=_ARTIFACT_ROOT / "chroma_db",
        bm25_path=_ARTIFACT_ROOT / "bm25.pkl",
    )
    app.state.retriever = retriever

    # 3. Anthropic client + frozen AgentContext (tool defs, always-on
    # chunk IDs all baked once here so per-request handlers don't redo
    # any of this work).
    client = Anthropic(api_key=settings.anthropic_api_key)
    app.state.agent_ctx = build_agent_context(con, retriever, client)

    # 4. AgentLoopSettings built from the live Settings values so
    # env-overridden LLM_MODEL / AGENT_MAX_* etc. flow through to
    # run_agent instead of silently no-oping against the hardcoded
    # DEFAULT_LOOP_SETTINGS. The /chat handler reads this off
    # app.state and forwards as the ``settings=`` kwarg.
    app.state.loop_settings = AgentLoopSettings(
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_iterations=settings.agent_max_iterations,
        max_input_tokens=settings.agent_max_input_tokens_per_turn,
        max_output_tokens=settings.agent_max_output_tokens_per_turn,
        embedding_model=settings.llm_embedding_model,
    )

    try:
        yield
    finally:
        # Defensive close — guards against tests that patch app.state.db
        # to a stub without a .close() method (the Plan agent's landmine
        # #3 mitigation).
        getattr(con, "close", lambda: None)()


app = FastAPI(
    title="Customs Analytics Agent",
    version="1.0.0",
    lifespan=lifespan,
    # /docs and /redoc deliberately left enabled — the API surface is
    # already disclosed via the committed openapi.json (G3), and the
    # auto-generated docs give reviewers a low-friction read of the
    # contract. Disable in a future multi-tenant production.
)

# ─────────────────────────────────────────────────────────────────────────────
# Middleware stack (outer → inner on request, reverse on response)
# ─────────────────────────────────────────────────────────────────────────────
#
# Ordering reasoning (full rationale in context/05-api-and-backend.md):
# 1. SecurityHeadersMiddleware outermost — its headers must stamp every
#    response, including 401/403/429/5xx errors from inner layers AND
#    short-circuit responses (CORS preflight, slowapi 429) that never
#    reach the route handler.
# 2. CORSMiddleware next so preflight OPTIONS returns BEFORE rate limit
#    fires (browsers preflighting shouldn't trip the bucket).
# 3. SlowAPIMiddleware after CORS so rejected-origin requests don't
#    count against the bucket.
# 4. RequestLoggingMiddleware innermost so request.state.request_id is set
#    BEFORE any route or dependency runs.
#
# Starlette's ``app.add_middleware()`` does ``user_middleware.insert(0, ...)``
# — every call PREPENDS. Net effect: the LAST ``add_middleware`` call
# wraps OUTERMOST and the FIRST call wraps INNERMOST among user
# middlewares. The add order below is therefore the REVERSE of the
# request execution order above: RequestLogging added first → innermost;
# SEM added last → outermost. The middleware-order assertion in
# tests/integration/test_security_headers.py guards against accidental
# regression here.

# slowapi state setup must happen BEFORE ``add_middleware(SlowAPIMiddleware)``:
# the middleware reads ``app.state.limiter`` at request time, and the
# exception handler must be registered before any rate-limited response
# can land. These three lines together are slowapi's required wiring.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)  # type: ignore[arg-type]

# Middleware adds, in INNER → OUTER order (Starlette prepends):
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_exact_origins,
    allow_origin_regex=settings.cors_combined_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
    max_age=3600,
)
app.add_middleware(SecurityHeadersMiddleware)

# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

app.include_router(chat.router)
app.include_router(starter_prompts.router)
app.include_router(health.router)
