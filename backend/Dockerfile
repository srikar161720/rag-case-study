# syntax=docker/dockerfile:1.7
# backend/Dockerfile — multi-stage Python build for the Customs Analytics Agent.
# Build context: backend/ (per Fork 35 — data/ and knowledge/ live inside backend/)

# ============================================================================
# Stage 1: Builder — install Python deps + build RAG index (Fork 17)
# ============================================================================
FROM python:3.12-slim AS builder

# Install uv (10-100x faster than pip)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Use the system Python across both stages. uv defaults to a managed
# (downloaded) interpreter; the runtime stage copies only /app/.venv, so a
# managed interpreter would leave the venv's bin/python symlink dangling in
# the final image. Pinning to the system Python (present in python:3.12-slim)
# keeps the copied venv valid. (Per the official uv Docker guide.)
ENV UV_PYTHON_DOWNLOADS=0

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
LABEL org.opencontainers.image.source="https://github.com/srikar161720/rag-case-study" \
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
