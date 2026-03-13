# Analyst — Implementation Status

**Status date:** March 13, 2026 (updated after codebase reconstruction, targeted regression verification, and live scraper integration validation)

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

The macro-data stack now also has a standalone sibling codebase at `/home/rick/Desktop/analyst/macro-data-service`.

`analyst-project` now prefers talking to that service over HTTP when `ANALYST_MACRO_DATA_BASE_URL` is set, and falls back to an in-process compatibility adapter only when the external endpoint is unset.

As of March 13, 2026, the largest production modules in storage, delivery, and ingestion were decomposed into feature-scoped implementation modules behind compatibility facades. Public imports and entrypoints stayed stable while internal responsibilities were split into smaller files.

---

## Implemented Now

### Package and entrypoints

- installable project metadata in `pyproject.toml`
- package entrypoint in `src/analyst/__main__.py`
- CLI in `src/analyst/cli.py`
- compatibility macro-data CLI in `src/analyst/macro_data/cli.py`
- Telegram bot entrypoint in `src/analyst/delivery/bot.py`
- `analyst-telegram` console script in `pyproject.toml`
- `analyst-macro-data` console script in `pyproject.toml`
- top-level app factory in `src/analyst/app.py`

### Macro-data service split

Implemented now:

- standalone sibling service repo at `/home/rick/Desktop/analyst/macro-data-service`
- service-side packages extracted there: `src/analyst/macro_data/`, `src/analyst/ingestion/`, `src/analyst/storage/`, `src/analyst/rag/`
- `src/analyst/macro_data/client.py` in `analyst-project` now prefers `HttpMacroDataClient` when `ANALYST_MACRO_DATA_BASE_URL` is configured
- end-to-end HTTP verification test in `tests/test_macro_data_integration.py`

Current limitation:

- the service repo is not yet independently versioned with a remote git origin
- `analyst-project` still retains transitional local copies of the service-side modules for compatibility and local fallback

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
- OpenRouter-backed runtime for generated responses
- runtime request/response context objects with injected delivery-time memory context

Current limitation:

- the delivery runtime still uses demo information inputs rather than the live WS1 store

### Engine layer

Implemented in `src/analyst/engine/`:

- macro Q&A response path (demo)
- draft-generation path (demo)
- meeting-prep path (demo)
- regime-summary note generation (demo)
- pre-market briefing generation (demo)
- **live engine** (`live_service.py`): `LiveAnalystEngine` with OpenRouter LLM backend
- `LiveAnalystEngine` now reads macro-data through the shared `MacroDataClient` boundary instead of directly depending on local ingestion/storage/RAG internals for its macro-data tools
- **agent loop** (`agent_loop.py`): turn-bounded Python tool-calling loop with optional conversation history
- **LLM provider** (`live_provider.py`): OpenRouter chat completions adapter with configurable model
- **prompts** (`live_prompts.py`): Chinese-language institutional macro analyst system/user prompts
- **type contracts** (`live_types.py`): Protocol-based `LLMProvider`, `AgentTool`, conversation types
- live flash commentary (数据快评), morning briefing (早盘速递), after-market wrap (收盘点评)
- regime state refresh with structured JSON regime scoring
- live calendar inspection path with scope routing (`today`, `upcoming`, `recent`, `week`)
- local agent tools for today's calendar, indicator release trends, surprise summaries, recent news, and news search
- tool assembly via `ToolKit` from `analyst.tools` — domain tools + universal tools (web search) composed per-agent

### Portfolio layer

Implemented in `src/analyst/portfolio/`:

