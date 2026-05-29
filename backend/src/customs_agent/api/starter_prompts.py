"""``GET /api/starter-prompts`` endpoint (Fork 30).

Returns the six empty-state chip definitions to the frontend. Both
authenticated (``Depends(require_api_key)``) and rate-limited
(``ratelimit_starter_prompts_per_minute``, default 60/min — cheaper
than the LLM-bearing ``/chat`` cap of 20/min since this endpoint
returns a static list with no inference cost).

The same :data:`STARTER_PROMPTS` list will later be imported by the
Fork 25 off-domain refusal handler so refusal messages can suggest
concrete in-scope examples.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from customs_agent.api._rate_limit import limiter
from customs_agent.api.auth import require_api_key
from customs_agent.config import settings
from customs_agent.config.starter_prompts import STARTER_PROMPTS

router = APIRouter()


@router.get("/api/starter-prompts", dependencies=[Depends(require_api_key)])
@limiter.limit(f"{settings.ratelimit_starter_prompts_per_minute}/minute")
async def get_starter_prompts(request: Request) -> list[dict[str, Any]]:
    """Return the 6 starter-prompt chips as a JSON list.

    ``request`` is required by the slowapi decorator (it inspects the
    request object to compute the bucket key) but is otherwise unused
    by the handler body.
    """
    return [p.model_dump() for p in STARTER_PROMPTS]
