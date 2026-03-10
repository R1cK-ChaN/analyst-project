# Analyst Engine

Status: legacy design note.

The active engine implementation now lives in:

- `src/analyst/engine/`

Current live status:

- Q&A path implemented
- draft path implemented
- meeting-prep path implemented
- regime-summary note generation implemented
- pre-market briefing generation implemented
- round sub-agent orchestration implemented in `src/analyst/engine/` for research and sales flows
- sub-agent memory scoping uses word-boundary tags and punctuation-aware retrieval from SQLite
- sub-agent audits persist `parent_agent`, `task_type`, `scope_tags`, status, summary, and elapsed time for both success and failure paths

Not yet implemented:

- scheduling
- persistence
- evaluation harness
- live grounded retrieval

Do not add new production code here. Use `src/analyst/engine/`.
