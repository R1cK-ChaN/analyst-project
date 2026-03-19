# Analyst — Implementation Status

**Status date:** March 20, 2026 (updated after research agent decoupled to standalone HTTP service)

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

The old split folders such as `analyst-runtime/`, `analyst-information/`, `analyst-engine/`, `analyst-delivery/`, and `analyst-integration/` have been removed. All live code now belongs under `src/analyst/`.

The sibling `information/` repo is currently reference material only. The standalone project does not import it at runtime.

The macro-data stack now also has a standalone sibling codebase at `/home/rick/Desktop/analyst/macro-data-service`.

The research agent has been extracted to a standalone sibling service at `/home/rick/Desktop/analyst/research-service` (GitHub: `R1cK-ChaN/research-service`). The companion calls it over HTTP via `ANALYST_RESEARCH_BASE_URL`.

`analyst-project` now prefers talking to both services over HTTP when the respective `_BASE_URL` env vars are set.

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

Implemented and completed:

- standalone sibling service repo at `/home/rick/Desktop/analyst/macro-data-service`
- service-side packages extracted there: `src/analyst/macro_data/`, `src/analyst/ingestion/`, `src/analyst/storage/`, `src/analyst/rag/`
- `src/analyst/macro_data/client.py` in `analyst-project` prefers `HttpMacroDataClient` when `ANALYST_MACRO_DATA_BASE_URL` is configured
- end-to-end HTTP verification test in `tests/test_macro_data_integration.py`
- **decoupling completed**: `ingestion/` package fully removed from `analyst-project` — all scraper and data-fetching code lives exclusively in `macro-data-service`
- `tools/` and `storage/` have zero ingestion imports — all data operations route through `MacroDataClient`
- `LocalMacroDataService` retains store-based operations (calendar, news, indicators from SQLite); live-fetch operations return a clear "requires macro-data-service" error
- utility functions (`normalize_indicator_name`, `canonicalize_url`, `content_hash`) extracted to `src/analyst/utils.py`

### Research service split

Implemented and completed:

- standalone sibling service repo at `/home/rick/Desktop/analyst/research-service` (GitHub: `R1cK-ChaN/research-service`)
- research agent (20 tools, 13 operators, PLAN→ACQUIRE→COMPUTE→INTERPRET pipeline) fully extracted
- `src/analyst/research/client.py` provides `HttpResearchClient` + `coerce_research_client()`
- `src/analyst/research/delegate.py` provides `build_research_delegate_tool()` — creates a tool named `research_agent` with identical parameters and return shape
- companion connects via `ANALYST_RESEARCH_BASE_URL` env var; without it, companion runs with image/photo tools only
- **decoupling completed**: `agents/research/` directory and `agents/companion/spec_builder.py` removed from `analyst-project`
- research service runs on port 8766 by default, requires `OPENROUTER_API_KEY` and `ANALYST_MACRO_DATA_BASE_URL`

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
- **live engine** (`live_service.py`): `LiveAnalystEngine` with pluggable LLM backend
- `LiveAnalystEngine` now reads macro-data through the shared `MacroDataClient` boundary instead of directly depending on local ingestion/storage/RAG internals for its macro-data tools
- **agent loop** (`agent_loop.py`): turn-bounded Python tool-calling loop with optional conversation history
- **executor layer** (`executor.py`): separates product-owned host-loop execution from provider-native execution
  - `HostLoopExecutor`: current Python tool-calling loop over OpenRouter/Anthropic-compatible chat completions
  - `ClaudeCodeExecutor`: native Claude Code turn execution for direct replies, with optional built-in web tools and shared analyst MCP tools
  - `LegacyLoopExecutor`: compatibility adapter so existing `PythonAgentLoop` callers and tests continue to work during migration
- **LLM/backends namespace** (`engine/backends/`): import-stable backend entrypoints for OpenRouter/Anthropic chat completions and the Claude Code CLI adapter
  - `live_provider.py` remains as the compatibility implementation module while new internal imports target `engine/backends/`
  - Claude Code now supports both host-loop-compatible `complete()` calls and native-agent `complete_native()` calls
- **runtime stack** (`runtime/`): layered conversation runtime and platform adapters
  - `chat.py`: prompt assembly, execution planning, reply post-processing, and public chat/runtime helpers
  - `conversation_service.py`: one-turn orchestration for context hydration, runtime invocation, and persistence
  - `environment_adapter.py`: normalized `ConversationInput` / `ProactiveConversationInput` contracts plus CLI/Telegram builders
  - `platform/telegram.py`: Telegram-specific turn preparation, persistence policy, and proactive scheduling rules
  - `capabilities.py`: declarative capability registry for host tools, native tool sets, MCP scopes, and sub-agent tool matrices