- `types.py`: frozen dataclasses — `PortfolioHolding`, `PortfolioConfig`, `RiskContribution`, `Alert`, `VolatilitySnapshot` (all `Serializable`)
- `holdings.py`: CSV import (`load_holdings_from_csv`) and validation (`validate_holdings` — weight sum, duplicates, negatives)
- `config.py`: portfolio config loading from env vars with sensible defaults
- `market_data.py`: yfinance-backed price history and VIX fetching
- `volatility.py`: EWMA covariance, portfolio volatility, risk contributions
- `signals.py`: VIX percentile/regime classification, target vol, scaling signal, alert generation
- `__init__.py`: `compute_portfolio_snapshot()` orchestrator — loads holdings, fetches prices, computes risk, persists to store
- **broker adapter layer** (`brokers/`):
  - `_base.py`: `BrokerAdapter` protocol, `BrokerSyncResult` dataclass, error hierarchy (`BrokerError` → `BrokerAuthError` / `BrokerConnectionError`)
  - `_ibkr.py`: IBKR Client Portal REST adapter — session validation (`POST /sso/validate`), account discovery (`GET /portfolio/accounts`), position fetch (`GET /portfolio/{acct}/positions/0`) with asset class mapping, zero-position skipping, short position abs(), mixed currency warnings, symbol fallback from `contractDesc`
  - `_longbridge.py`: Longbridge (长桥) OpenAPI adapter — HMAC-SHA256 request signing (stdlib only, no new deps), `GET /v1/asset/stock` position fetch, symbol normalization (`AAPL.US`→`AAPL`, `700.HK`→`0700.HK`, `600519.SH`→`600519.SS`), cost-basis fallback with warning when market value unavailable
  - `_tiger.py`: Tiger Brokers (老虎) Open Platform adapter — RSA-SHA256 request signing (lazy `cryptography` import with clear error if not installed), JSON-RPC gateway calls, private key from PEM file or inline content, `_SEC_TYPE_MAP` for security type mapping
  - `__init__.py`: `create_broker_adapter(broker, **kwargs)` factory with generic `(AdapterClass, ConfigClass)` registry — adding a new broker is one file + one registry entry
  - env vars: `ANALYST_IBKR_GATEWAY_URL`, `ANALYST_IBKR_ACCOUNT_ID`, `ANALYST_LONGBRIDGE_APP_KEY/APP_SECRET/ACCESS_TOKEN`, `ANALYST_TIGER_ID/PRIVATE_KEY/ACCOUNT`

### Tools layer

Implemented in `src/analyst/tools/` — 13 tool builders across 12 files:

- `ToolKit` composable builder (`_registry.py`): per-agent tool assembly with `add()`, `merge()`, and `to_list()` — not a global registry, each agent builds its own kit
- web search tool (`_web_search.py`): live web search via OpenRouter's `plugins` API using a separate LLM call (default model: `anthropic/claude-sonnet-4:online`)
  - `WebSearchConfig` with `from_env()` classmethod reusing `analyst.env.get_env_value()`
  - `WebSearchHandler` stateful callable holding config + `requests.Session`
  - `build_web_search_tool()` factory returning an `AgentTool`
  - the web search makes an independent API call — does not pollute the agent's main conversation context
  - returns structured JSON: `summary`, `results` (title/url/snippet), `result_count`
  - the agent decides when to search (Option C) — saves tokens vs auto-search
- live calendar tool (`_live_calendar.py`): fetches economic calendar events live from Investing.com and/or ForexFactory via `curl_cffi` browser impersonation
  - `LiveCalendarHandler` stateful callable that scrapes both sources, persists to SQLite, and returns filtered results
  - `build_live_calendar_tool(store)` factory returning an `AgentTool`
  - supports `source` (investing/forexfactory/both), `importance`, and `country` filters
  - the agent decides when to fetch live data vs reading from the local store
