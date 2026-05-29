"""Health + readiness endpoints (Fork 40).

Two routes, both public (no auth, no rate limit):

- ``GET /health`` — cheap liveness probe. Returns
  ``{"status": "ok"}`` in <10 ms. Fly polls this every 30 seconds.
- ``GET /ready`` — deep readiness + build manifest. Verifies DuckDB,
  ChromaDB, and BM25 are all loaded; exposes
  ``prompt_version``, ``model``, ``embedding_model``, ``chunk_count``,
  ``built_at``, ``temperature``, ``agent_max_iterations`` from the
  baked-in manifest. Returns 503 when any subsystem check fails.

``/ready`` is the canonical "what's deployed?" surface: one ``curl``
answers what version of the agent is currently live, useful for
EVALUATION.md run metadata (G5) and post-deploy verification.

Public exposure is intentional and safe — the response is operational
metadata only (counts, version strings, build timestamp). No secrets,
no customer data, no internal state. Both endpoints deliberately omit
:func:`Depends(require_api_key)` so Fly's health checker (which can't
easily carry a header) keeps working.
"""

import json
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Request, Response

from customs_agent.agent.prompt import PROMPT_VERSION
from customs_agent.config import MANIFEST_PATH, settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Cheap liveness probe — no DB, no auth, no LLM. <10 ms."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, Any]:
    """Deep readiness probe with build manifest passthrough.

    Per-subsystem checks: DuckDB row count, ChromaDB chunk count,
    BM25 loaded flag, manifest payload. Returns 503 if any check fails.
    """
    t0 = perf_counter()
    checks: dict[str, Any] = {}
    overall_ok = True

    # DuckDB
    try:
        con = request.app.state.db
        n = con.execute("SELECT COUNT(*) FROM entries_v").fetchone()[0]
        checks["duckdb"] = {"ok": True, "entries_count": int(n)}
    except Exception as e:  # pragma: no cover — defensive
        checks["duckdb"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # ChromaDB
    try:
        retriever = request.app.state.retriever
        chunk_count = retriever._chroma.count()
        checks["chroma"] = {"ok": chunk_count > 0, "chunk_count": int(chunk_count)}
        if chunk_count == 0:
            overall_ok = False
    except Exception as e:  # pragma: no cover — defensive
        checks["chroma"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # BM25 — presence check only. A None ``_bm25`` (incomplete boot,
    # future regression) is a degraded state worth surfacing in the
    # readiness contract — mirrors the ``chunk_count == 0 → overall_ok
    # = False`` flip in the chroma block above.
    try:
        retriever = request.app.state.retriever
        bm25_ok = retriever._bm25 is not None
        checks["bm25"] = {"ok": bm25_ok}
        if not bm25_ok:
            overall_ok = False
    except Exception as e:  # pragma: no cover — defensive
        checks["bm25"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # Build manifest passthrough. A missing manifest stays non-fatal
    # (Docker bakes one but local dev may not have run ``make
    # build-index`` yet — manifest fields surface as None and ``ok``
    # stays True). A present-but-corrupt manifest is a real subsystem
    # failure and degrades to 503 in the same shape as the other
    # checks, so the /ready contract holds: 503 on ANY subsystem
    # trouble, including a malformed manifest.
    try:
        if MANIFEST_PATH.exists():
            manifest = json.loads(MANIFEST_PATH.read_text())
        else:
            manifest = {}
        checks["manifest"] = {
            "ok": True,
            "prompt_version": PROMPT_VERSION,
            "model": settings.llm_model,
            "embedding_model": manifest.get("embedding_model"),
            "chunk_count": manifest.get("chunk_count"),
            "built_at": manifest.get("built_at"),
            "agent_max_iterations": settings.agent_max_iterations,
            "temperature": settings.llm_temperature,
        }
    except Exception as e:  # pragma: no cover — defensive
        checks["manifest"] = {"ok": False, "error": str(e)}
        overall_ok = False

    duration_ms = int((perf_counter() - t0) * 1000)
    if not overall_ok:
        response.status_code = 503

    return {
        "status": "ready" if overall_ok else "degraded",
        "checks": checks,
        "duration_ms": duration_ms,
    }