- **prompts** (`live_prompts.py`): Chinese-language institutional macro analyst system/user prompts
- **type contracts** (`live_types.py`): Protocol-based `LLMProvider`, `AgentTool`, conversation types
- live flash commentary (数据快评), morning briefing (早盘速递), after-market wrap (收盘点评)
- regime state refresh with structured JSON regime scoring
- live calendar inspection path with scope routing (`today`, `upcoming`, `recent`, `week`)
- local agent tools for today's calendar, indicator release trends, surprise summaries, recent news, and news search
- tool assembly via `ToolKit` from `analyst.tools` — domain tools + universal tools (web search) composed per-agent
- Claude Code native turns can now access a shared analyst-owned read-only tool subset through the local MCP bridge in `src/analyst/mcp/`

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

### Sandbox layer

Implemented in `src/analyst/sandbox/`:

- `policy.py`: AST-based code validation — blocks forbidden modules (`os`, `subprocess`, `socket`, etc.), forbidden builtins (`exec`, `eval`, `open`, etc.), and dunder attribute access (`__subclasses__`, `__globals__`, etc.)
- `container_runner.py`: Docker CLI wrapper with dependency injection for testability (same `runner=subprocess.run` pattern as `ClaudeCodeProvider` and `LivePhotoPackager`)
- `manager.py`: public `SandboxManager` API — validates code via policy, executes in ephemeral Docker container, returns structured result
- `limits.py`: `SandboxLimits` config with `from_env()` classmethod (memory, CPU, timeout, image name)
- `docker/Dockerfile`: minimal Python 3.11 image with numpy, pandas, scipy, matplotlib, statsmodels
- `docker/runner.py`: in-container executor — reads JSON from stdin, execs code, captures `result` variable and print output, writes JSON to stdout
- Docker security constraints: `--network none`, `--read-only`, `--tmpfs /tmp`, `--tmpfs /workspace`, `--memory=512m`, `--cpus=1`, no host env vars passed (`env={}`)
- graceful degradation: if Docker is unavailable, the tool returns a structured error dict instead of crashing

### Analysis layer

Implemented in `src/analyst/analysis/`:

- **artifact cache** (`artifact.py`, `store.py`):
  - `ArtifactIdentity`: deterministic 16-hex-char SHA-256 ID from (artifact_type, parameters, time_context)
  - `Artifact` frozen dataclass with result dict, dependencies list, created_at, expires_at
  - `DEFAULT_TTL_SECONDS`: per-type TTL (market_snapshot: 1h, macro_indicator: 24h, research_analysis: 4h, etc.)
  - SQLite-backed storage via `SQLiteAnalysisMixin` (upsert, get_fresh with TTL check, expire_stale, list_by_type)
  - `ArtifactStore` convenience wrapper for the mixin

- **operator algebra** (`operators/`): 13 deterministic compute operators across 6 categories:
  - Data: `fetch_series` (wraps store indicator history → typed Series), `fetch_dataset` (calendar/news/fed/prices → typed Dataset)
  - Transform: `pct_change` (MoM/QoQ/YoY), `rolling_stat` (mean/std/min/max/median), `resample` (frequency change), `align` (time-axis alignment), `combine` (multi-series aggregation)
  - Metric: `trend` (linear direction + slope), `difference` (spread with z-score), `regression` (OLS with R²)
  - Relation: `compare` (two-series summary), `correlation` (Pearson r with strength)
  - Signal: `threshold_signal` (classification with crossover detection)
  - All operators run in host process via numpy — no Docker overhead
  - Auto-cache results as artifacts via the artifact cache

- **type system** (`operators/types.py`):
  - 5 canonical types: Series, Dataset, Metric, Signal, Text
  - Every `OperatorSpec` declares `input_types` (what type each input expects) and `output_type` (what it produces)
  - `is_compatible()` with coercion rules (Dataset can downcast to Series)
  - `check_composability()` validates upstream → downstream type compatibility
  - `validate_chain()` checks two OperatorSpecs can be composed
  - `run_operator()` auto-validates typed inputs at runtime
  - `TypeMismatchError` with clear messages for debugging

- **operator registry** (`operators/registry.py`):
  - `OperatorSpec` frozen dataclass with name, operator_type, description, input_types, output_type, handler
  - `OPERATOR_REGISTRY` global dict of all registered operators
  - `run_operator()` with context injection for store-dependent operators (fetch_series, fetch_dataset)
  - Future-ready for planner validation and graph builder

