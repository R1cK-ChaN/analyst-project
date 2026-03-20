# storage/

SQLite schema and CRUD operations, organized as mixins composed into
`SQLiteEngineStore`.

## Files

| File | Status | Notes |
|------|--------|-------|
| `sqlite.py` | Active | Composition facade — all mixins into one store |
| `sqlite_core.py` | Active | Connection management, WAL mode, schema init |
| `sqlite_schema.py` | Active | DDL definitions (tables, indexes) |
| `sqlite_records.py` | Active | All Record dataclasses |
| `sqlite_memory.py` | Active | Profile, relationship, conversations, reminders |
| `sqlite_groups.py` | Active | Group profiles, members, messages |
| `sqlite_analysis.py` | Active | Artifact cache storage (for research-service) |
| `sqlite_research.py` | Light use | Research notes, artifacts, decision logs |
| `sqlite_documents.py` | Light use | Document storage for knowledge base |
| `sqlite_market_macro.py` | Light use | Calendar events, market prices, regime snapshots |
| `sqlite_calendar_normalization.py` | Light use | Calendar event deduplication |
| `sqlite_seed_data.py` | Testing only | Test/demo data generators |

No legacy files remain in this module.
