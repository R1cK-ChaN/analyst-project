# Analyst — Implementation Status

**Status date:** March 7, 2026 (updated after ws1/engine + ws1/calendar merge)

This document is the current implementation snapshot for `analyst-project/`.

Use this file for "what exists now."
Use the workstream docs for "what we want to build next."

---

## Current Reality

`analyst-project/` is now a standalone Python project.

The active implementation lives under:

- `src/analyst/`
- `data/demo/`
- `tests/`
- `pyproject.toml`

The old split folders such as `analyst-runtime/`, `analyst-information/`, `analyst-engine/`, `analyst-delivery/`, and `analyst-integration/` are now documentation and historical scaffolding only. New code should go into `src/analyst/`.

The sibling `information/` repo is currently reference material only. The standalone project does not import it at runtime.

---

## Implemented Now

### Package and entrypoints

- installable project metadata in `pyproject.toml`
- package entrypoint in `src/analyst/__main__.py`
- CLI in `src/analyst/cli.py`
- Telegram bot entrypoint in `src/analyst/delivery/bot.py`
- `analyst-telegram` console script in `pyproject.toml`
- top-level app factory in `src/analyst/app.py`

### Shared contracts

Implemented in `src/analyst/contracts.py`:

- `Event`
- `CalendarItem`
- `MarketSnapshot`
- `RegimeState`
- `ResearchNote`
- `DraftResponse`
- `ChannelMessage`

### Information layer

Implemented in `src/analyst/information/`:

- file-backed repository reading local JSON demo data
- market snapshot builder
- regime-state builder
- context-packet builder for question answering and draft generation

Current data source:

- bundled local demo files in `data/demo/`

### Runtime layer

Implemented in `src/analyst/runtime/`:

- prompt profiles for core interaction modes
- deterministic template runtime
- runtime request/response context objects

Current limitation:

- this is not yet connected to a real agent loop or external model provider

### Engine layer

Implemented in `src/analyst/engine/`:

- macro Q&A response path (demo)
- draft-generation path (demo)
- meeting-prep path (demo)
- regime-summary note generation (demo)
- pre-market briefing generation (demo)
- **live engine** (`live_service.py`): `LiveAnalystEngine` with OpenRouter LLM backend
- **agent loop** (`agent_loop.py`): turn-bounded Python tool-calling loop
- **LLM provider** (`live_provider.py`): OpenRouter chat completions adapter with configurable model
- **prompts** (`live_prompts.py`): Chinese-language institutional macro analyst system/user prompts
- **type contracts** (`live_types.py`): Protocol-based `LLMProvider`, `AgentTool`, conversation types
- live flash commentary (数据快评), morning briefing (早盘速递), after-market wrap (收盘点评)
- regime state refresh with structured JSON regime scoring
- live calendar inspection path with scope routing (`today`, `upcoming`, `recent`, `week`)
- local agent tools for today's calendar, indicator release trends, and surprise summaries

### Storage layer

Implemented in `src/analyst/storage/`:

- SQLite store (`sqlite.py`) with managed connection context manager (commit/rollback/close)
- six tables: `calendar_events`, `market_prices`, `central_bank_comms`, `indicators`, `regime_snapshots`, `generated_notes`
- frozen dataclass records for all table types
- calendar event enrichment fields including `revised_previous` and `currency`
- query methods: recent/upcoming events, date-range queries, today's events, indicator release history, latest prices, indicator history, regime snapshots
- upsert semantics with UNIQUE constraints for deduplication

### Ingestion layer

Implemented in `src/analyst/ingestion/`:

- `InvestingCalendarClient`: economic calendar scraper (Investing.com)
- `ForexFactoryCalendarClient`: economic calendar scraper (ForexFactory)
- `FREDIngestionClient`: FRED API adapter for 25+ macro series (inflation, employment, growth, rates, liquidity, FX, credit)
- `FedIngestionClient`: Fed RSS feed parser for press releases, speeches, and testimony
- `MarketPriceClient`: cross-asset price scraper via yfinance (equities, FX, bonds, commodities, crypto)
- `IngestionOrchestrator`: refresh-all and schedule orchestrator with configurable intervals
- Investing calendar retry/backoff and multi-day refresh window (`days_back=1`, `days_forward=3`)
- Investing calendar parsing for currency text and revised previous values

