"""Build-time RAG indexer (Fork 17).

Emits three artifacts that are baked into the Docker image and read at
runtime:

* ``chroma_db/``      — persistent ChromaDB collection ``"knowledge"`` of
                        ~40 chunks embedded via OpenAI
                        ``text-embedding-3-small``.
* ``bm25.pkl``        — pickled :class:`rank_bm25.BM25Okapi` over the same
                        chunks, tokenized via :mod:`customs_agent.rag._tokenize`
                        so the build-time and runtime tokenizers agree
                        byte-for-byte.
* ``manifest.json``   — build metadata (embedding model, indexer version,
                        UTC timestamp, chunk count, sorted chunk IDs, and a
                        SHA-256 per source ``.txt``). Surfaced by the
                        ``/ready`` endpoint on ``feat/fastapi-backend`` and
                        baked into EVALUATION.md run metadata on
                        ``feat/remaining-tools-and-eval``.

``OPENAI_API_KEY`` is the only secret required and is read via a tiny
:class:`pydantic_settings.BaseSettings` subclass that loads
``backend/.env`` (so ``make build-index`` works locally without a shell
``export``). In Docker, the key is mounted via
``--mount=type=secret,id=openai_key`` so it never lands in any image
layer (Fork 17).

The script is idempotent: existing ``chroma_db/`` is removed before
re-indexing so a stale collection name can't pollute a fresh build.
``bm25.pkl`` and ``manifest.json`` overwrite atomically.

Run via::

    make build-index
    # or
    cd backend && uv run python -m scripts.build_index
"""

import argparse
import hashlib
import json
import os
import pickle
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import chromadb
import structlog
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from pydantic_settings import BaseSettings, SettingsConfigDict
from rank_bm25 import BM25Okapi

from customs_agent.rag._tokenize import tokenize
from customs_agent.rag.chunker import KNOWLEDGE_DIR, parse_chunks

INDEXER_VERSION = "1.0.0"
EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION_NAME = "knowledge"

# Default output paths, anchored at the backend/ root. Overridable via CLI flags.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_CHROMA = _BACKEND_ROOT / "chroma_db"
DEFAULT_OUT_BM25 = _BACKEND_ROOT / "bm25.pkl"
DEFAULT_OUT_MANIFEST = _BACKEND_ROOT / "manifest.json"

log = structlog.get_logger()


class _BuildSettings(BaseSettings):
    """Build-time settings, decoupled from runtime ``Settings``.

    The runtime class requires ``ANTHROPIC_API_KEY`` / ``BACKEND_API_KEY`` /
    ``ALLOWED_ORIGINS`` — none of which the indexer needs. This narrow
    subclass loads only ``OPENAI_API_KEY`` from ``backend/.env`` and
    ignores everything else so a partial dev environment can still build.
    """

    openai_api_key: str
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


def _build_chroma(
    out_chroma: Path,
    chunks: list[Any],
    api_key: str,
) -> None:
    """(Re-)create the persistent ChromaDB collection and add all chunks."""
    if out_chroma.exists():
        log.info("rag.build.chroma.wipe_existing", path=str(out_chroma))
        shutil.rmtree(out_chroma)
    out_chroma.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(out_chroma))
    embedding_fn = OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name=EMBEDDING_MODEL,
    )
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )

    collection.add(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "doc": c.doc,
                "doc_title": c.doc_title,
                "section_id": c.section_id,
                "section_title": c.section_title,
                "section_kind": c.section_kind,
            }
            for c in chunks
        ],
    )
    log.info(
        "rag.build.chroma.indexed",
        path=str(out_chroma),
        collection=COLLECTION_NAME,
        chunk_count=len(chunks),
        embedding_model=EMBEDDING_MODEL,
    )


def _build_bm25(out_bm25: Path, chunks: list[Any]) -> None:
    """Tokenize chunks with the shared tokenizer and pickle the BM25 index."""
    tokenized = [tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    out_bm25.write_bytes(pickle.dumps(bm25))
    log.info("rag.build.bm25.pickled", path=str(out_bm25), chunk_count=len(chunks))


def _build_manifest(
    out_manifest: Path,
    chunks: list[Any],
    knowledge_dir: Path,
) -> None:
    """Write the manifest JSON with embedding metadata + source SHAs."""
    source_shas: dict[str, str] = {}
    for path in sorted(knowledge_dir.glob("*.txt")):
        source_shas[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    manifest: dict[str, Any] = {
        "embedding_model": EMBEDDING_MODEL,
        "indexer_version": INDEXER_VERSION,
        "built_at": datetime.now(UTC).isoformat(),
        "chunk_count": len(chunks),
        "chunk_ids": sorted(c.chunk_id for c in chunks),
        "source_file_shas": source_shas,
    }
    out_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    log.info(
        "rag.build.manifest.written",
        path=str(out_manifest),
        chunk_count=len(chunks),
        source_files=list(source_shas),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Returns ``0`` on success, ``1`` on failure. Returning rather than raising
    lets the Dockerfile RUN step see a clean exit code.
    """
    parser = argparse.ArgumentParser(
        description="Build the RAG index (ChromaDB + BM25 + manifest).",
    )
    parser.add_argument(
        "--out-chroma", type=Path, default=DEFAULT_OUT_CHROMA,
        help="Output directory for the persistent ChromaDB collection.",
    )
    parser.add_argument(
        "--out-bm25", type=Path, default=DEFAULT_OUT_BM25,
        help="Output path for the pickled BM25Okapi instance.",
    )
    parser.add_argument(
        "--out-manifest", type=Path, default=DEFAULT_OUT_MANIFEST,
        help="Output path for the manifest.json metadata.",
    )
    parser.add_argument(
        "--knowledge-dir", type=Path, default=KNOWLEDGE_DIR,
        help="Source directory of knowledge .txt files.",
    )
    args = parser.parse_args(argv)

    try:
        settings = _BuildSettings()  # type: ignore[call-arg]
    except Exception as exc:
        print(
            "✗ OPENAI_API_KEY missing — add it to backend/.env or export "
            "it before running this script.",
            file=sys.stderr,
        )
        print(f"  ({exc})", file=sys.stderr)
        return 1

    api_key = settings.openai_api_key
    if not api_key:
        print(
            "✗ OPENAI_API_KEY is set but empty. Populate it in backend/.env.",
            file=sys.stderr,
        )
        return 1
    # Some libraries (and friendly logs) expect the env var; mirror it.
    os.environ["OPENAI_API_KEY"] = api_key

    log.info("rag.build.start", knowledge_dir=str(args.knowledge_dir))
    chunks = parse_chunks(args.knowledge_dir)
    log.info("rag.build.chunks_parsed", chunk_count=len(chunks))

    _build_chroma(args.out_chroma, chunks, api_key=api_key)
    _build_bm25(args.out_bm25, chunks)
    _build_manifest(args.out_manifest, chunks, args.knowledge_dir)

    log.info(
        "rag.build.complete",
        chunk_count=len(chunks),
        out_chroma=str(args.out_chroma),
        out_bm25=str(args.out_bm25),
        out_manifest=str(args.out_manifest),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