- web page fetch tool (`_web_fetch.py`): fetches and extracts readable content from web pages as markdown via `ArticleFetcher`
- live article tool (`_live_article.py`): fetch and summarize individual articles by URL
- live markets tool (`_live_markets.py`): get current market prices and index levels
- live news tool (`_live_news.py`): search and retrieve recent macro/finance news
- live indicators tool (`_live_indicators.py`): query country-level economic indicators
- live rates tool (`_live_rates.py`): get central bank policy rates
- live rate expectations tool (`_live_rate_expectations.py`): market-implied rate expectations
- **portfolio sync tool** (`_live_portfolio.py`): `sync_portfolio_from_broker` — calls `create_broker_adapter(broker).fetch_positions()`, validates, persists to store, returns structured summary with holdings/skipped/warnings; catches `BrokerAuthError`/`BrokerConnectionError` with clear LLM-readable error messages
- portfolio risk tool (`_live_portfolio.py`): `get_portfolio_risk` — full risk snapshot with actionable suggestions, VIX regime guidance, per-asset risk contributions
- portfolio holdings tool (`_live_portfolio.py`): `get_portfolio_holdings` — current composition with concentration analysis
- VIX regime tool (`_live_portfolio.py`): `get_vix_regime` — lightweight VIX query (no holdings required)
- **image generation tool** (`_image_gen.py`): `generate_image` — generates static images via Volcengine Ark image generation using a configurable model (default: `doubao-seedream-5-0-260128`) with `watermark=false` by default so Seedream does not stamp visible `AI生成` branding on delivered still images
  - `ImageGenConfig` with `from_env()` classmethod reusing `analyst.env.get_env_value()`, env vars: `VOLCENGINE_API_KEY` / `ARK_API_KEY`, `ARK_BASE_URL`, `ANALYST_IMAGE_GEN_MODEL`, `ANALYST_IMAGE_GEN_SIZE`
  - `ImageGenHandler` now supports both generic image generation and structured selfie mode (`mode`, `scene_key`, `scene_prompt`)
  - generic mode also accepts `use_attached_image=true`, which reuses the current inbound Telegram image as the Seedream reference image for variation/edit requests
  - generic mode calls `POST /images/generations`, parses `data[].url` or base64 image payloads, and saves base64 responses to temp files (`/tmp/analyst_gen_{uuid}.{ext}`)
  - selfie mode uses a local persona-state store under `.analyst/media/persona`, bootstraps 3-5 anchor selfies, assembles a fixed 4-block Seedream prompt, composes local reference images into a conditioning image, and updates `latest_selfie` after each successful generation
  - returns structured JSON: `status`, `image_path` or `image_url`, `prompt_used`, and selfie metadata when applicable
  - `build_image_gen_tool()` factory returning an `AgentTool`
- **live photo generation tool** (`_live_photo.py`): `generate_live_photo` — generates a short motion clip via SeedDance, returns a Telegram-ready motion video by default, and can attach a true Apple Live Photo bundle when a macOS packager is available
  - `SeedDanceConfig` with optional env-gated registration (`ANALYST_VIDEO_GEN_PROVIDER=seeddance`, `VOLCENGINE_API_KEY` or `ARK_API_KEY`, `ARK_BASE_URL`, `ANALYST_LIVE_PHOTO_MODEL`)
  - provider abstraction + `SeedDanceVideoProvider` for async task polling and clip download
  - current default Ark model: `doubao-seedance-1-0-pro-fast-251015`
  - `LivePhotoPackager` optionally uses `ffmpeg` plus a macOS `makelive` packager to create the tagged photo/video pair Apple expects
  - generic motion mode remains text-to-video, but also supports `use_attached_image=true` so a user-supplied Telegram image can drive Seedance image-to-video; selfie motion mode now generates a Seedream still first and then sends that image into Seedance image-to-video
  - returns structured JSON with `delivery_video_path` in all successful motion cases, and includes paired Live Photo asset paths / `asset_id` only when Apple packaging is available
  - if SeedDance video generation fails after a selfie still was generated, the tool falls back to that still image; if video generation succeeds but Apple packaging is unavailable, the tool still returns a motion video result
  - `build_optional_live_photo_tool()` registers whenever SeedDance is configured; unsupported runtimes log that they are running in motion-video mode
