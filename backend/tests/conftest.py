"""Root-level test configuration.

Sets safe defaults for the required Settings env vars BEFORE any
``customs_agent.*`` import happens at test collection. From this branch
forward, importing ``customs_agent.config`` instantiates a module-level
``settings = Settings()`` singleton; without these defaults, a clean
developer checkout (no ``.env`` exported into the shell) would fail
collection with ``pydantic.ValidationError``.

``os.environ.setdefault`` respects values set by the real environment
(``.env`` loaded via shell, CI secrets, etc.) — it only fills in when
the variable is absent. The placeholder values below are deliberately
identifiable as test fixtures.

``RATELIMIT_ENABLED=false`` makes the module-level
``customs_agent.api._rate_limit.limiter`` no-op all
``@limiter.limit(...)`` decorators for the entire suite. The chunk-3b
``tests/integration/test_rate_limit.py`` builds its own ``Limiter``
instance with ``enabled=True`` plus tiny per-route limits — that's the
only place the rate-limit machinery is exercised under load.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("BACKEND_API_KEY", "test-backend-key")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("RATELIMIT_ENABLED", "false")
# OPENAI_API_KEY is read directly by ``customs_agent.rag.retriever``'s
# ChromaDB embedding-function constructor at app boot — chromadb 0.5+
# raises ``ValueError("CHROMA_OPENAI_API_KEY environment variable is
# not set")`` when the constructor receives an empty string AND the
# fallback env var is also absent. The placeholder below satisfies the
# constructor; tests never actually call ``.retrieve()`` against the
# real OpenAI embeddings API (the integration suite stubs the retriever
# on the agent context when /chat round-trips are tested).
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
