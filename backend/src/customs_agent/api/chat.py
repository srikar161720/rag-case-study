"""``POST /chat`` non-streaming endpoint (Fork 23 + 28).

Thin handler that:

1. Reads the per-request ``request_id`` stamped by
   :class:`customs_agent.observability.logging.RequestLoggingMiddleware`
   onto ``request.state``.
2. Reads the singleton :class:`AgentContext` built once at boot by
   :func:`customs_agent.agent.bootstrap.build_agent_context` and stored
   on ``app.state.agent_ctx``.
3. Forwards to :func:`customs_agent.agent.loop.run_agent` — the sync
   orchestrator that owns the tool-calling loop, citation marker
   stripping, refusal detection, and sidecar assembly. ``run_agent``
   never raises (graceful degradation via the three "limit hit" flags
   on :class:`ResponseMeta`), so this handler never needs its own
   try/except.

The contract types (:class:`ChatRequest`, :class:`ChatResponse`) live
in :mod:`customs_agent.agent.contracts` next to the producer that
constructs them; this module re-exports them so the historical import
path ``from customs_agent.api.chat import ChatRequest, ChatResponse``
keeps working (preserving the PROGRESS.md ``api/chat.py`` named-export
checklist item).

The streaming variant (``POST /chat/stream``) lands on
``feat/streaming`` per Fork 29 Phase 1.
"""

from fastapi import APIRouter, Depends, Request

from customs_agent.agent.bootstrap import AgentContext
from customs_agent.agent.contracts import ChatRequest, ChatResponse
from customs_agent.agent.loop import AgentLoopSettings, run_agent
from customs_agent.api._rate_limit import limiter
from customs_agent.api.auth import require_api_key
from customs_agent.config import settings

router = APIRouter()


@router.post("/chat", dependencies=[Depends(require_api_key)])
@limiter.limit(f"{settings.ratelimit_chat_per_minute}/minute")
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Forward the user turn to :func:`run_agent` and return its
    :class:`ChatResponse` verbatim.

    The slowapi decorator inspects ``request`` to compute the bucket
    key — the parameter is required by the decorator contract even
    though the handler body doesn't otherwise need the raw request
    object beyond the ``app.state`` and ``state.request_id`` reads.

    ``app.state.loop_settings`` is built once at lifespan startup from
    the live ``Settings`` values; passing it as ``settings=`` to
    ``run_agent`` keeps env-overridden ``LLM_MODEL`` /
    ``AGENT_MAX_ITERATIONS`` etc. live in the loop rather than no-oping
    against the hardcoded ``DEFAULT_LOOP_SETTINGS``.
    """
    request_id: str = request.state.request_id
    ctx: AgentContext = request.app.state.agent_ctx
    loop_settings: AgentLoopSettings = request.app.state.loop_settings
    return run_agent(
        ctx,
        user_message=body.messages[-1].content,
        history=list(body.messages[:-1]),
        request_id=request_id,
        settings=loop_settings,
    )


__all__ = ["ChatRequest", "ChatResponse", "router"]