- both `LiveAnalystEngine._build_tools()` and `build_sales_tools()` now use `ToolKit` to assemble their tool lists, with universal tools (web search, live calendar, web fetch) composed per-agent
- the live-data, stored-data, and RAG-facing tool builders can now proxy through the `MacroDataClient` seam instead of binding directly to local storage or retriever implementations
- the sales agent's `ToolKit` includes all 13 tools when live-photo generation is configured (6 live data + 3 universal + live calendar + portfolio sync + image generation + live-photo generation); otherwise the motion tool is omitted without breaking startup
- adding future universal tools follows the same pattern: create `_new_tool.py` with handler + `build_*_tool()` factory, export from `__init__.py`, agents opt in via `kit.add()`

### Storage layer

Implemented in `src/analyst/storage/`:

- feature-scoped SQLite implementation modules behind the stable `src/analyst/storage/sqlite.py` facade:
  - schema/bootstrap in `sqlite_schema.py`
  - records/types in `sqlite_records.py`
  - market/macro/news/research/memory/group/document/portfolio/calendar domains in dedicated `sqlite_*.py` modules
- SQLite store (`sqlite.py`) with managed connection context manager (commit/rollback/close)
- typed pipeline tables for:
  - market state: `calendar_events`, `market_prices`, `central_bank_comms`, `indicators`, `news_articles`
  - research: `regime_snapshots`, `generated_notes`, `analytical_observations`, `research_artifacts`
  - trader: `trade_signals`, `decision_log`, `position_state`, `performance_records`, `trading_artifacts`
  - sales: `client_profiles`, `conversation_threads`, `conversation_messages`, `delivery_queue`
- frozen dataclass records for all table types
- calendar event enrichment fields including `revised_previous` and `currency`
- news article metadata fields for institution/country/market/asset class/sector/document type/event type/subject/data period/commentary/language/authors/provider
- FTS-backed `news_fts` index with LIKE fallback for SQLite builds without FTS5
- time-decay + impact-weight news ranking via `get_news_context()`
- query methods for market state, typed research publication, trader lineage, and sales profile/thread/delivery retrieval
- upsert semantics with UNIQUE constraints for deduplication
- foreign-key-enforced lineage from trader outputs back to `research_artifacts`

### Refactor validation

Validated on March 13, 2026:

- targeted regression suite passed locally:
  - `tests/test_oecd.py`
  - `tests/test_oecd_sources.py`
  - `tests/test_gov_report.py`
  - `tests/test_companion_checkins.py`
  - `tests/test_telegram.py`
  - `tests/test_memory.py`
  - `tests/test_news_ingestion.py`
  - result: `221 passed`
- live integration suite passed against real endpoints:
  - `pytest tests/test_scrapers.py -m live -v`
  - result: `5 passed`

### Memory layer

Implemented in `src/analyst/memory/`:

- `ClientProfileUpdate` data model (`profile.py`): 17 dimensions — language, risk profile, watchlist, expertise level, mood, emotional trend, stress level, investment horizon, institution type, risk preference, asset focus, market focus, activity, confidence, personal facts, notes, response style
- context builders (`service.py`):
  - `build_research_context()` — regime snapshots + recent notes + observations
  - `build_trading_context()` — positions, decisions, performance
  - `build_sales_context()` — client interactions + profile for sales agent personalization, including absence awareness (`days_since_last_active` computed from `last_active_at`)
  - `record_sales_interaction()` — persists raw messages to `conversation_messages` and extracts/accumulates client profile dimensions via LLM
- context rendering (`render.py`): `RenderBudget` for text formatting with character limits
- conversation recording: every bot reply triggers `record_sales_interaction()`, which stores the raw message exchange and updates the client profile — all chat messages are recorded for later improvement
- profile accumulation: dimensions build up across conversations — each new interaction can add or refine profile fields without overwriting previous data
- emotional memory: `emotional_trend` (improving/declining/stable/volatile) and `stress_level` (low/moderate/high/critical) are tracked by the LLM across conversations and persisted in SQLite — the agent uses these to proactively check on stressed clients
- personal facts memory: `personal_facts` list stores personal details the client mentions (family, hobbies, life events) — capped at 20, re-mentioned facts refresh recency so they survive the cap; the agent references these naturally in conversation

