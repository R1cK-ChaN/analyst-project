# Analyst Runtime

Status: legacy design note.

The active runtime implementation now lives in:

- `src/analyst/runtime/`

Current live status:

- prompt profiles implemented
- deterministic template runtime implemented
- runtime request/response context objects implemented

Not yet implemented:

- real agent-loop adapter
- model-provider integration
- memory integration

Do not add new production code here. Use `src/analyst/runtime/`.
