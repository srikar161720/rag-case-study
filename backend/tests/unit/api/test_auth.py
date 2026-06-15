"""Unit tests for :mod:`customs_agent.api.auth`.

Exercises :func:`require_api_key` directly as an async callable. The
three branches (missing / invalid / valid) each map to a specific HTTP
status + error code in the body, per the unified error contract in
``context/05-api-and-backend.md``, and the two reject branches each emit
an ``auth.*`` structured event for security forensics.

``require_api_key`` takes a :class:`Request` (FastAPI injects it in
production so the auth events can carry ``client_ip`` + ``path``); the
unit tests pass a minimal hand-built ASGI request via :func:`_make_request`.

The fixture API key value comes from the root ``tests/conftest.py``
env shim (``BACKEND_API_KEY=test-backend-key``) — tests assert against
:data:`customs_agent.config.settings.backend_api_key` directly rather
than hardcoding, so a future change to the shim value doesn't silently
break test correctness.
"""

import pytest
import structlog.testing
from fastapi import HTTPException
from starlette.requests import Request

from customs_agent.api.auth import require_api_key
from customs_agent.config import settings
from customs_agent.observability.events import Events


def _make_request(path: str = "/chat", host: str = "testclient") -> Request:
    """Minimal ASGI :class:`Request` exposing just ``client.host`` +
    ``url.path`` — the two attributes ``require_api_key`` reads for its
    ``auth.*`` log events."""
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": (host, 0),
        }
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_require_api_key_missing_header_raises_401() -> None:
    """``X-API-Key`` absent → 401 ``missing_api_key``."""
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(_make_request(), x_api_key=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == {
        "error": "missing_api_key",
        "message": "X-API-Key header required.",
    }
    # WWW-Authenticate hint exposes the auth scheme to compliant clients.
    assert exc_info.value.headers == {"WWW-Authenticate": 'ApiKey realm="customs-agent"'}


@pytest.mark.asyncio
@pytest.mark.unit
async def test_require_api_key_empty_string_raises_401() -> None:
    """Empty-string header is treated as absent (``not x_api_key`` is True)."""
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(_make_request(), x_api_key="")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "missing_api_key"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_require_api_key_invalid_value_raises_403() -> None:
    """Header present but wrong value → 403 ``invalid_api_key``."""
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(_make_request(), x_api_key="definitely-not-the-real-key")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "error": "invalid_api_key",
        "message": "Invalid API key.",
    }


@pytest.mark.asyncio
@pytest.mark.unit
async def test_require_api_key_valid_value_returns_key() -> None:
    """Header matches ``settings.backend_api_key`` → returns the value."""
    result = await require_api_key(_make_request(), x_api_key=settings.backend_api_key)
    assert result == settings.backend_api_key


@pytest.mark.asyncio
@pytest.mark.unit
async def test_require_api_key_uses_constant_time_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard against accidental regression to ``==`` for the comparison.

    Replaces :func:`secrets.compare_digest` in the auth module with a
    spy and confirms it's invoked. If a future refactor swaps in
    ``==``, this test fails — preserving the timing-attack defense
    discipline.
    """
    calls: list[tuple[str, str]] = []
    original = __import__("customs_agent.api.auth", fromlist=["compare_digest"]).compare_digest

    def spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr("customs_agent.api.auth.compare_digest", spy)
    await require_api_key(_make_request(), x_api_key=settings.backend_api_key)
    assert len(calls) == 1
    # The handler encodes both args to UTF-8 bytes before the compare
    # to dodge the TypeError ``compare_digest`` raises on non-ASCII
    # str inputs — see test_require_api_key_non_ascii_value_returns_403.
    assert calls[0][0] == settings.backend_api_key.encode("utf-8")
    assert calls[0][1] == settings.backend_api_key.encode("utf-8")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_require_api_key_non_ascii_value_returns_403() -> None:
    """Non-ASCII ``X-API-Key`` value follows the invalid-key branch
    (403), NOT the ``TypeError`` path that bare ``compare_digest`` on
    str inputs would raise.

    Before the byte-encoding fix, ``compare_digest("tëst-key", ...)``
    raised ``TypeError("comparing strings with non-ASCII characters is
    not supported")`` and propagated as a 500. The fix encodes both
    args to UTF-8 bytes, which trivially handles any header byte
    sequence and routes wrong-keys through the documented 403 path.
    """
    with pytest.raises(HTTPException) as exc_info:
        await require_api_key(_make_request(), x_api_key="tëst-këy-with-umlauts")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "error": "invalid_api_key",
        "message": "Invalid API key.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# auth.* structured events (Fork 52 taxonomy)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.unit
async def test_missing_key_emits_auth_missing_key_event() -> None:
    """The 401 branch logs ``auth.missing_key`` with client_ip + path."""
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(HTTPException):
            await require_api_key(_make_request(path="/chat"), x_api_key=None)
    events = [e for e in logs if e["event"] == Events.AUTH_MISSING_KEY]
    assert len(events) == 1
    assert events[0]["path"] == "/chat"
    assert events[0]["client_ip"] == "testclient"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_invalid_key_emits_auth_invalid_key_event_with_prefix() -> None:
    """The 403 branch logs ``auth.invalid_key`` with the first-8-char
    prefix of the rejected key (never the full value, Fork 48)."""
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(HTTPException):
            await require_api_key(_make_request(), x_api_key="abcdefgh-wrong-value")
    events = [e for e in logs if e["event"] == Events.AUTH_INVALID_KEY]
    assert len(events) == 1
    assert events[0]["api_key_prefix"] == "abcdefgh"
    assert events[0]["path"] == "/chat"
