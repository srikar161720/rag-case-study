"""End-to-end ``POST /chat`` round-trip with a stubbed Anthropic client.

Replaces ``app.state.agent_ctx`` for the duration of a test with a
context whose ``client`` is a :class:`FakeAnthropicClient` and whose
``retriever`` is a minimal empty stub. The real DuckDB connection,
tool definitions, and always-on chunk IDs stay intact — only the
network-dependent pieces are mocked.

This covers:

- Happy path: LLM emits a plain text response → 200 with a valid
  :class:`ChatResponse` shape including a ``req_``-prefixed
  ``request_id``, populated ``prompt_version`` and ``model``,
  ``refused=False``.
- Refusal path: LLM prepends the ``<!-- refusal:<category> -->``
  marker → 200 with ``refused=True`` and the category surfaced in
  ``refusal_category``.

Deeper tool-use round-trips are covered by the unit-level agent loop
suite at ``tests/unit/agent/test_loop.py`` — that's the right grain
for asserting tool invocation ordering and the citation marker
machinery. This file proves the HTTP transport and stub-replacement
mechanism work, and that the response body conforms to the wire
contract.
"""

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests._fakes import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeUsage,
)


class _EmptyRetriever:
    """Stub retriever that returns no candidates — keeps the agent
    loop offline by short-circuiting the ChromaDB embedding call."""

    def retrieve(self, query: str, k: int = 5) -> list[Any]:
        return []


@pytest.fixture
def fake_anthropic(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FakeAnthropicClient]:
    """Swap ``app.state.agent_ctx`` with a stub for one test.

    ``monkeypatch.setattr`` auto-restores after the test so the
    session-scoped client's real AgentContext comes back for the
    subsequent integration tests.
    """
    original_ctx = client.app.state.agent_ctx
    fake_client = FakeAnthropicClient()
    stub_ctx = replace(
        original_ctx, client=fake_client, retriever=_EmptyRetriever()
    )
    monkeypatch.setattr(client.app.state, "agent_ctx", stub_ctx)
    yield fake_client


