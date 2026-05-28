"""Root-level test configuration.

Sets safe defaults for the three required Settings env vars BEFORE any
``customs_agent.*`` import happens at test collection. From this branch
forward, importing ``customs_agent.config`` instantiates a module-level
``settings = Settings()`` singleton; without these defaults, a clean
developer checkout (no ``.env`` exported into the shell) would fail
collection with ``pydantic.ValidationError``.

``os.environ.setdefault`` respects values set by the real environment
(``.env`` loaded via shell, CI secrets, etc.) — it only fills in when
the variable is absent. The placeholder values below are deliberately
identifiable as test fixtures.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("BACKEND_API_KEY", "test-backend-key")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")