- **soft pipeline policy**: research agent system prompt enforces PLAN → ACQUIRE → COMPUTE → INTERPRET workflow with tool priority (analysis operators > data tools > python sandbox)

### Tools layer

Implemented in `src/analyst/tools/` — 17 tool builders across 16 files:

- `ToolKit` composable builder (`_registry.py`): per-agent tool assembly with `add()`, `merge()`, and `to_list()` — not a global registry, each agent builds its own kit
- **shared MCP bridge** (`src/analyst/mcp/`): local stdio MCP server exposing a safe read-only subset of analyst-owned tools to Claude Code
  - `shared_tools.py`: source-of-truth registry for MCP-shareable tools and role-level shared tool sets
  - `server.py`: minimal MCP server implementing `initialize`, `tools/list`, and `tools/call`
  - `bridge.py`: Claude Code MCP config writer used by native Claude turns
  - current shared subset: live news/article/markets/indicators/rates/VIX plus store-backed calendar/news/Fed comms/indicator history/research search and read-only portfolio views
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
- **sandboxed Python analysis tool** (`_python_analysis.py`): `run_python_analysis` — executes Python code in a Docker sandbox for data analysis, statistical calculations, and chart generation; code is AST-validated via `sandbox/policy.py` before execution; available to research agent, user chat surface, and `data_deep_dive` / `research_lookup` sub-agents
- **analysis operator tool** (`_analysis_operators.py`): `run_analysis` — unified dispatch tool for 13 built-in operators; auto-caches results as artifacts; preferred over python sandbox for standard computations
- **artifact cache tools** (`_artifact_cache.py`): `check_artifact_cache` (lookup before compute) + `store_artifact` (cache after compute) — enables cross-run result reuse with TTL-based freshness
- both `LiveAnalystEngine._build_tools()` and `build_user_chat_tools()` now use `ToolKit` to assemble their tool lists, with universal tools (web search, live calendar, web fetch) composed per-agent
- all live-data tool builders route through the `MacroDataClient` seam — no direct scraper imports in `tools/`
- the user chat agent's `ToolKit` includes all 13 tools when live-photo generation is configured (6 live data + 3 universal + live calendar + portfolio sync + image generation + live-photo generation); otherwise the motion tool is omitted without breaking startup
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

### Test validation

Validated on March 15, 2026:

- full test suite: `528 passed` (scraper tests moved to `macro-data-service`)
- sandbox tests: `36 passed` (policy, container runner, manager, tool — all mocked, no Docker needed)
- artifact cache tests: `24 passed` (identity determinism, storage round-trip, TTL expiry, tool handlers)
- analysis operator tests: `54 passed` (all 13 operators, type system, composability validation, registry, tool handler)
- live sandbox tests: 8 scenarios verified against real Docker (numpy, pandas, scipy, matplotlib, data pass-through, policy rejection, runtime error, stdout capture)

### Memory layer

Implemented in `src/analyst/memory/`:

- `ClientProfileUpdate` data model (`profile.py`): 17 dimensions — language, risk profile, watchlist, expertise level, mood, emotional trend, stress level, investment horizon, institution type, risk preference, asset focus, market focus, activity, confidence, personal facts, notes, response style
- context builders (`service.py`):
  - `build_research_context()` — regime snapshots + recent notes + observations
  - `build_trading_context()` — positions, decisions, performance
  - `build_user_context()` — client interactions + profile for user chat agent personalization, including absence awareness (`days_since_last_active` computed from `last_active_at`)
  - `record_user_interaction()` — persists raw messages to `conversation_messages` and extracts/accumulates client profile dimensions via LLM
- context rendering (`render.py`): `RenderBudget` for text formatting with character limits
- conversation recording: every bot reply triggers `record_user_interaction()`, which stores the raw message exchange and updates the client profile — all chat messages are recorded for later improvement
- profile accumulation: dimensions build up across conversations — each new interaction can add or refine profile fields without overwriting previous data
- emotional memory: `emotional_trend` (improving/declining/stable/volatile) and `stress_level` (low/moderate/high/critical) are tracked by the LLM across conversations and persisted in SQLite — the agent uses these to proactively check on stressed clients
- personal facts memory: `personal_facts` list stores personal details the client mentions (family, hobbies, life events) — capped at 20, re-mentioned facts refresh recency so they survive the cap; the agent references these naturally in conversation

### Ingestion layer

**Removed from `analyst-project` as of March 15, 2026.** All scraper and data-fetching code now lives exclusively in the standalone `macro-data-service` repo at `/home/rick/Desktop/analyst/macro-data-service`.

