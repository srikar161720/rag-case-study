"""Integration tests for ``GET /ready`` (Fork 40).

Covers the happy path (all subsystems loaded; 200 + manifest fields
populated from ``backend/manifest.json``) plus the two failure paths
the spec calls out:

- Chroma collection unreachable → 503 ``status: "degraded"``,
  ``checks.chroma.ok = False``.
- DuckDB connection unreachable → 503 ``status: "degraded"``,
  ``checks.duckdb.ok = False``.

Failure paths use ``monkeypatch.setattr`` so the mutation is
automatically restored after each test — keeping the
session-scoped TestClient state hermetic for the other
integration tests.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_ready_happy_path_returns_ready(client: TestClient) -> None:
    """All subsystems loaded → 200 + ``status: "ready"``."""
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["duration_ms"] >= 0


@pytest.mark.integration
def test_ready_duckdb_check_carries_entry_count(client: TestClient) -> None:
    """``checks.duckdb.ok = True`` + ``entries_count = 1200`` (matches
    the validated dataset constant)."""
    response = client.get("/ready")
    checks = response.json()["checks"]
    assert checks["duckdb"]["ok"] is True
    assert checks["duckdb"]["entries_count"] == 1200


@pytest.mark.integration
def test_ready_chroma_check_carries_chunk_count(client: TestClient) -> None:
    """``checks.chroma.ok = True`` + positive ``chunk_count`` (the
    actual value is set by ``make build-index``; we just require >0)."""
    response = client.get("/ready")
    checks = response.json()["checks"]
    assert checks["chroma"]["ok"] is True
    assert checks["chroma"]["chunk_count"] > 0


@pytest.mark.integration
def test_ready_bm25_check_ok(client: TestClient) -> None:
    """``checks.bm25.ok = True`` — presence check only."""
    response = client.get("/ready")
    checks = response.json()["checks"]
    assert checks["bm25"]["ok"] is True


@pytest.mark.integration
def test_ready_manifest_carries_prompt_version_and_model(
    client: TestClient,
) -> None:
    """Manifest passthrough: ``PROMPT_VERSION`` from
    ``customs_agent.agent.prompt`` + ``llm_model`` from Settings."""
    response = client.get("/ready")
    manifest = response.json()["checks"]["manifest"]
    assert manifest["ok"] is True
    assert isinstance(manifest["prompt_version"], str)
    assert len(manifest["prompt_version"]) > 0
    assert manifest["model"] == "claude-sonnet-4-6"


@pytest.mark.integration
def test_ready_manifest_includes_build_fields_when_local_manifest_present(
    client: TestClient,
) -> None:
    """When ``backend/manifest.json`` exists (it does locally;
    ``make build-index`` produces it), the build fields are
    populated from the JSON: ``embedding_model``, ``chunk_count``,
    ``built_at``."""
    response = client.get("/ready")
    manifest = response.json()["checks"]["manifest"]
    # These three come from the manifest file's JSON; the test
    # tolerates None for forward compat with a Docker image where the
    # file might be at a different path. Local-dev tests should
    # populate them.
    if manifest["embedding_model"] is not None:
        assert manifest["embedding_model"] == "text-embedding-3-small"
        assert isinstance(manifest["chunk_count"], int)
        assert manifest["chunk_count"] > 0
        assert isinstance(manifest["built_at"], str)


@pytest.mark.integration
def test_ready_returns_503_when_chroma_count_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the chroma collection raises on ``.count()``, the chroma
    check fails and ``/ready`` returns 503 ``status: "degraded"``.

    ``monkeypatch`` auto-restores after the test so subsequent
    integration tests see the healthy session-scoped retriever.
    """

    def boom() -> int:
        raise RuntimeError("simulated chroma failure")

    monkeypatch.setattr(
        client.app.state.retriever._chroma, "count", boom, raising=False
    )

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["chroma"]["ok"] is False
    assert "simulated chroma failure" in body["checks"]["chroma"]["error"]


@pytest.mark.integration
def test_ready_returns_503_when_duckdb_query_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the DuckDB connection raises on ``.execute(...)``, the
    duckdb check fails and ``/ready`` returns 503.

    DuckDB's ``DuckDBPyConnection`` is a C extension with read-only
    attributes, so we can't ``monkeypatch.setattr(con, "execute", ...)``
    — instead we swap the whole ``app.state.db`` attribute with a stub
    that has a raising ``execute``. ``monkeypatch.setattr`` on
    ``app.state`` works because Starlette's ``State`` is a plain
    namespace.
    """

    class _RaisingConnection:
        def execute(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError("simulated duckdb failure")

    monkeypatch.setattr(client.app.state, "db", _RaisingConnection())

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["duckdb"]["ok"] is False
    assert "simulated duckdb failure" in body["checks"]["duckdb"]["error"]


@pytest.mark.integration
def test_ready_returns_503_when_bm25_is_none(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``retriever._bm25 is None`` (incomplete boot, future regression)
    must flip ``overall_ok=False`` → 503, not silently report 200 with
    a quietly-broken BM25 subsystem. Mirrors the chroma block's
    ``chunk_count == 0 → degraded`` pattern.
    """
    monkeypatch.setattr(client.app.state.retriever, "_bm25", None)

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["bm25"]["ok"] is False


@pytest.mark.integration
def test_ready_returns_503_when_manifest_malformed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A present-but-corrupt manifest must degrade ``/ready`` to 503,
    not 500. Without the ``try/except`` around the manifest
    read+parse, ``json.JSONDecodeError`` would propagate out of the
    handler as an unhandled 500 — breaking the readiness contract
    (``503 on ANY subsystem trouble``) that the chroma + duckdb
    blocks already honor.
    """
    bad_path = tmp_path / "manifest.json"
    bad_path.write_text("{this is not json")
    monkeypatch.setattr("customs_agent.api.health.MANIFEST_PATH", bad_path)

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["manifest"]["ok"] is False
    assert "error" in body["checks"]["manifest"]
