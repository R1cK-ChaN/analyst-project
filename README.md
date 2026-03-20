# Analyst — Complete Project Package

Standalone Analyst product scaffold. This folder now contains its own installable Python package under `src/analyst/` and can run without importing from the sibling `information/` repo.

Current status on March 20, 2026:

### Engine & Data
- the live WS1 engine is implemented under `src/analyst/engine/` with a dedicated macro-data client boundary under `src/analyst/macro_data/`
- the service-side macro-data stack has been extracted into a standalone sibling codebase at `/home/rick/Desktop/analyst/macro-data-service`
- local live commands cover refresh, flash commentary, briefing, wrap, regime refresh, calendar inspection, and news inspection
- the implemented source set is FRED, Fed RSS, Investing.com, ForexFactory, TradingEconomics, yfinance, and macro-finance RSS news ingestion
- the news layer includes article fetch/extraction, structured metadata, SQLite persistence, FTS-backed search, and time-decay ranking

### Memory & Relationship
- three-layer memory: the memory layer records all chat messages and extracts 17 client profile dimensions that accumulate across conversations, including emotional trend tracking, stress level monitoring, and personal facts memory (up to 20 facts with recency-refresh dedup)
- companion relationship state (`RelationshipState`): intimacy scoring, stage transitions (stranger → acquaintance → familiar → close → intimate) with 48h cooldown, tendency distribution (platonic/romantic/playful/supportive), streak tracking, and mood history (last 10 moods with emotional trend)
- structured nickname storage (`NicknameEntry`): extracted from personal_facts, supports English patterns and direct user text detection
- narrative rendering: `_render_companion_profile` outputs Chinese behavioral instructions based on relationship stage and tendencies
- tendency spike damping with retroactive correction to prevent single-message swings

### Tools & Analysis
- a unified tools layer (`src/analyst/tools/`) provides `ToolKit` composable builder and 17 tool builders (6 live data scrapers + web search + web fetch + live calendar + article fetch + portfolio sync + image generation + optional live-photo generation + sandboxed Python analysis + analysis operators + artifact cache lookup + artifact cache store); all tools route live data operations through the `MacroDataClient` boundary, and a shared MCP bridge exposes a safe read-only subset to Claude Code native turns
- an analysis operator algebra (`src/analyst/analysis/operators/`) provides 13 deterministic compute operators with typed I/O (Series/Dataset/Metric/Signal); operators run in host process via numpy, auto-cache results as artifacts, and are accessible through the unified `run_analysis` tool
- an artifact cache (`src/analyst/analysis/`) provides deterministic identity (SHA-256), SQLite-backed storage with TTL
- a Docker-based sandbox module (`src/analyst/sandbox/`) provides isolated Python code execution for agent-driven data analysis with AST policy validation and ephemeral containers

### Companion Agent Architecture
- the companion agent is fully self-contained with 3 tools: `generate_image`, `generate_live_photo` (optional), and `web_search`
- `web_search` uses OpenRouter's `:online` model (default `anthropic/claude-sonnet-4:online`) via plugins API — the model decides when to search for factual queries (stock prices, weather, news)
- single-pass LLM execution with full tool access on every turn — no rule-based gating
- social awareness: user disengagement detection (short/ack replies), self-focus drift detection, question taxonomy (emotional probes vs topic invitations vs life-care), reciprocity enforcement
- stage-as-interaction-freedom: `RelationshipStagePolicy` with per-stage constraints (teasing, disclosure, comfort, disagreement ceiling), per-stage example prompt modules, tendency modifiers, ceiling mechanism clamping engagement policy
- user timezone support: reads `timezone_name` from user profile, shows both bot time (Singapore) and user local time
- text quality: sentence completeness scoring (penalizes formal connectors, compound clauses, comma-dense messages), tool artifact sanitization (strips hallucinated XML/JSON tool blocks)

### Runtime & Execution
- the execution layer is split between product-owned host-loop orchestration and provider-native execution: OpenRouter/Anthropic models run through the Python tool-calling loop, while Claude Code can run as a native agent via the local MCP bridge
- the layered conversation stack lives under `src/analyst/runtime/` (`chat.py`, `conversation_service.py`, `environment_adapter.py`, `platform/telegram.py`, and `capabilities.py`)
- a sub-agent layer is implemented for sales and runtime-assisted content generation, with scoped memory, recursion prevention, and SQLite audit logging; the research agent has been decoupled to a standalone HTTP service (see Research Service Split)
- the portfolio package supports CSV import and live broker sync via an extensible adapter layer (IBKR, Longbridge 长桥, Tiger 老虎), with EWMA risk pipeline, VIX regime signals, and agent-actionable tools

