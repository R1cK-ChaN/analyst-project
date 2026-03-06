# Analyst Integration

Status: legacy design note.

The active integration implementation now lives in:

- `src/analyst/integration/`

Current live status:

- keyword-based mode detection implemented
- routed WeCom-style message handling implemented
- engine-to-delivery reply flow implemented

Not yet implemented:

- transport adapter layer
- observability
- retries
- persistent logging

Do not add new production code here. Use `src/analyst/integration/`.