### Ingestion layer

Implemented in `src/analyst/ingestion/`:

- `InvestingCalendarClient`: economic calendar scraper (Investing.com) — uses `curl_cffi` for Cloudflare TLS bypass
- `ForexFactoryCalendarClient`: economic calendar scraper (ForexFactory) — uses `curl_cffi` for Cloudflare TLS bypass
- `TradingEconomicsCalendarClient`: economic calendar scraper with per-event importance (3 requests) — uses `curl_cffi`
- `http_transport.py`: transport factory (`create_cf_session`) using `curl_cffi` browser impersonation with graceful fallback to `requests.Session`
- `FREDIngestionClient`: FRED API adapter for 25+ macro series (inflation, employment, growth, rates, liquidity, FX, credit)
- `FedIngestionClient`: Fed RSS feed parser for press releases, speeches, and testimony
- `MarketPriceClient`: cross-asset price scraper via yfinance (equities, FX, bonds, commodities, crypto)
- `NewsIngestionClient`: macro-finance RSS pipeline with URL deduplication, article fetch, structured extraction, and persistence
- `news_feeds.py`: 140+ curated RSS/Google News feed definitions by category
- `news_fetcher.py`: article extraction with Google News proxy resolution + readability/markdownify
- `news_extract.py`: LLM metadata extraction with keyword fallback and canonical finance category mapping
- `IngestionOrchestrator`: refresh-all and schedule orchestrator with configurable intervals
- Investing calendar retry/backoff and multi-day refresh window (`days_back=1`, `days_forward=3`)
- Investing calendar parsing for currency text and revised previous values
- scheduled news refresh every 15 minutes
- standalone scrapers (`src/analyst/ingestion/scrapers/`):
  - `InvestingNewsClient`: news with pagination (`page` param + `fetch_all_news`), comment count capture
  - `ForexFactoryNewsClient`: news with pagination, thumbnail capture
  - `TradingEconomicsNewsClient`: news stream with pagination (`start`/`count` + `fetch_all_news`), image/thumbnail/html/type capture
  - `TradingEconomicsIndicatorsClient`: indicator tables with native tab-pane taxonomy (falls back to keyword heuristic)
  - `TradingEconomicsMarketsClient`: market quotes with `data-symbol` and `data-decimals` capture

### Environment resolver

Implemented in `src/analyst/env.py`:

- multi-file `.env` fallback chain (project `.env` → sibling `information/.env`)
- `get_env_value()` with multi-key lookup and default
- `lru_cache`-based file reading with `clear_env_cache()` for testing

### Delivery layer

Implemented in `src/analyst/delivery/`:

- WeCom-style message formatting
- Telegram-specific message formatting
- Telegram polling bot with persona-driven agent loop (陈襄)
  - persona system prompt (`soul.py`): identity, personality, language mirroring, behavioral boundaries, tool usage instructions (including broker sync for IBKR/Longbridge/Tiger, image generation, and optional live-photo generation), emotional support guidance, time-of-day awareness, absence awareness, proactive emotional warmth
  - `GROUP_CHAT_ADDENDUM` in `soul.py`: group chat behavioral rules (observe silently, reply only on @mention, adapt to group context)
  - all responses generated by LLM — no hardcoded text
  - agent loop with 12-13 tools depending on Seedance configuration: 6 live data scrapers + web search + web fetch + live calendar + article fetch + portfolio sync + image generation, plus optional live-photo generation
  - `MediaItem` dataclass and `_extract_media()` post-processor: scans agent loop message history for `generate_image` and `generate_live_photo` tool results, attaching photo or video media to `SalesChatReply`
  - inbound media handling: the bot accepts Telegram photos and image documents, converts them into OpenRouter multimodal image input, and exposes the same attachment to generation tools when `use_attached_image=true`
  - media delivery: bot sends generated images as Telegram photos and motion selfies as Telegram videos, with managed temp-file cleanup after send
  - per-user conversation history (12 recent messages retrieved for continuity)
  - commands: `/start`, `/help`, `/regime`, `/calendar`, `/premarket`
  - free-text messages plus inbound images routed through agent with autonomous tool access
  - reply-to-message context: when a user replies to a previous message, the referenced text is extracted and included in the LLM prompt (`_extract_reply_context`), supporting partial quotes via Telegram's quote feature; original text preserved for history recording
  - group chat support: bot observes silently in group chats, responds only when @mentioned
  - typing simulation: length-proportional delay between multi-bubble messages with "typing..." indicator, mimicking real human typing rhythm
  - time-of-day awareness: current time (Asia/Shanghai) injected into every system prompt — agent can naturally reference late nights, early mornings, weekends
  - sales-memory hydration from `client_profiles`, `conversation_messages`, and `delivery_queue`
  - structured sales-memory persistence after each free-text interaction via `record_sales_interaction()`
  - 17 client profile dimensions extracted and accumulated across conversations (including emotional trend, stress level, and personal facts)
