# analysis/

Deterministic analysis pipeline with typed operators and artifact caching.

**Not used by the companion agent.** This entire module serves the research-service
(decoupled to `/home/rick/Desktop/analyst/research-service`). It remains here as
shared library code but the companion agent never calls it.

## Files

| File | Status | Notes |
|------|--------|-------|
| `artifact.py` | Not for companion | Artifact identity (SHA-256) + TTL policy |
| `store.py` | Not for companion | Artifact SQLite storage/retrieval |
| `types.py` | Not for companion | Type checkers (Series, Dataset, Metric, Signal) |
| `operators/registry.py` | Not for companion | Operator registry + type validation |
| `operators/*.py` (13 operators) | Not for companion | fetch_series, align, combine, correlation, etc. |