The `analyst-project` consumes data through `MacroDataClient` (HTTP when `ANALYST_MACRO_DATA_BASE_URL` is set, or `LocalMacroDataService` store-based fallback for read-only operations).

### Environment resolver

Implemented in `src/analyst/env.py`:

- multi-file `.env` fallback chain (project `.env` → sibling `information/.env`)
- `get_env_value()` with multi-key lookup and default
- `lru_cache`-based file reading with `clear_env_cache()` for testing

### Delivery layer

Implemented in `src/analyst/delivery/`:

- WeCom-style message formatting
- Telegram-specific message formatting
- Telegram polling bot with persona-driven agent execution (陈襄)
  - persona system prompt (`soul.py`): identity, personality, language mirroring, behavioral boundaries, tool usage instructions (including broker sync for IBKR/Longbridge/Tiger, image generation, and optional live-photo generation), emotional support guidance, time-of-day awareness, absence awareness, proactive emotional warmth
  - capability overlays are now appended per turn so prompt instructions can distinguish host-managed tools, Claude native tools, and shared analyst MCP tools
  - `GROUP_CHAT_ADDENDUM` in `soul.py`: group chat behavioral rules (observe silently, reply only on @mention, adapt to group context)
  - all responses generated by LLM — no hardcoded text
  - host-loop path still exposes 12-13 tools depending on Seedance configuration: 6 live data scrapers + web search + web fetch + live calendar + article fetch + portfolio sync + image generation, plus optional live-photo generation
  - Claude Code native-agent path is now supported behind `ANALYST_CLAUDE_CODE_USE_NATIVE_AGENT=1`
    - native Claude turns use built-in `WebSearch` / `WebFetch`
    - selected analyst-owned read-only tools are shared through the local MCP bridge
    - image-generation, live-photo, and edit-style turns still stay on the host-loop path
  - `MediaItem` dataclass and `_extract_media()` post-processor: scans agent loop message history for `generate_image` and `generate_live_photo` tool results, attaching photo or video media to `UserChatReply`
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
  - structured sales-memory persistence after each free-text interaction via `record_user_interaction()`
  - 17 client profile dimensions extracted and accumulated across conversations (including emotional trend, stress level, and personal facts)
- chat runtime (`runtime/chat.py`): standalone chat execution layer with tool wiring, client profile management, conversation history, time injection, role-specific shared MCP tool lists, capability overlays, turn-execution planning, and media extraction from tool results
- conversation service (`runtime/conversation_service.py`): shared one-turn orchestration for context building, reply generation, and persistence
- environment adapters (`runtime/environment_adapter.py`): normalized conversation input contracts for CLI, Telegram, and proactive turns
- Telegram platform policy (`runtime/platform/telegram.py`): Telegram-specific turn preparation, persistence policy, and proactive-checkin rules separated from `delivery/bot.py`
- capability registry (`runtime/capabilities.py`): declarative registry for companion/user-chat/content-runtime surfaces, MCP scopes, native tool names, and sub-agent tool assignments
- compatibility facade (`delivery/user_chat.py`): legacy import surface that now forwards to `runtime/chat.py` while preserving existing callers and tests
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

Implemented in `tests/` — 528 tests total:

- `test_broker_ibkr.py` (54 tests) for broker adapter layer: IBKR, Longbridge, Tiger position mapping + session validation + factory
- `test_sandbox.py` (36 tests) for sandbox policy (AST validation), container runner (Docker CLI mock), manager (orchestration), and tool builder
- `test_artifact_cache.py` (24 tests) for artifact identity determinism, SQLite storage round-trip, TTL expiry, upsert overwrite, lookup/store tool handlers
- `test_analysis_operators.py` (54 tests) for all 13 operators, type system (composability, coercion, mismatch detection), registry dispatch, auto-caching, tool builder schema
- `test_memory.py` for research/trader/sales pipeline memory behavior, client isolation, delivery gating, profile accumulation, emotional trend/stress level persistence
- `test_product_layer.py` for product-layer smoke tests
- `test_telegram.py` for Telegram formatter, truncation, routing, bot wiring, agent-loop chat flow, media delivery cleanup
- `test_ws1_engine.py` for WS1 live engine and calendar paths: store CRUD, flash commentary loop, regime payload parsing, env fallback chain, CLI routing
- `test_url_canon.py` for URL canonicalization and content fingerprinting utilities (now imported from `analyst.utils`)
- `test_web_fetch.py` for web fetch tool factory and MacroDataClient integration
- `test_cli.py` for CLI companion chat, media gen commands

---

## Not Implemented Yet

