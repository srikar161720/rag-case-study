# RAG Layer

Authoritative source for the Retrieval-Augmented Generation pipeline:
chunking, embedding, vector + lexical retrieval, hybrid fusion, always-on
context selection, and build-time indexing.

Load this file when working on `backend/src/customs_agent/rag/`,
`backend/scripts/build_index.py`, or when adjusting what the agent
"knows" by default.

---

## What "the knowledge layer" contains

Four plain-text files provided with the case study, sitting at
`backend/knowledge/` (moved from root per Fork 35):

| File | Sections | What it defines |
|---|---|---|
| `customs_core_concepts.txt` | 10 numbered concepts | Domain terminology: entry numbers, entry types, lifecycle dates (Release Date = canonical), Form 7501, BOLs, container numbers, MID, port codes, pay type |
| `duties_fees_tariffs.txt` | 9 duty/fee sections + 6 **Business Rules for Analytics** | HTS code formatting, primary duty, tariff stacking, Section 301 (CN-only), IEEPA (per-country rates), MPF (per-entry cap), HMF (ocean-only), entered value; **plus the 6 rules: date filtering, entry vs line count, duty aggregation, country-of-origin filtering, shell entries, on-hold entries** |
| `customer_profiles_qbr_metrics.txt` | 3 customer profiles + 5 QBR section templates + 4 metric definitions | MHF / PCA / SAG profiles; QBR template; **the 4 metric formulas: Effective Duty Rate, Entry Line Density, Section 301 Exposure Ratio, Hold Rate (with 5% benchmark + 8% investigation threshold)** |
| `data_dictionary.txt` | Column list + Relationships + 4 **Known Data Quirks** | Column semantics; **the 4 quirks: Section 301 fields populated ONLY for CN; IEEPA fields populated ONLY for Release Date ≥ 2025-02-01; MPF line-level allocation but entry-level capped; some entries share Bill of Lading (consolidations)** |

Total: ~17 KB of structured text. Small enough to fit in a single LLM
context window many times over — which makes the architectural question
of "what's RAG'd vs always-on" (Fork 15) the most interesting one in
this layer.

---

## Chunking Strategy (Fork 14)

**Section-header split**: each numbered section becomes one chunk.
Approximately **~30 chunks total** across the four files.

### Why not fixed-token windows or sentence-level