### Delivery (Telegram Bot — 陈襄/Shawn Chan)
- deployed to a Contabo VPS with two persona modes: SALES and COMPANION
- LLM: OpenRouter (default google/gemini-3-flash-preview), 6-turn agent loop
- **private chat**: full tool access (image gen + web search), time-of-day awareness, user timezone awareness, absence awareness, typing simulation between multi-bubble messages, inbound user-image understanding
- **group chat**: observe silently, reply on @mention/reply, plus autonomous intervention system — score-based trigger engine (name mention 0.7, interest match 0.4, unanswered question 0.4, emotional gap 0.4) with 6 suppression penalties (bot recency, message rate, private conversation detection, tension markers, send window), 0.6 threshold, 30–180s delayed send with re-evaluation before delivery
- **image generation**: static images via Volcengine Seedream with AI watermark disabled, optional motion-selfie/live-photo via Seedance with Telegram video delivery, image decision layer controlling when to proactively attach images
- **proactive outreach**: relationship-aware check-ins (follow_up, inactivity, morning/evening/weekend routine pings), outreach response rate tracking with pause/throttle, cold outreach strategy, outreach dedup, and relationship-aware send windows based on intimacy stage and late-night activity patterns
- **safety**: injection defense scanner, prompt immunization module
- env-gated Claude Code native-agent path behind `ANALYST_CLAUDE_CODE_USE_NATIVE_AGENT=1`

### Infrastructure
- the `ingestion/` package has been fully removed — all scraper code lives in `macro-data-service`; utility functions extracted to `src/analyst/utils.py`
- the companion agent is self-contained — no external research-service dependency; `src/analyst/research/` contains unused delegate code preserved for reference
- the standalone HTTP communication path to `macro-data-service` is covered by integration tests
- oversized production modules reconstructed into feature-specific modules behind compatibility facades

### Test Coverage
- 1429 tests passing (`python3 -m pytest tests/ -q --ignore=tests/test_calendar_normalization.py`)
- key test suites: relationship state (85 tests), group intervention (56 tests), analysis operators (54 tests), sandbox (36 tests), artifact cache (24 tests), memory (90+ tests), Telegram bot wiring, companion check-ins, proactive outreach, image decision, injection defense
- research-service has its own 26 tests at `/home/rick/Desktop/analyst/research-service/tests/`

### Pending
- China-specific ingestion, live end-to-end provider verification, and WeCom delivery are still pending

## What's Inside