### Data ingestion (remaining)

All ingestion code now lives in the standalone `macro-data-service` repo. Not yet implemented there:

- live government-report crawling (BLS, BEA beyond FRED)
- China-specific sources (PBOC, NBS, Xinhua, Caixin)
- live document parsing

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
- executor split between product-owned host loop and Claude Code native execution
- OpenRouter/Anthropic providers plus Claude Code CLI adapter, fronted through `engine/backends/`
- Chinese-language institutional macro prompts (数据快评, 早盘速递, 收盘点评, regime refresh)
- regime state scoring with clamped numeric axes and cross-asset implications
- environment resolver with multi-file `.env` fallback
- CLI commands: refresh, schedule, flash, briefing, wrap, regime-refresh, live-calendar, news-refresh, news-latest, news-search, news-feeds, portfolio-import, portfolio-risk, portfolio-sync
- agent tools for recent releases, today's calendar, indicator trends, market snapshot, Fed comms, indicator history, latest regime state, surprise summaries, recent news, news search, web search, live calendar fetch, portfolio risk, portfolio holdings, VIX regime, portfolio sync from broker, image generation, live-photo generation, sandboxed Python analysis, analysis operators (13 built-in), and artifact cache (lookup + store)
- unified tools layer (`src/analyst/tools/`): `ToolKit` composable builder + `web_search` via OpenRouter plugins API + `fetch_live_calendar` via MacroDataClient + `generate_image` via Volcengine Ark + `generate_live_photo` via SeedDance + `run_python_analysis` via Docker sandbox + `run_analysis` via operator registry + `check_artifact_cache` / `store_artifact` via SQLite artifact store
- research agent has 20 tools total with soft pipeline policy (PLAN → ACQUIRE → COMPUTE → INTERPRET) and typed operator algebra for composable analysis
- local MCP bridge (`src/analyst/mcp/`) so Claude Code native turns can use selected analyst-owned read-only tools without duplicating tool logic
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
- all responses generated by LLM through the execution layer — no hardcoded welcome/help text
- host-loop tools for live data access depending on Seedance configuration: `fetch_live_calendar`, `get_live_article`, `get_live_markets`, `get_live_news`, `get_live_indicators`, `get_live_rates`, `get_live_rate_expectations`, `web_search`, `web_fetch`, `sync_portfolio_from_broker`, `generate_image`, optional `generate_live_photo`, plus regime/calendar/briefing tools
- Claude Code native-agent mode can additionally use built-in web tools plus shared analyst MCP tools when `ANALYST_CLAUDE_CODE_USE_NATIVE_AGENT=1`
- chat runtime (`runtime/chat.py`): standalone execution layer with `build_user_chat_tools()` factory, client profile management, conversation history, capability overlays, turn-execution planning, and media extraction from tool results
- conversation service (`runtime/conversation_service.py`): shared one-turn lifecycle so CLI and Telegram both route through the same runtime contract
- environment adapters (`runtime/environment_adapter.py`): `ConversationInput` / `ProactiveConversationInput` contracts for transport normalization
- Telegram platform policy (`runtime/platform/telegram.py`): Telegram-specific turn preparation, reminder/check-in policy, and persistence helpers
- capability registry (`runtime/capabilities.py`): declarative companion/user-chat/content-runtime capability matrix consumed by `runtime/chat.py` and `engine/sub_agent_specs.py`
- compatibility facade (`delivery/user_chat.py`): legacy import path retained while delivery and CLI call the runtime layer directly
- per-user conversation history (12 recent messages retrieved for continuity)
- command handlers: `/start`, `/help`, `/regime`, `/calendar`, `/premarket`
- free-text messages routed through agent with full tool access
- group chat support: bot detects group chats, observes silently, responds only when @mentioned with group-specific persona addendum
- Telegram-safe 4096-character truncation that preserves disclaimer suffix
- structured sales memory for Telegram:
  - `client_profiles` — 14 dimensions extracted and accumulated
  - `conversation_threads` / `conversation_messages` — all messages recorded
  - `delivery_queue`
  - `record_user_interaction()` called after every bot reply for persistence
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
- `docs/workstreams/WS1_Macro_Engine.md`
- `docs/workstreams/WS2_Delivery_Shell.md`
- `docs/workstreams/WS4_Integration.md`

For reference only:

- `code-toolkit/`
- sibling `information/` repo
- sibling `agent_maxwell/` repo

---

## How To Run

From `analyst-project/`:

```bash
# Build the sandbox Docker image (required for run_python_analysis tool)
docker build -t analyst-python-sandbox src/analyst/sandbox/docker/

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
