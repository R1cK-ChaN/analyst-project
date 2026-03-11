# Storage Layer

SQLite-based persistence with WAL mode and foreign keys enabled.
All tables live in a single `engine.db` file (`~/.analyst/engine.db` by default).

---

## Document Storage (5-table normalized schema)

Stores government reports and official statistical releases from ~40 sources
across US, CN, JP, and EU. Designed for clean separation of source metadata,
recurring release streams, document records, content blobs, and overflow JSON.

### Tables

```
doc_source              Publisher-level info (BLS, ECB, NBS...)
  |
  +-- doc_release_family   Recurring release streams (us.bls.cpi, cn.nbs.gdp...)
        |
        +-- document          Canonical stored report record
              |
              +-- document_blob   Content by role (markdown, raw_html, raw_pdf...)
              +-- document_extra  Overflow JSON metadata
```

### doc_source

| Column | Type | Notes |
|--------|------|-------|
| `source_id` | TEXT PK | e.g. `us.bls`, `cn.nbs`, `eu.ecb` |
| `source_code` | TEXT | Short code: `bls`, `nbs` |
| `source_name` | TEXT | Full name: `BLS`, `国家统计局` |
| `source_type` | TEXT | CHECK: `government_agency`, `central_bank`, `intl_org`, `statistics_bureau`, `news_agency` |
| `country_code` | TEXT | 2-letter ISO: `US`, `CN`, `JP`, `EU` |
| `default_language_code` | TEXT | `en`, `zh` |
| `is_active` | INTEGER | 1/0 |

### doc_release_family

| Column | Type | Notes |
|--------|------|-------|
| `release_family_id` | TEXT PK | e.g. `us.bls.cpi`, `cn.pboc.lpr` |
| `source_id` | TEXT FK | -> `doc_source` |
| `release_code` | TEXT | `cpi`, `gdp`, `lpr` |
| `topic_code` | TEXT | `inflation`, `employment`, `monetary_policy` |
| `frequency` | TEXT | `monthly`, `quarterly`, `irregular` |

### document

| Column | Type | Notes |
|--------|------|-------|
| `document_id` | TEXT PK | SHA-256 prefix of URL |
| `release_family_id` | TEXT FK | -> `doc_release_family` (nullable) |
| `source_id` | TEXT FK | -> `doc_source` |
| `canonical_url` | TEXT UNIQUE | Full URL |
| `title` | TEXT | Report title |
| `document_type` | TEXT | CHECK: `release`, `bulletin`, `speech`, `methodology`, `revision_notice`, `minutes`, `statement`, `press_release`, `report`, `outlook` |
| `language_code` | TEXT | 2-letter ISO |
| `country_code` | TEXT | 2-letter ISO |
| `topic_code` | TEXT | Same codes as release_family |
| `published_date` | TEXT | `YYYY-MM-DD` |
| `status` | TEXT | CHECK: `published`, `revised`, `superseded`, `withdrawn` |
| `version_no` | INTEGER | Default 1 |
| `hash_sha256` | TEXT | Full SHA-256 of URL |

### document_blob

| Column | Type | Notes |
|--------|------|-------|
| `document_blob_id` | TEXT PK | `{doc_id}_{role}` |
| `document_id` | TEXT FK | -> `document` |
| `blob_role` | TEXT | CHECK: `raw_pdf`, `raw_html`, `clean_html`, `plain_text`, `markdown` |
| `content_text` | TEXT | Text content (for markdown, plain_text, html) |
| `content_bytes` | BLOB | Binary content (for PDFs) |
| `byte_size` | INTEGER | Content size |
| `parser_name` | TEXT | e.g. `markdownify` |

### document_extra

| Column | Type | Notes |
|--------|------|-------|
| `document_id` | TEXT PK FK | -> `document` |
| `extra_json` | TEXT | JSON overflow: importance, institution, description, source-specific fields |

### Indexes

```sql
idx_document_url                  UNIQUE ON document(canonical_url)
idx_document_source_date          ON document(source_id, published_date)
idx_document_release_date         ON document(release_family_id, published_date)
idx_document_country_topic_date   ON document(country_code, topic_code, published_date)
idx_document_status               ON document(status)
idx_blob_document_role            ON document_blob(document_id, blob_role)
```

### Seeding

Sources and release families are auto-seeded from the gov_report scraper
configs on first ingestion refresh:

```python
store.seed_doc_sources_and_families({
    "us": _US_SOURCES, "cn": _CN_SOURCES,
    "jp": _JP_SOURCES, "eu": _EU_SOURCES,
})
```

This populates 16 sources and 41 release families.

### CRUD Methods

| Method | Description |
|--------|-------------|
| `upsert_doc_source()` | Insert/update a source |
| `get_doc_source()` / `list_doc_sources()` | Query sources |
| `upsert_doc_release_family()` | Insert/update a release family |
| `get_doc_release_family()` / `list_doc_release_families()` | Query families (filter by source, country, topic) |
| `upsert_document()` | Insert/update a document |
| `get_document()` / `get_document_by_url()` / `document_exists()` | Lookup documents |
| `list_documents()` | Filter by source, family, country, topic, status, type, days |
| `upsert_document_blob()` | Insert/update a blob |
| `get_document_blob()` / `list_document_blobs()` | Query blobs by doc + role |
| `upsert_document_extra()` / `get_document_extra()` | JSON overflow metadata |

---

## Other Tables

| Table | Purpose |
|-------|---------|
| `calendar_events` | Economic calendar (Investing, ForexFactory, TradingEconomics) |
| `market_prices` | Asset price snapshots (yfinance) |
| `central_bank_comms` | Fed speeches, statements, testimony (RSS feeds) |
| `indicators` | Time series macro data (FRED, NY Fed, rate probabilities) |
| `news_articles` | News + gov reports (FTS5 full-text search) |
| `regime_snapshots` | Market regime JSON snapshots |
| `generated_notes` | AI-generated analysis notes |
| `analytical_observations` | Observations & insights |
| `research_artifacts` | Research documents with tags |
| `trade_signals` | Trading signals with rationale |
| `decision_log` | Decision tracking |
| `position_state` | Current portfolio positions |
| `performance_records` | Trading performance metrics |
| `trading_artifacts` | Trading strategy documents |
| `client_profiles` | User profiles (20+ dimensions) |
| `conversation_threads` / `conversation_messages` | Chat history |
| `delivery_queue` | Content delivery to users |
| `group_profiles` / `group_members` / `group_messages` | Group chat |
| `portfolio_holdings` / `portfolio_vol_snapshots` / `portfolio_alerts` | Portfolio management |
| `subagent_runs` | Sub-agent task tracking |

## Running Tests

```bash
python3 -m pytest tests/test_document_storage.py -v
```
