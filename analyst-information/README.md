# Analyst Information

Status: legacy design note.

The active information-layer implementation now lives in:

- `src/analyst/information/`

Current live status:

- file-backed local repository implemented
- bundled demo datasets implemented
- market snapshot and regime-state service implemented

Not yet implemented:

- live ingestion
- scheduled refresh
- persistent product stores
- adapters to external reference repos

Do not add new production code here. Use `src/analyst/information/`.