@pytest.mark.integration
def test_chat_simple_text_response_returns_200_and_response_shape(
    client: TestClient,
    valid_headers: dict[str, str],
    fake_anthropic: FakeAnthropicClient,
) -> None:
    """LLM returns a single text block; ``run_agent`` produces a
    valid ChatResponse."""
    fake_anthropic.queue(
        FakeResponse(
            stop_reason="end_turn",
            content=[FakeTextBlock(text="The total entered value was $1.2M.")],
            usage=FakeUsage(input_tokens=120, output_tokens=18),
        )
    )

    response = client.post(
        "/chat",
        headers=valid_headers,
        json={
            "messages": [
                {"role": "user", "content": "What's the total entered value?"}
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()

    # Top-level ChatResponse shape
    assert body["answer"] == "The total entered value was $1.2M."
    assert body["refused"] is False
    assert body["refusal_category"] is None
    assert body["knowledge_citations"] == []
    assert body["tool_calls"] == []
    assert body["assumptions"] == []

    # ResponseMeta — request_id has the canonical ``req_<12 hex>`` shape
    # (Fork 52) stamped by RequestLoggingMiddleware, prompt_version and
    # model are non-empty strings, usage numbers populated from the fake.
    meta = body["meta"]
    assert isinstance(meta["request_id"], str)
    assert meta["request_id"].startswith("req_")
    assert len(meta["request_id"]) == 16  # "req_" + 12 hex chars
    assert isinstance(meta["prompt_version"], str)
    assert meta["model"] == "claude-sonnet-4-6"
    assert meta["temperature"] == 0.0
    assert meta["input_tokens"] == 120
    assert meta["output_tokens"] == 18
    assert meta["iteration_limit_hit"] is False
    assert meta["budget_limit_hit"] is False


@pytest.mark.integration
def test_chat_request_id_is_unique_per_request(
    client: TestClient,
    valid_headers: dict[str, str],
    fake_anthropic: FakeAnthropicClient,
) -> None:
    """Each request gets a fresh ``req_<12 hex>`` id —
    :class:`RequestLoggingMiddleware` is wired and runs per request."""
    fake_anthropic.queue(
        FakeResponse(
            stop_reason="end_turn",
            content=[FakeTextBlock(text="first")],
            usage=FakeUsage(),
        )
    )
    fake_anthropic.queue(
        FakeResponse(
            stop_reason="end_turn",
            content=[FakeTextBlock(text="second")],
            usage=FakeUsage(),
        )
    )

    r1 = client.post(
        "/chat",
        headers=valid_headers,
        json={"messages": [{"role": "user", "content": "first"}]},
    )
    r2 = client.post(
        "/chat",
        headers=valid_headers,
        json={"messages": [{"role": "user", "content": "second"}]},
    )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["meta"]["request_id"] != r2.json()["meta"]["request_id"]


@pytest.mark.integration
def test_chat_refusal_marker_surfaces_in_response(
    client: TestClient,
    valid_headers: dict[str, str],
    fake_anthropic: FakeAnthropicClient,
) -> None:
    """When the LLM emits the hidden ``<!-- refusal:<category> -->``
    marker, the response carries ``refused=True`` and the category
    is surfaced in ``refusal_category``.

    The detector lives at :mod:`customs_agent.agent.refusal`; this
    test proves it's wired into the loop end-to-end (CLAUDE.md
    Critical Gotcha #12)."""
    refusal_text = (
        "<!-- refusal:off_domain -->\n\n"
        "I can only answer questions about customs entry data."
    )
    fake_anthropic.queue(
        FakeResponse(
            stop_reason="end_turn",
            content=[FakeTextBlock(text=refusal_text)],
            usage=FakeUsage(),
        )
    )

    response = client.post(
        "/chat",
        headers=valid_headers,
        json={
            "messages": [
                {"role": "user", "content": "What's the weather like?"}
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["refused"] is True
    assert body["refusal_category"] == "off_domain"
    # The marker itself is stripped from the public answer.
    assert "<!-- refusal" not in body["answer"]


@pytest.mark.integration
def test_app_state_loop_settings_mirrors_settings(client: TestClient) -> None:
    """``app.state.loop_settings`` must be built from the live
    ``Settings`` values at lifespan, not the hardcoded
    ``DEFAULT_LOOP_SETTINGS`` fallback. A future env override of
    ``LLM_MODEL`` / ``AGENT_MAX_ITERATIONS`` / etc. flows through this
    object to ``run_agent``."""
    from customs_agent.config import settings

    ls = client.app.state.loop_settings
    assert ls.model == settings.llm_model
    assert ls.temperature == settings.llm_temperature
    assert ls.max_iterations == settings.agent_max_iterations
    assert ls.max_input_tokens == settings.agent_max_input_tokens_per_turn
    assert ls.max_output_tokens == settings.agent_max_output_tokens_per_turn
    assert ls.embedding_model == settings.llm_embedding_model


@pytest.mark.integration
def test_chat_handler_forwards_loop_settings_to_run_agent(
    client: TestClient,
    valid_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``/chat`` handler must pass ``app.state.loop_settings`` as
    the ``settings=`` kwarg to ``run_agent``. Without this, env-
    overridden ``LLM_MODEL`` / ``AGENT_MAX_ITERATIONS`` etc. would
    silently no-op against ``DEFAULT_LOOP_SETTINGS`` while ``/ready``
    continues to advertise the env values — silent divergence.

    Spies ``customs_agent.api.chat.run_agent`` to capture the kwargs;
    asserts ``settings`` is the SAME object as ``app.state.loop_settings``
    (identity, not equality) so a future refactor that swapped in a
    fresh AgentLoopSettings() at each request would still fail this
    test.
    """
    from customs_agent.agent.contracts import ChatResponse, ResponseMeta

    captured_kwargs: dict[str, object] = {}

    def spy(*args: object, **kwargs: object) -> ChatResponse:
        captured_kwargs.update(kwargs)
        return ChatResponse(
            answer="spy",
            meta=ResponseMeta(
                request_id="test-id",
                prompt_version="test",
                model="test",
                embedding_model="test",
                temperature=0.0,
                iterations_used=0,
            ),
        )

    monkeypatch.setattr("customs_agent.api.chat.run_agent", spy)

    response = client.post(
        "/chat",
        headers=valid_headers,
        json={"messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert "settings" in captured_kwargs
    assert captured_kwargs["settings"] is client.app.state.loop_settings