### Environment resolver

Implemented in `src/analyst/env.py`:

- multi-file `.env` fallback chain (project `.env` → sibling `information/.env`)
- `get_env_value()` with multi-key lookup and default
- `lru_cache`-based file reading with `clear_env_cache()` for testing

### Delivery layer

Implemented in `src/analyst/delivery/`:

- WeCom-style message formatting
- Telegram-specific message formatting
- Telegram polling bot shell with `/start`, `/help`, `/regime`, `/calendar`, and `/premarket`
- compliance disclaimers
- calendar reply formatting
- Telegram-safe 4096-character truncation that preserves disclaimers

### Integration layer

Implemented in `src/analyst/integration/`:

- keyword-based mode detection
- message routing to engine methods
- channel-agnostic formatter protocol
- generic formatted reply generation
- backward-compatible `handle_wecom_message()` alias

### Tests

Implemented in `tests/`:

- `test_product_layer.py` for product-layer smoke tests
- `test_telegram.py` for Telegram formatter, truncation, routing, and bot wiring
- `test_ws1_engine.py` for WS1 live engine and calendar paths: store CRUD/upsert/filter/range queries, scraper retry behavior, flash commentary tool-calling loop with persistence, no-event error path, regime payload parsing with malformed JSON, env fallback chain, and CLI routing for refresh/flash/regime-refresh/live-calendar

---

## Not Implemented Yet

### Data ingestion (remaining)

Not yet implemented inside `analyst-project/`:

- live government-report crawling (BLS, BEA beyond FRED)
- live news ingestion (Finnhub, Alpha Vantage, Google News RSS)
- China-specific sources (PBOC, NBS, Xinhua, Caixin)
- live document parsing

Note: calendar scraping (Investing.com, ForexFactory), FRED series, Fed RSS, and yfinance market prices are now implemented in `src/analyst/ingestion/`.

### Agent backend (remaining)

Not yet implemented:

- memory store / user personalization
- prompt/version management beyond local code
- retry/backoff for LLM provider errors
- multi-model comparison (DeepSeek, Qwen alternatives)

Note: OpenRouter LLM integration and a Python agent loop with tool calling are now implemented in `src/analyst/engine/`.

### Product storage (remaining)

Not yet implemented:

- interaction log store
- user context store

Note: SQLite-backed research store (generated notes), market state store (prices, indicators), and regime snapshot persistence are now implemented in `src/analyst/storage/`.

### Delivery infrastructure

Not yet implemented:

- actual WeCom bot/server
- official account publishing
- mini-program endpoints
- scheduler for briefing pushes
- webhook handling

### Operations

Not yet implemented:

- deployment packaging
- config/env management
- observability
- retry logic
- production auth/compliance logging

---

## Workstream Status

### WS1 Macro Engine

Status: Month 1 scope implemented

Done:

- engine contract layer
- regime summary, pre-market briefing, Q&A, draft, and meeting-prep paths (demo)
- SQLite store with 6 tables and managed connections
- ingestion adapters: Investing.com calendar, ForexFactory calendar, FRED API (25+ series), Fed RSS, yfinance market prices
- enriched calendar event storage with `revised_previous` and `currency`
- calendar query surface for recent, upcoming, today, week, and indicator-history views
- ingestion orchestrator with refresh-all and scheduled polling
- Investing calendar retry/backoff and multi-day fetching
- Python agent loop with turn-bounded tool calling
- OpenRouter LLM provider with configurable model
- Chinese-language institutional macro prompts (数据快评, 早盘速递, 收盘点评, regime refresh)
- regime state scoring with clamped numeric axes and cross-asset implications
- environment resolver with multi-file `.env` fallback
- CLI commands: refresh, schedule, flash, briefing, wrap, regime-refresh, live-calendar
- agent tools for recent releases, today's calendar, indicator trends, market snapshot, Fed comms, indicator history, latest regime state, and surprise summaries
- focused WS1 tests covering store, scraper retry paths, loop, env, CLI, regime parsing, and calendar query behavior

Missing:

