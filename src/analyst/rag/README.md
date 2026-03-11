# analyst/rag — Macro-Economic RAG Retrieval Engine

Hybrid dense + sparse (BM25) retrieval with RRF fusion, reranking, and
coverage-aware selection.  Backed by **SQLite + numpy** for lightweight
single-VPS deployment.

Vendored from `rag-service` and adapted for macro-economic content (news,
Fed communications, economic indicators, calendar events, research notes).

## Architecture

```
SQLite engine.db
  └─ rag_chunks table (text + dense BLOB + sparse JSON + metadata)

Retrieval pipeline:
  query → embed (OpenAI) ──┐
                            ├─ RRF fusion → dedup → time-decay
  query → BM25 sparse ─────┘     → coverage selection → rerank (optional)
                                       → evidence bundle
```

### Key modules

| Module | Description |
|--------|-------------|
| `vector_store.py` | SQLite table `rag_chunks` + numpy brute-force IP search |
| `embeddings.py` | OpenAI `text-embedding-3-large` (3072-dim) |
| `bm25.py` | BM25 sparse vectors via mmh3 hashing (10M buckets) |
| `pipeline.py` | Core retrieval: dense+sparse search → RRF → dedup → coverage |
| `reranker.py` | Optional Jina API reranker |
| `retriever.py` | `MacroRetriever` — high-level wrapper owning all components |
| `chunker.py` | Content-type-aware chunking (news, Fed comms, indicators, events, research) |
| `bridge.py` | `MacroIngestionBridge` — SQLite → chunk → embed → insert to vector store |
| `policies/*.yaml` | Policy definitions for 4 retrieval modes |

### Retrieval modes

| Mode | Use case | Dense | BM25 |
|------|----------|-------|------|
| **RESEARCH** | Flash commentary, deep-dive | high | medium |
| **BRIEFING** | Morning/after-market briefings | medium | high |
| **QA** | Free-form user questions | high | high |
| **REGIME** | Regime state assessment | medium | medium |

## CLI Commands

```bash
# Full rebuild — drops rag_chunks, re-chunks + re-embeds all SQLite data
analyst-cli rag calibrate

# Incremental sync — only new records since last watermark
analyst-cli rag sync

# Show collection stats and watermarks
analyst-cli rag status
```

## Configuration

All via environment variables (read from `.env` by `analyst.env.get_env_value`):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | Required for embeddings |
| `ANALYST_RAG_DB_PATH` | `engine.db` | SQLite DB path (shared with analyst engine) |
| `ANALYST_EMBEDDING_MODEL` | `text-embedding-3-large` | OpenAI model |
| `ANALYST_EMBEDDING_DIM` | `3072` | Embedding dimension |
| `ANALYST_ENABLE_RERANKER` | `false` | Enable Jina reranker |
| `ANALYST_RERANKER_API_KEY` | — | Jina API key |
| `ANALYST_BM25_STATS_DIR` | — | Directory for BM25 stats JSON |
| `ANALYST_RAG_POLICY_DIR` | `policies/` | Policy YAML directory |

## Agent Tool

The `search_knowledge_base` tool is automatically registered when `MacroRetriever`
initializes successfully.  Parameters: `query`, `mode`, `country`,
`indicator_group`, `impact_level`, `content_type`, `days`, `limit`.

## Dependencies

- `openai>=1.10.0` — embeddings
- `numpy>=1.24` — brute-force vector search
- `mmh3>=4.1.0` — BM25 hash buckets
- `PyYAML` — policy loading
