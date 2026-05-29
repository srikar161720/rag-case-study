"""Shared fixtures for ``tests/integration/``.

The integration suite exercises the full FastAPI app end-to-end via a
session-scoped :class:`fastapi.testclient.TestClient`. Lifespan boots
once for the whole session (CSV load + views + RAG retriever from
artifacts + Anthropic client + AgentContext), so per-test cost is
just a TestClient request roundtrip (~1 ms).

Rate-limiting is GLOBALLY disabled for the suite via the
``RATELIMIT_ENABLED=false`` shim in ``tests/conftest.py``. The
chunk-3b ``test_rate_limit.py`` builds its own ``Limiter`` instance
with ``enabled=True`` plus tiny per-route limits to exercise the
machinery — that is the only place the limit-state matters.

Two fixtures:

- :func:`client` — session-scoped :class:`TestClient` wrapping
  :data:`customs_agent.main.app`. The ``with`` statement triggers the
  Starlette lifespan context manager so the data layer, retriever, and
  agent context are all loaded.
- :func:`valid_headers` — function-scoped dict including the
  ``X-API-Key`` matching ``settings.backend_api_key``. Tests apply it
  to authenticated routes.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from customs_agent.config import settings
from customs_agent.main import app


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """Session-scoped TestClient. Lifespan runs once.

    Using TestClient as a context manager (the ``with`` statement)
    triggers Starlette's lifespan boot — without it the app would skip
    the boot wiring entirely and ``request.app.state.*`` reads would
    raise ``AttributeError`` on first use.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_headers() -> dict[str, str]:
    """Headers including the X-API-Key matching the test shim's value."""
    return {"X-API-Key": settings.backend_api_key}