- sales chat agent (`sales_chat.py`): standalone agent loop with tool wiring, client profile management, conversation history, time injection, `build_sales_tools()` factory, and media extraction from tool results
- compliance disclaimers (formatter layer, kept for other consumers)
- calendar reply formatting
- Telegram-safe 4096-character truncation that preserves disclaimers

### Integration layer

Implemented in `src/analyst/integration/`:

- keyword-based mode detection
- message routing to engine methods
- channel-agnostic formatter protocol
- generic formatted reply generation
- optional `memory_context` injection for delivery-time personalization
- backward-compatible `handle_wecom_message()` alias

### Tests

Implemented in `tests/`:

- `test_broker_ibkr.py` (54 tests) for broker adapter layer: IBKR asset class mapping + position mapping (single/empty/mixed currencies/zero skipped/short abs/weight sum/symbol fallback) + session validation (valid/expired/401/unreachable); Longbridge symbol normalization (US/HK pad/Shanghai/Shenzhen/passthrough) + position mapping (single/empty/zero skipped/mixed currencies/cost basis warning/market value preferred/weight sum) + session validation (valid/expired/missing creds/unreachable); Tiger sec_type mapping + position mapping (single/empty/zero skipped/mixed currencies/weight sum) + session validation (missing creds/auth failure/unreachable/cryptography not installed); factory tests (create all 3 brokers, unknown raises, available listed in error)
- `test_news_ingestion.py` for RSS feed registry, classifier utility, article fetcher, SQLite news storage, extraction fallback behavior, and news ingestion/retrieval regressions
- `test_memory.py` for research/trader/sales pipeline memory behavior, client isolation, delivery gating, profile accumulation, trader lineage constraints, naive/aware timestamp handling in absence calculation, personal facts persistence and recency-refresh dedup under cap, and emotional trend/stress level persistence
- `test_product_layer.py` for product-layer smoke tests
- `test_telegram.py` for Telegram formatter, truncation, routing, bot wiring, agent-loop chat flow (persona, history, tools, truncation, error fallback), reply-to-message context extraction, and media delivery cleanup
- `test_ws1_engine.py` for WS1 live engine and calendar paths: store CRUD/upsert/filter/range queries, scraper retry behavior, flash commentary tool-calling loop with persistence, no-event error path, regime payload parsing with malformed JSON, env fallback chain, and CLI routing for refresh/flash/regime-refresh/live-calendar

---

## Not Implemented Yet

### Data ingestion (remaining)

Not yet implemented inside `analyst-project/`:

- live government-report crawling (BLS, BEA beyond FRED)
- China-specific sources (PBOC, NBS, Xinhua, Caixin)
- live document parsing

Note: calendar scraping (Investing.com, ForexFactory), FRED series, Fed RSS, yfinance market prices, and RSS-based news ingestion are now implemented in `src/analyst/ingestion/`.

