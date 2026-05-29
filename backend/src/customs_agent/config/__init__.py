"""Public façade of the ``customs_agent.config`` package.

Re-exports the canonical names so consumers continue writing
``from customs_agent.config import settings`` — the module-to-package
conversion on ``feat/fastapi-backend`` (this branch) is transparent to
all prior imports.

Three names are re-exported:

- :class:`Settings` — the Pydantic-settings model
  (in :mod:`customs_agent.config._settings`).
- :data:`settings` — the module-level singleton, instantiated at first
  import. Raises ``pydantic.ValidationError`` immediately if the three
  required env vars (``ANTHROPIC_API_KEY``, ``BACKEND_API_KEY``,
  ``ALLOWED_ORIGINS``) are absent.
- :data:`MANIFEST_PATH` — resolves to the production Docker path
  (``/app/manifest.json``) when present, else the local-dev fallback
  next to the build artifacts (``backend/manifest.json``). Used by
  :mod:`customs_agent.api.health`'s ``/ready`` handler; tests
  monkeypatch this constant rather than crafting their own path logic.

The :mod:`customs_agent.config.starter_prompts` submodule holds the
6 empty-state chip definitions (Fork 30) and is not re-exported here —
consumers import from the explicit submodule path.
"""

from pathlib import Path

from customs_agent.config._settings import Settings

# Module-level singleton. Constructed at import time; raises pydantic
# ``ValidationError`` immediately on a missing required env var so the
# app fails loudly at boot rather than 500-ing later under traffic.
# mypy strict can't see that pydantic-settings populates required fields
# from the environment — the call-arg ignore is the canonical workaround.
settings: Settings = Settings()  # type: ignore[call-arg]


# Resolve the build manifest. Docker bakes it at ``/app/manifest.json``
# (Fork 17). Locally the file lives next to the chroma_db/ and bm25.pkl
# build artifacts at ``backend/manifest.json``. The /ready handler
# tolerates a missing manifest by returning partial fields with None
# values, so a missing local file is not a boot blocker.
_DOCKER_MANIFEST = Path("/app/manifest.json")
_LOCAL_MANIFEST = Path(__file__).resolve().parents[3] / "manifest.json"
MANIFEST_PATH: Path = _DOCKER_MANIFEST if _DOCKER_MANIFEST.exists() else _LOCAL_MANIFEST


__all__ = ["MANIFEST_PATH", "Settings", "settings"]
