"""Public re-export of the ``/chat`` request and response contracts (Fork 28).

The agent's primary data model lives in
:mod:`customs_agent.agent.contracts`. This module exists so PROGRESS.md's
``api/chat.py`` named-export checklist item is honored without duplicating
type definitions, and so the FastAPI route function that lands on
``feat/fastapi-backend`` has a conventional import path::

    from customs_agent.api.chat import ChatRequest, ChatResponse

If new request/response types ever need to be added that don't belong in
the agent layer (e.g., endpoint-specific query params), they go here
directly. Today, only the two top-level wire types route through this
shim.
"""

from customs_agent.agent.contracts import ChatRequest, ChatResponse

__all__ = ["ChatRequest", "ChatResponse"]