### Agent backend (remaining)

Not yet implemented:

- prompt/version management beyond local code
- retry/backoff for LLM provider errors
- multi-model comparison (DeepSeek, Qwen alternatives)

Note: OpenRouter LLM integration, a Python agent loop with tool calling, and product-owned memory/context assembly are now implemented in `src/analyst/engine/`, `src/analyst/memory/`, and `src/analyst/storage/`.

### Product storage (remaining)

Not yet implemented:

- CRM sync / external profile store
- production audit export / compliance reporting surface

Note: SQLite-backed research, trader, and sales memory stores are now implemented in `src/analyst/storage/`.

### Delivery infrastructure

Not yet implemented:

- actual WeCom bot/server
- official account publishing
- mini-program endpoints
- scheduler for briefing pushes
- webhook handling

### Operations

Partially implemented:

- Telegram bot deployed to Contabo VPS via rsync (no `.git` on server)
- deployment workflow: rsync code → pip install → pkill old process → nohup start new process
- `.env` on server holds production tokens (excluded from rsync)
- bot logs to `~/analyst-bot.log` on server

Not yet implemented:

- systemd service / process supervisor (currently nohup + disown)
- config/env management beyond `.env` files
- observability / structured logging
- retry logic for LLM provider errors
- production auth/compliance logging

---

## Workstream Status

### WS1 Macro Engine

Status: Month 1 scope implemented

Done:

- engine contract layer
- regime summary, pre-market briefing, Q&A, draft, and meeting-prep paths (demo)
- SQLite store with typed market/research/trader/sales tables and managed connections
- ingestion adapters: Investing.com calendar, ForexFactory calendar, TradingEconomics calendar/news/indicators/markets, FRED API (25+ series), Fed RSS, yfinance market prices, RSS news ingestion
- enriched calendar event storage with `revised_previous` and `currency`
- news article storage with structured metadata, provider tracking, and FTS-backed retrieval
- calendar query surface for recent, upcoming, today, week, and indicator-history views
- news query surface for latest/search/context views with time-decay ranking
- ingestion orchestrator with refresh-all and scheduled polling
- Investing calendar retry/backoff and multi-day fetching
- RSS article fetch/extract pipeline with keyword/LLM metadata extraction
- Python agent loop with turn-bounded tool calling
- OpenRouter LLM provider with configurable model
- Chinese-language institutional macro prompts (数据快评, 早盘速递, 收盘点评, regime refresh)
- regime state scoring with clamped numeric axes and cross-asset implications
- environment resolver with multi-file `.env` fallback
- CLI commands: refresh, schedule, flash, briefing, wrap, regime-refresh, live-calendar, news-refresh, news-latest, news-search, news-feeds, portfolio-import, portfolio-risk, portfolio-sync
- agent tools for recent releases, today's calendar, indicator trends, market snapshot, Fed comms, indicator history, latest regime state, surprise summaries, recent news, news search, web search, live calendar fetch, portfolio risk, portfolio holdings, VIX regime, portfolio sync from broker, image generation, and live-photo generation
- unified tools layer (`src/analyst/tools/`): `ToolKit` composable builder + `web_search` via OpenRouter plugins API + `fetch_live_calendar` via curl_cffi (agent-initiated) + `generate_image` via Volcengine Ark (`doubao-seedream-5-0-260128`) + `generate_live_photo` via SeedDance with Telegram video delivery and optional macOS `makelive` packaging for future Apple channels
- portfolio risk pipeline: CSV import, broker sync (IBKR/Longbridge/Tiger), EWMA covariance, VIX regime, agent-actionable tools
- auto-refresh staleness check on `get_today_calendar` and `get_upcoming_calendar` tools (refreshes calendar if data is >1 hour stale)
- error isolation in `refresh_calendar`: Investing.com and ForexFactory failures are independent — one source failing does not block the other
- research publication into `research_artifacts` plus `analytical_observations`
- typed trader-state schema with FK lineage ready for a future trader runtime
- focused WS1 tests covering store, scraper retry paths, loop, env, CLI, calendar query behavior, news ingestion, search, and ranking regressions