```
analyst-project/
│
├── 00-overview/                    ← START HERE
│   ├── Product_Vision.md           Product definition, positioning, pricing, competitive landscape
│   ├── Workstream_Plan.md          How all 5 workstreams connect, timeline, decision points
│   ├── Implementation_Status.md    What is implemented now, what is still missing, and which paths are live
│   └── Current_System_Migration_Plan.md
│                                   Plan for evolving current agent/information code into Analyst product modules
│
├── tests/                          ← LOCAL VALIDATION (1429 tests)
│   ├── test_relationship_state.py  Relationship state, intimacy, stage transitions, tendencies, nicknames (85 tests)
│   ├── test_group_intervention.py  Autonomous group intervention triggers, penalties, re-evaluation (56 tests)
│   ├── test_analysis_operators.py  13 operators, type system, registry, composability validation (54 tests)
│   ├── test_sandbox.py             Sandbox policy, container runner, manager, and tool tests (36 tests)
│   ├── test_artifact_cache.py      Artifact identity, SQLite storage, TTL, lookup/store tools (24 tests)
│   ├── test_memory.py              Memory layer, profile extraction, group chat context, emotional tracking
│   ├── test_telegram.py            Telegram formatter, bot wiring, transport, companion timing
│   ├── test_broker_ibkr.py         Broker adapter layer: IBKR, Longbridge, Tiger
│   ├── test_product_layer.py       End-to-end contract and routing smoke tests
│   └── test_ws1_engine.py          WS1 live engine + calendar: store, env, CLI, regime parsing
│
├── src/analyst/                    ← LIVE IMPLEMENTATION
│   ├── app.py                      App factory and top-level product wiring
│   ├── cli.py                      Local CLI entrypoint
│   ├── contracts.py                Shared product contracts
│   ├── env.py                      Multi-file .env resolver
│   ├── research/                   Research service HTTP client + delegate tool (calls research-service)
│   ├── macro_data/                 Macro-data client boundary + local compatibility service
│   ├── information/                Local information layer using bundled demo data
│   ├── agents/                     Agent role specs (companion) with prompt builders and tool assembly
│   ├── runtime/                    Chat orchestration, conversation service, environment adapters, platform policy, capability registry
│   ├── analysis/                   Artifact cache + 13 analysis operators with typed I/O + operator registry
│   ├── tools/                      17 agent tools — ToolKit builder + live data scrapers + web search/fetch + calendar + portfolio sync + image gen + live photo + sandbox + analysis operators + artifact cache
│   ├── sandbox/                    Docker-based sandboxed Python execution (policy, container runner, manager, Dockerfile)
│   ├── mcp/                        Local MCP bridge exposing selected analyst-owned tools to Claude Code
│   ├── engine/                     Engine service boundary + live engine + executor layer + host loop + provider adapters (backends/)
│   ├── storage/                    SQLite store (WAL mode) with schema migrations, group tables, relationship state, companion scheduling
│   ├── memory/                     Three-layer memory: client profiles (17 dimensions), emotional tracking, personal facts, group chat context, relationship state
│   ├── utils.py                    Text/URL utility functions extracted from former ingestion layer
│   ├── delivery/                   Telegram bot (陈襄/Shawn Chan) with group chat + autonomous intervention, companion timing, proactive outreach, image decision, injection defense, soul prompt modules, schedule/reminder systems
│   └── integration/                Message routing
│
├── data/demo/                      ← LOCAL DEMO DATA
│   ├── events.json                 Sample macro events
│   ├── calendar.json               Sample upcoming releases
│   ├── documents.json              Sample research snippets
│   └── market_prices.json          Sample market snapshot
│
├── docs/                           ← SUPPORTING DOCS
│   ├── macro_data_service.md       Macro-data service note
│   ├── sales_agent_soul_v2.md      Sales persona design note
│   └── workstreams/                Detailed WS1-WS5 workstream specs
│       ├── WS1_Macro_Engine.md
│       ├── WS2_Delivery_Shell.md
│       ├── WS3_Customer_Discovery.md
│       ├── WS4_Integration.md
│       └── WS5_Go_To_Market.md
│
├── pyproject.toml                  ← STANDALONE PROJECT ENTRY
│
└── code-toolkit/                   ← CODE: Working scraper toolkit
    ├── README.md                   Setup instructions
    ├── requirements.txt            Python dependencies
    ├── deploy.sh                   Contabo VPS deployment script
    ├── main.py                     Orchestrator (run all scrapers)
    ├── scrapers/
    │   ├── fred_client.py          FRED API (free) — US economic data
    │   ├── investing_calendar.py   Economic calendar scraper
    │   ├── fed_scraper.py          Fed RSS communications scraper
    │   └── market_scraper.py       Cross-asset price scraper (yfinance)
    ├── storage/
    │   └── event_store.py          SQLite database layer
    └── utils/
        └── analyst_context.py      LLM context builder + system prompts

```

## Execution Order

```
WEEK 1-2 (do all three in parallel):
├── WS1: Set up data pipeline, build Analyst agent, test output quality
├── WS2: Register WeCom + 公众号, build bot skeleton with placeholders
└── WS3: Run 5 interviews + 48-hour network audit ← HIGHEST PRIORITY

WEEK 3-4:
├── WS1: Add Sales agent (Q&A + draft mode), tune Chinese language quality
├── WS2: All 5 interaction modes working, scheduled push, logging
└── WS3: Competitive deep dive, synthesize findings, identify pilot candidates

MONTH 2:
├── WS4: Connect engine to WeCom bot, connect to 公众号, connect Mini Program
├── WS1: Continue quality tuning based on real output review
└── WS2: Mini Program MVP, per-user memory, error handling

MONTH 3:
├── WS5: Seed 5-10 RMs with free access, daily feedback loop
├── WS4: Adapt product based on WS3 findings and seed user feedback
└── Decision point: continue / pivot / kill

MONTH 4-5:
├── WS5: Convert seed users to paid teams
└── All: Iterate based on real usage
```

## Key Decision Points

| When | Question | If Yes | If No |
|------|----------|--------|-------|
| Week 4 | Do we have warm intros to 3+ firms? | Continue B2B plan | Pivot to B2C first |
| Week 4 | Does compliance allow internal copilot? | Continue as planned | Reposition as pure research tool |
| Month 3 | Are 3+ of 10 seed users active daily? | Continue to paid conversion | Product doesn't fit workflow, go back to interviews |
| Month 5 | Did 2+ teams convert to paid? | Scale B2B | Pricing/value wrong, reassess |

## Local Validation

The standalone package inside `analyst-project/` can be smoke-tested with:

```bash
python3 -m unittest discover -s tests -v
```

Full test suite (1429 tests; scraper tests in macro-data-service, research agent tests in research-service):

```bash
python3 -m pytest tests/ -q --ignore=tests/test_calendar_normalization.py
```

Quick local usage:

```bash
# Standalone macro-data service (preferred decoupled path)
cd /home/rick/Desktop/analyst/macro-data-service
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
macro-data-service serve --host 127.0.0.1 --port 8765

# Standalone research service (decoupled research agent)
cd /home/rick/Desktop/analyst/research-service
OPENROUTER_API_KEY=<key> ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765 \
  python3 -m research.server --port 8766

# In another shell, point analyst-project at both services
export ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765
export ANALYST_MACRO_DATA_API_TOKEN=
export ANALYST_RESEARCH_BASE_URL=http://127.0.0.1:8766

# Demo commands (no API keys needed)
PYTHONPATH=src python3 -m analyst regime
PYTHONPATH=src python3 -m analyst route "帮我写一段关于今晚非农数据的客户消息"

# Portfolio management
PYTHONPATH=src python3 -m analyst portfolio-import data/demo/holdings.csv
PYTHONPATH=src python3 -m analyst portfolio-risk --json
PYTHONPATH=src python3 -m analyst portfolio-sync --broker ibkr --dry-run
PYTHONPATH=src python3 -m analyst portfolio-sync --broker longbridge --dry-run
PYTHONPATH=src python3 -m analyst portfolio-sync --broker tiger --dry-run

# Local sales-agent prompt testing (requires OpenRouter model env)
PYTHONPATH=src python3 -m analyst sales-chat --once "最近太难做了"
PYTHONPATH=src python3 -m analyst sales-chat --client-id demo-user --db-path /tmp/analyst-sales.db

# WS1 live engine commands (requires .env with API keys — see .env.example)
PYTHONPATH=src python3 -m analyst refresh --once
PYTHONPATH=src python3 -m analyst live-calendar --scope today
PYTHONPATH=src python3 -m analyst live-calendar --scope upcoming --country US
PYTHONPATH=src python3 -m analyst flash --indicator cpi
PYTHONPATH=src python3 -m analyst briefing
PYTHONPATH=src python3 -m analyst wrap
PYTHONPATH=src python3 -m analyst regime-refresh
PYTHONPATH=src python3 -m analyst news-refresh --category markets
PYTHONPATH=src python3 -m analyst news-latest --limit 10 --category centralbanks
PYTHONPATH=src python3 -m analyst news-search "Fed" --limit 10

# Telegram bot
ANALYST_TELEGRAM_TOKEN=your-token PYTHONPATH=src python3 -m analyst.delivery.bot
```

This validates the current standalone implementation:

- bundled demo data + demo engine path
- WS1 live engine: macro-data client boundary, calendar/news query surface, executor split (host loop vs Claude Code native path), backend namespace under `engine/backends/`, and provider adapters
- extracted service communication: standalone `macro-data-service` HTTP API + standalone `research-service` HTTP API
- sub-agent execution: scoped tag extraction, memory retrieval with punctuation boundaries, SQLite audit logging
- unified tools layer: ToolKit composable builder + 17 tools plus local MCP bridge for Claude Code
- Docker-based sandbox: AST policy validation + ephemeral container execution for agent-driven Python analysis
- analysis operator algebra: 13 deterministic operators with typed I/O, composability validation, auto-caching
- portfolio risk pipeline: CSV import, broker sync (IBKR/Longbridge/Tiger), EWMA covariance, VIX regime signals
- Telegram agent bot (陈襄/Shawn Chan) with dual persona modes, group chat + autonomous intervention, 3 companion tools (image gen + live photo + web search), proactive outreach with response rate tracking, relationship state machine, social awareness, injection defense
- companion relationship system: intimacy scoring, 4-stage progression, tendency distribution, stage-as-interaction-freedom policy, nickname extraction, emotional trend tracking, schedule consistency, reminder system
- user chat runtime layered across `runtime/chat.py`, `conversation_service.py`, `environment_adapter.py`, `platform/telegram.py`, and `capabilities.py`
- WeCom and Telegram formatters, integration router

## Source Of Truth

Current implementation status:

- `00-overview/Implementation_Status.md`
- `docs/macro_data_service.md`

Live code:

- `src/analyst/`

Target-state planning:

- `00-overview/Workstream_Plan.md`
- `docs/workstreams/WS1_Macro_Engine.md`
- `docs/workstreams/WS2_Delivery_Shell.md`
- `docs/workstreams/WS4_Integration.md`