These docs are *authored as structured rules and definitions*. Sentence-
level splits destroy context ("Section 301 tariffs apply only to..." in
isolation means nothing). Fixed-token windows split rules in half ("RULE:
Section 301 tariffs apply ONLY to..." cut mid-sentence). Section
boundaries are the natural unit of meaning AND the natural unit the
agent will need to retrieve — for example, Q10 ("which date field?")
needs exactly the chunk titled "RULE 1 — Date Filtering."

### Chunk content shape

Each chunk's stored text is enriched with parent-doc context so the
embedding captures the section's place in the document:

```
DOCUMENT: duties_fees_tariffs.txt — Duties, Fees & Tariff Programs
SECTION: §4 SECTION 301 TARIFFS (CHINA-SPECIFIC)

Trade remedy tariffs applied to goods of Chinese origin. Key codes:
- 9903.88.03 (List 3): 25% additional duty on ~$200B of Chinese goods
- 9903.88.15 (List 4A): 7.5% additional duty on ~$120B of Chinese goods

RULE: Section 301 tariffs apply ONLY to goods where Country of Origin
is China (CN). They do not apply to goods manufactured in other countries
even if components originated in China.
```

And the matching ChromaDB metadata:

```json
{
  "chunk_id":      "section_301_china_specific",
  "doc":           "duties_fees_tariffs.txt",
  "doc_title":     "Duties, Fees & Tariff Programs",
  "section_id":    "§4",
  "section_title": "Section 301 Tariffs (China-Specific)",
  "section_kind":  "duty_program"
}
```

### `section_kind` taxonomy

Used by the always-on selection logic (Fork 15) and by retrieval filters
(future work):

| `section_kind` | Source sections | Always-on? |
|---|---|---|
| `concept` | All 10 `customs_core_concepts.txt` sections | ❌ retrieve |
| `duty_program` | `duties_fees_tariffs.txt` §1–9 (HTS, primary duty, tariff stacking, Section 301, IEEPA, MPF, HMF, etc.) | ❌ retrieve |
| `rule` | `duties_fees_tariffs.txt` §Business Rules 1–6 | ✅ **always-on** |
| `customer_profile` | `customer_profiles_qbr_metrics.txt` MHF / PCA / SAG profiles | ❌ retrieve |
| `qbr_section_template` | `customer_profiles_qbr_metrics.txt` 5 QBR sections | ❌ retrieve (relevant only for `qbr_summary` tool) |
| `metric` | `customer_profiles_qbr_metrics.txt` 4 metric definitions | ✅ **always-on** |
| `column_definition` | `data_dictionary.txt` Column Definitions section | ❌ retrieve (compact schema overview is always-on instead) |
| `relationship` | `data_dictionary.txt` Relationships & Joins section | ❌ retrieve |
| `quirk` | `data_dictionary.txt` 4 Known Data Quirks | ✅ **always-on** |

### Chunk parser (~50 lines)

```python
# backend/src/customs_agent/rag/chunker.py
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc: str
    doc_title: str
    section_id: str
    section_title: str
    section_kind: str
    text: str

# Regex matches "1. SECTION TITLE", "§4 ...", "RULE 1 — ...", etc.
SECTION_RE = re.compile(r"^(\d+\.|§\d+|RULE \d+ —)\s+(.+)$", re.MULTILINE)

KNOWLEDGE_DIR = Path(__file__).parent.parent.parent.parent / "knowledge"

KIND_MAP: dict[str, str] = {
    # Map (file, section_id) → section_kind; falls back to per-file default.
    # Filled in via a small dispatch table per file.
    ...
}

def parse_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.txt")):
        ...
    return chunks
```

The actual parser is straightforward; the parser file is canonical for
chunk ID generation and metadata enrichment.

---

## Embedding Model (Fork 13)

**OpenAI `text-embedding-3-small`**, build-time only.

| Property | Value |
|---|---|
| Dimensions | 1536 |
| Cost | $0.02 per 1M tokens |
| Total cost for this corpus | ~$0.00012 (≈30 chunks × ~200 tokens × $0.02/1M), paid once at build |
| When called | During `docker build` only — never at runtime |
| API key | `OPENAI_API_KEY`, injected via BuildKit secret mount (Fork 17 + 39); never stored in image layers |

### Why not Voyage / `text-embedding-3-large` / local

- **vs `text-embedding-3-large`**: 6.5× more expensive, 2× dimensions
  (more memory), zero accuracy gain on a 30-chunk corpus.
- **vs Voyage `voyage-3`**: Anthropic-recommended but another vendor +
  another credential for marginal quality gain at this size.
- **vs local `all-MiniLM-L6-v2`**: drags in PyTorch (~1 GB Docker bloat),
  slows cold-start, lower quality on jargon-heavy text.

### Quality is adequate because retrieval is hybrid

The Fork 16 hybrid retriever pairs semantic search with BM25 lexical
matching. BM25 nails the jargon-heavy queries (`9903.88.15`, `IEEPA`,
`MPF`, exact HTS codes); semantic handles paraphrases. Either retriever
alone would have blind spots; together they cover both, so the semantic
quality doesn't need to be best-in-class.

---

## Retrieval Strategy (Fork 16)

**Hybrid BM25 + semantic with Reciprocal Rank Fusion**, top-K = 5,
pulling 2K candidates from each retriever before fusion.

### Why hybrid

This corpus has both flavors of content:

- **Jargon-dense** rule text (`9903.88.15`, `IEEPA`, `MPF`, `Form 7501`).
  BM25 nails exact-token matching.
- **Conceptual prose** ("how to calculate effective duty rate"). Semantic
  catches paraphrases.

Either retriever alone has blind spots. Hybrid covers both.

### Reciprocal Rank Fusion (RRF)

For each chunk, score = `Σ 1/(rank_in_each_retriever + 60)`. Top-K by
fused score wins. No score normalization, no calibration, no tunable
hyperparameters. The constant 60 is the well-established default —
don't tune it.

### Reference: retriever.py pattern

```python
# backend/src/customs_agent/rag/retriever.py
from collections import defaultdict
from rank_bm25 import BM25Okapi
import chromadb
from chromadb.utils import embedding_functions

class HybridRetriever:
    def __init__(self, chroma_path: Path, bm25_path: Path, chunks: list[Chunk]):
        self._chunks_by_id = {c.chunk_id: c for c in chunks}
        # Embeddings: persisted ChromaDB built at Docker build (Fork 17)
        self._chroma = chromadb.PersistentClient(path=str(chroma_path)).get_collection(
            name="knowledge",
            embedding_function=embedding_functions.OpenAIEmbeddingFunction(
                api_key=os.environ.get("OPENAI_API_KEY", ""),  # only used if re-indexing at runtime
                model_name="text-embedding-3-small",
            ),
        )
        # BM25: pickled at build (Fork 17)
        self._bm25 = pickle.loads(bm25_path.read_bytes())
        self._chunk_ids_ordered = [c.chunk_id for c in chunks]

    def retrieve(self, query: str, k: int = 5) -> list[Chunk]:
        candidate_pool = k * 2  # 10 from each retriever before fusion

        # Semantic
        sem_results = self._chroma.query(query_texts=[query], n_results=candidate_pool)
        sem_ids = sem_results["ids"][0]

        # BM25
        bm25_scores = self._bm25.get_scores(self._tokenize(query))
        bm25_top_idx = sorted(range(len(bm25_scores)), key=lambda i: -bm25_scores[i])[:candidate_pool]
        bm25_ids = [self._chunk_ids_ordered[i] for i in bm25_top_idx]

        # RRF fusion
        fused: dict[str, float] = defaultdict(float)
        for rank, cid in enumerate(sem_ids):
            fused[cid] += 1 / (rank + 60)
        for rank, cid in enumerate(bm25_ids):
            fused[cid] += 1 / (rank + 60)

        top_ids = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [self._chunks_by_id[cid] for cid, _ in top_ids]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # Critical: preserve dots inside HTS codes so "9903.88.15" tokenizes as one token
        # (default whitespace+punctuation split would break it into "9903" "88" "15")
        return re.findall(r"\d+\.\d+\.\d+|\w+", text.lower())
```

### Special tokenization rule

Default BM25 tokenization breaks `9903.88.15` into three tokens (`9903`,
`88`, `15`). Customs codes need to tokenize as a single token. The
regex `\d+\.\d+\.\d+|\w+` matches dotted numeric sequences first, then
falls back to word characters.

### Retrieval observability hook

Per Fork 16 + Fork 52, every retrieval call emits a Langfuse span
(`rag.retrieve`) with:

```python
@observe(name="rag.retrieve")
def retrieve(...) -> list[Chunk]:
    ...
    langfuse_context.update_current_observation(
        input={"query": query, "k": k},
        output={"chunks": [
            {"chunk_id": c.chunk_id, "doc": c.doc, "section": c.section_id,
             "score_semantic": sem_score(c.chunk_id),
             "score_bm25":     bm25_score(c.chunk_id),
             "score_rrf":      fused[c.chunk_id]}
            for c in result
        ]},
        metadata={"retriever": "hybrid_rrf", "rrf_constant": 60},
    )
    return result
```

This makes the panel "what did the agent retrieve?" trivially answerable
post-hoc.

---

## Always-On Context (Fork 15)

**Hybrid**: universal scaffolding always in the cached system prefix
(Fork 27); topical knowledge via retrieval. The hybrid threads the
RAG mandate (case study requires RAG to be implemented) while
maximizing accuracy on the universal-context items.

### What's always-on (~2-3 KB total ≈ ~750 tokens)

| Block | Source chunks | Why always-on |
|---|---|---|
| **Business Rules for Analytics** (6 rules) | `duties_fees_tariffs.txt` `§Business Rules 1-6` (`section_kind: "rule"`) | Referenced on every Tier 1-4 question (Release Date default, entry vs line count, duty aggregation, origin filter, shell entries, on-hold). Retrieval failure on any of these tanks accuracy. |
| **Known Data Quirks** (4 quirks) | `data_dictionary.txt` `§Known Data Quirks` (`section_kind: "quirk"`) | Section 301 ⇒ CN only; IEEPA ⇒ Release Date ≥ 2025-02-01; MPF cap; consolidated BOLs. Universal preconditions for every aggregation. |
| **Customer codes** (MHF/PCA/SAG → full names) | Authored in `prompts/data_overview.md` (Fork 21) | Tiny lookup; agent uses it constantly. |
| **Schema overview** (~10 key columns) | Authored in `prompts/data_overview.md` from `DESCRIBE entries_v` / `entry_lines_v` (Fork 21) | Agent needs the column shape for nearly every tool call. |
| **Metric definitions** (4 metrics) | `customer_profiles_qbr_metrics.txt` `§Effective Duty Rate`, `§Entry Line Density`, `§Section 301 Exposure Ratio`, `§Hold Rate` (`section_kind: "metric"`) | Q5 and Q6 hinge on exact formulas + the 5%/8% benchmark thresholds. |

### What's retrieved per query (the rest)

| Source chunks | Why retrieval |
|---|---|
| `customs_core_concepts.txt` 10 concepts (`section_kind: "concept"`) | Only relevant when user asks about them directly |
| `duties_fees_tariffs.txt` §1–9 duty/fee specifics (`section_kind: "duty_program"`) | Only when question touches a specific program / country |
| `customer_profiles_qbr_metrics.txt` customer profile narratives | Only for customer-specific questions |
| `customer_profiles_qbr_metrics.txt` QBR section templates (`section_kind: "qbr_section_template"`) | Only for QBR generation (Q9) |
| `data_dictionary.txt` Relationships & Joins, Column Definitions | Only when user asks about schema mechanics |

### Always-on assembly

```python
# backend/src/customs_agent/rag/always_on.py
ALWAYS_ON_KINDS = frozenset(["rule", "quirk", "metric"])

def assemble_always_on_block(chunks: list[Chunk]) -> str:
    """Concatenate always-on chunks into a stable Markdown block.

    Stable ordering by (kind, section_id) ensures the cached prefix
    (Fork 55) doesn't drift across identical content.
    """
    selected = sorted(
        [c for c in chunks if c.section_kind in ALWAYS_ON_KINDS],
        key=lambda c: (c.section_kind, c.section_id, c.chunk_id),
    )
    parts: list[str] = []
    for c in selected:
        parts.append(f"### {c.doc_title} — {c.section_title}\n\n{c.text}\n")
    return "\n".join(parts)
```

This output is included in the templated system prompt (Fork 27 —
specifically `prompts/knowledge_always_on.md` is the version of this
content that the agent sees).

### Dedup against retrieved chunks

When ChromaDB also surfaces an always-on chunk (because the user query
semantically matches it), dedupe by `chunk_id` before injecting
retrieved chunks into the user message:

```python
# In the agent loop, before assembling the user-side context
always_on_ids = {c.chunk_id for c in always_on_chunks}
retrieved_filtered = [c for c in retrieved if c.chunk_id not in always_on_ids]
```

5-line safeguard. Prevents the same chunk from appearing twice in the
prompt, which would burn cache tokens for zero benefit.

---

## Build-Time Indexing (Fork 17)

Embeddings and BM25 index are built during `docker build` and baked into
the runtime image. The runtime container has zero embedding work to do
at boot and **never needs `OPENAI_API_KEY` at all** — only the LLM-
provider key.

### Why build-time

| Reason | Detail |
|---|---|
| **Reproducibility** | Each Docker image is pinned to its embeddings. Same image = same retrieval behavior. |
| **Fast cold-start** | Zero boot-time embedding work. Fly machine restarts come up in seconds, not minutes. |
| **Smaller runtime credential surface** | `OPENAI_API_KEY` is build-only (GHA Secret); runtime container has only `ANTHROPIC_API_KEY`. |
| **Build acts as smoke test** | If a knowledge file has a parse error, build fails; deploy never happens. |
| **Decoupled from OpenAI uptime at boot** | If OpenAI is down at runtime, retrieval still works (uses persisted embeddings). |

### Three artifacts baked into the image

| Path in image | Content | Built by |
|---|---|---|
| `/app/chroma_db/` | ChromaDB persistent client directory (SQLite + parquet) holding ~30 embedded chunks | `chunks → OpenAI text-embedding-3-small → Chroma collection.add()` |
| `/app/bm25.pkl` | Pickled `BM25Okapi` instance with pre-tokenized chunk corpus | `chunks → tokenize → BM25Okapi → pickle.dumps()` |
| `/app/manifest.json` | Build metadata: embedding model name, indexer version, build timestamp, chunk count, source file SHAs | `scripts/build_index.py` emits this last |

### `scripts/build_index.py` sketch

```python
# backend/scripts/build_index.py
import json
import pickle
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

from customs_agent.rag.chunker import parse_chunks

def main(out_chroma: Path, out_bm25: Path, out_manifest: Path) -> None:
    chunks = parse_chunks()

    # Build ChromaDB
    client = chromadb.PersistentClient(path=str(out_chroma))
    collection = client.get_or_create_collection(
        name="knowledge",
        embedding_function=embedding_functions.OpenAIEmbeddingFunction(
            api_key=os.environ["OPENAI_API_KEY"],
            model_name="text-embedding-3-small",
        ),
    )
    collection.add(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "doc":           c.doc,
                "doc_title":     c.doc_title,
                "section_id":    c.section_id,
                "section_title": c.section_title,
                "section_kind":  c.section_kind,
            }
            for c in chunks
        ],
    )

    # Build BM25
    tokenized = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(tokenized)
    out_bm25.write_bytes(pickle.dumps(bm25))

    # Manifest
    source_shas = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path("knowledge").glob("*.txt"))
    }
    out_manifest.write_text(json.dumps({
        "embedding_model": "text-embedding-3-small",
        "indexer_version": "1.0.0",
        "built_at":        datetime.now(timezone.utc).isoformat(),
        "chunk_count":     len(chunks),
        "source_file_shas": source_shas,
    }, indent=2))
```

### Dockerfile wiring (Fork 41 reference)

The builder stage runs `build_index.py` with `OPENAI_API_KEY` injected
via `--mount=type=secret,id=openai_key`. Per Fork 41:

```dockerfile
RUN --mount=type=secret,id=openai_key \
    OPENAI_API_KEY=$(cat /run/secrets/openai_key) \
    .venv/bin/python scripts/build_index.py \
        --out-chroma /app/chroma_db \
        --out-bm25 /app/bm25.pkl \
        --out-manifest /app/manifest.json
```

The runtime stage copies these three artifacts from the builder; the
`OPENAI_API_KEY` never lands in any layer.

### `/ready` endpoint surfaces the manifest (Fork 40)

The `/ready` endpoint reads `manifest.json` at boot and exposes its
contents in the readiness response. This makes "what version of the
knowledge index is deployed?" answerable in one `curl` call — useful
for EVALUATION.md run metadata (G5) and post-deploy verification.

---

## Composition with Other Layers

- **`04-agent-and-tools.md`**: the agent loop calls
  `retriever.retrieve(user_message, k=5)` once per chat request before
  the first LLM call (Fork 29 Phase 2 emits `event: knowledge_retrieved`
  with the chunk IDs at this point). Retrieved chunks land in the user
  message section of the Anthropic API request (below the cache boundary
  per Fork 55).
- **`05-api-and-backend.md`**: the `/ready` endpoint includes the
  manifest from `/app/manifest.json` in its response payload.
- **`07-infrastructure.md`**: the Dockerfile (Fork 41) bakes the
  artifacts in; `.dockerignore` excludes the development-time
  `chroma_db/`, `bm25.pkl`, `manifest.json` so stale local artifacts
  don't override the freshly built ones.
- **`08-cicd-and-testing.md`**: Fork 45 Layer 1 unit tests live in
  `tests/unit/rag/` and verify chunker output, retriever ranking on
  known queries, always-on assembly determinism.
- **`10-observability.md`**: every retrieval emits a Langfuse
  `rag.retrieve` span; retrieved chunk IDs + scores flow into the trace.

---

## Future Work (RAG layer)

| Item | Trigger |
|---|---|
| Cross-encoder reranker (e.g., `bge-reranker-base`) | When corpus grows beyond ~500 chunks and retrieval ranking becomes the bottleneck |
| Metadata-aware retrieval filtering (e.g., `where={"section_kind": "rule"}` for Tier 4 questions) | When unseen-question diversity reveals query patterns that benefit from kind-filtering |
| Embedding model upgrade (e.g., `text-embedding-3-large`) | When semantic recall measurably plateaus on harder paraphrases |
| Hybrid weight tuning (replace RRF with weighted sum) | When the corpus has very different domain density per section |
| Per-tool retrieval bypass | If certain tools (e.g., `lookup_knowledge`) never benefit from semantic search |
| Live re-indexing endpoint | When knowledge files are edited often enough that build-time rebuilds become slow |
| Vector store migration (pgvector / Pinecone) | Multi-machine deployment requires shared retrieval state |

All deferred. Current scale (30 chunks, sub-second retrieval) doesn't
justify any of them.