Missing:

- live end-to-end verification against OpenRouter/FRED (tested locally with mocks only)
- China-specific ingestion (PBOC, NBS, Xinhua, Caixin)
- non-RSS premium/news API sources (Finnhub, Alpha Vantage) if broader coverage is needed
- evaluation harness and quality benchmarking against real sell-side notes
- live trader runtime on top of the implemented trader tables

### WS2 Delivery Shell

Status: Persona-driven Telegram agent bot deployed to production server with full tool access and group chat support. WeCom transport not yet started.

Done:

- WeCom-style and Telegram-specific reply formatting with per-mode compliance disclaimers
- `ChannelFormatter` protocol for channel-agnostic delivery (`router.py`)
- Telegram agent bot (`bot.py`) with persona 陈襄 (`soul.py`) and `analyst-telegram` console script
- persona system prompt: high-EQ institutional sales professional, auto-detects and mirrors user language (Chinese/English), warm conversational style, emotional support guidance, tool usage instructions
- `GROUP_CHAT_ADDENDUM` in `soul.py`: group chat behavioral rules — observe silently, reply only on @mention, adapt tone to group context
- all responses generated by LLM through the agent loop — no hardcoded welcome/help text
- 12-13 agent tools for live data access depending on Seedance configuration: `fetch_live_calendar`, `get_live_article`, `get_live_markets`, `get_live_news`, `get_live_indicators`, `get_live_rates`, `get_live_rate_expectations`, `web_search`, `web_fetch`, `sync_portfolio_from_broker`, `generate_image`, optional `generate_live_photo`, plus regime/calendar/briefing tools
- sales chat agent (`sales_chat.py`): standalone agent loop with `build_sales_tools()` factory, client profile management, conversation history, and media extraction from tool results
- per-user conversation history (12 recent messages retrieved for continuity)
- command handlers: `/start`, `/help`, `/regime`, `/calendar`, `/premarket`
- free-text messages routed through agent with full tool access
- group chat support: bot detects group chats, observes silently, responds only when @mentioned with group-specific persona addendum
- Telegram-safe 4096-character truncation that preserves disclaimer suffix
- structured sales memory for Telegram:
  - `client_profiles` — 14 dimensions extracted and accumulated
  - `conversation_threads` / `conversation_messages` — all messages recorded
  - `delivery_queue`
  - `record_sales_interaction()` called after every bot reply for persistence
- client/thread sales context is injected into the agent loop before free-text replies
- deployed to Contabo VPS via rsync, running as background process

### Verification added in this update

- `tests/test_macro_data_integration.py`: starts the extracted `macro-data-service` as a separate process, points `analyst-project` to it over localhost HTTP, and verifies recent-release and news queries through `HttpMacroDataClient`

Missing:

- real WeCom integration (account, self-built app, callback endpoint)
- push scheduling (早盘速递 at 7:30am, event-driven 快评)
- official account and mini-program delivery surfaces

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
- live WS1-backed delivery instead of the current demo information layer

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
# Preferred decoupled path
cd /home/rick/Desktop/analyst/macro-data-service
python -m venv .venv
. .venv/bin/activate
pip install -e .
macro-data-service serve --host 127.0.0.1 --port 8765

export ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765
export ANALYST_MACRO_DATA_API_TOKEN=

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

# Portfolio commands
PYTHONPATH=src python3 -m analyst portfolio-import data/demo/holdings.csv
PYTHONPATH=src python3 -m analyst portfolio-risk --json
PYTHONPATH=src python3 -m analyst portfolio-sync --broker ibkr --dry-run
PYTHONPATH=src python3 -m analyst portfolio-sync --broker longbridge --dry-run
PYTHONPATH=src python3 -m analyst portfolio-sync --broker tiger --dry-run

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
