"""Integration tests for ``GET /api/starter-prompts`` (Fork 30).

End-to-end of the empty-state-chip endpoint:

- Returns 200 + 6 chip objects with the full ``StarterPrompt`` shape
  when a valid ``X-API-Key`` is supplied.
- Returns 401 without the header (the ``Depends(require_api_key)`` on
  the route is enforced).
- Returns 403 with a wrong key value.

The chip-config data contract itself (count = 6, no oversized titles,
all tiers covered, etc.) is unit-tested at
``tests/unit/api/test_starter_prompts_config.py`` — this file only
covers the HTTP delivery surface.
"""

import pytest
from fastapi.testclient import TestClient

from customs_agent.config.starter_prompts import STARTER_PROMPTS


@pytest.mark.integration
def test_starter_prompts_returns_all_chips(
    client: TestClient, valid_headers: dict[str, str]
) -> None:
    """200 + list of 6 chips with the expected ``StarterPrompt`` shape."""
    response = client.get("/api/starter-prompts", headers=valid_headers)
    assert response.status_code == 200
    body = response.json()

    # Cardinality matches the static config.
    assert isinstance(body, list)
    assert len(body) == len(STARTER_PROMPTS)
    assert len(body) == 6

    # Each chip carries the 5 declared StarterPrompt fields.
    expected_keys = {"id", "title", "prompt", "category", "tier"}
    for chip in body:
        assert set(chip.keys()) == expected_keys


@pytest.mark.integration
def test_starter_prompts_payload_matches_static_config(
    client: TestClient, valid_headers: dict[str, str]
) -> None:
    """The serialized response is the literal ``model_dump()`` of each
    chip — sanity check that the handler isn't dropping or re-shaping
    fields in flight."""
    response = client.get("/api/starter-prompts", headers=valid_headers)
    expected = [p.model_dump() for p in STARTER_PROMPTS]
    assert response.json() == expected


@pytest.mark.integration
def test_starter_prompts_requires_api_key(client: TestClient) -> None:
    """No ``X-API-Key`` → 401 missing_api_key."""
    response = client.get("/api/starter-prompts")
    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["error"] == "missing_api_key"


@pytest.mark.integration
def test_starter_prompts_rejects_invalid_key(client: TestClient) -> None:
    """Wrong ``X-API-Key`` value → 403 invalid_api_key."""
    response = client.get(
        "/api/starter-prompts", headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 403
    body = response.json()
    assert body["detail"]["error"] == "invalid_api_key"


@pytest.mark.integration
def test_starter_prompts_carries_security_headers(
    client: TestClient, valid_headers: dict[str, str]
) -> None:
    """Security middleware stamps headers on the 200 happy path."""
    response = client.get("/api/starter-prompts", headers=valid_headers)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