- live end-to-end verification against OpenRouter/FRED (tested locally with mocks only)
- China-specific ingestion (PBOC, NBS, Xinhua, Caixin)
- news ingestion (Finnhub, Alpha Vantage, Google News)
- evaluation harness and quality benchmarking against real sell-side notes
- Sales agent Month 2 scope (user personalization, memory)

### WS2 Delivery Shell

Status: Telegram validation bot implemented, WeCom transport not yet started

Done:

- WeCom-style and Telegram-specific reply formatting with per-mode compliance disclaimers
- `ChannelFormatter` protocol for channel-agnostic delivery (`router.py`)
- Telegram polling bot shell (`bot.py`) with `analyst-telegram` console script
- command handlers: `/start`, `/help`, `/regime`, `/calendar`, `/premarket`
- free-text intent routing via regex-based `detect_mode()` (draft, meeting-prep, regime, calendar, QA fallback)
- Telegram-safe 4096-character truncation that preserves disclaimer suffix
- 26 tests covering formatter correctness, truncation edge cases, integration routing, and bot handler wiring

Current limitation: the Telegram bot uses the demo stack (`FileBackedInformationRepository` + `TemplateAgentRuntime`), not the live WS1 engine. Connecting it to the live engine is a WS4 integration task.

Missing:

- real WeCom integration (account, self-built app, callback endpoint)
- connection to live WS1 engine for real-time macro data
- push scheduling (早盘速递 at 7:30am, event-driven 快评)
- per-user memory and context
- interaction logging
- official account and mini-program delivery surfaces
- webhook/server deployment and production operations

### WS3 Customer Discovery

Status: not implemented in code

This remains an operating workstream, not a software module.

### WS4 Integration

Status: partially implemented

Done:

- router patterns
- request-to-engine dispatch
- formatter abstraction across delivery channels
- formatted reply output

Missing:

- WeCom transport/server layer
- logging/tracing
- retries and failure handling
- per-user state

### WS5 Go-To-Market

Status: not implemented in code

This remains a commercial and operational workstream.

---

## Recommended Current Source of Truth

For architecture and implementation:

- `src/analyst/`
- `tests/`
- this file

For product intent and target shape:

- `00-overview/Product_Vision.md`
- `00-overview/Workstream_Plan.md`
- `ws1-engine/`
- `ws2-delivery/`
- `ws4-integration/`

For reference only:

- `code-toolkit/`
- sibling `information/` repo
- sibling `agent_maxwell/` repo

---

## How To Run

From `analyst-project/`:

```bash
# Demo commands (no API keys needed)
PYTHONPATH=src python3 -m analyst regime
PYTHONPATH=src python3 -m analyst route "帮我写一段关于今晚非农数据的客户消息"

# WS1 live engine commands (requires .env with API keys)
PYTHONPATH=src python3 -m analyst refresh --once
PYTHONPATH=src python3 -m analyst live-calendar --scope today
PYTHONPATH=src python3 -m analyst live-calendar --scope upcoming --country US
PYTHONPATH=src python3 -m analyst flash --indicator cpi
PYTHONPATH=src python3 -m analyst briefing
PYTHONPATH=src python3 -m analyst wrap
PYTHONPATH=src python3 -m analyst regime-refresh
PYTHONPATH=src python3 -m analyst schedule

# Telegram bot
ANALYST_TELEGRAM_TOKEN=your-token PYTHONPATH=src python3 -m analyst.delivery.bot

# Tests
python3 -m unittest discover -s tests -v
```

---

## Immediate Next Implementation Targets

1. ~~Replace `data/demo/` with a local Analyst-owned ingestion/store layer.~~ Done (WS1 engine).
2. ~~Add persistent research and interaction storage inside `analyst-project/`.~~ Done (SQLite store with regime snapshots and generated notes).
3. ~~Add a real runtime adapter behind the current deterministic runtime interface.~~ Done (OpenRouter provider + agent loop).
4. Run live end-to-end verification against OpenRouter and FRED with real credentials.
5. Connect WS1 calendar/regime surfaces to delivery and API endpoints, not just local CLI access.
6. Add China-specific ingestion sources (PBOC, NBS, Xinhua).
7. Add a production-grade WeCom delivery transport layer and push scheduler.
8. Begin quality benchmarking against real CICC/CITIC/Huatai notes.
