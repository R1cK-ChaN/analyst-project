# Analyst — Complete Project Package

Standalone Analyst product scaffold. This folder now contains its own installable Python package under `src/analyst/` and can run without importing from the sibling `information/` repo.

Current status on March 15, 2026:

- the live WS1 engine is implemented under `src/analyst/engine/` with a dedicated macro-data client boundary under `src/analyst/macro_data/`
- the service-side macro-data stack has been extracted into a standalone sibling codebase at `/home/rick/Desktop/analyst/macro-data-service`
- local live commands now cover refresh, flash commentary, briefing, wrap, regime refresh, calendar inspection, and news inspection
- the implemented source set is FRED, Fed RSS, Investing.com, ForexFactory, TradingEconomics, yfinance, and macro-finance RSS news ingestion
- the news layer now includes article fetch/extraction, structured metadata, SQLite persistence, FTS-backed search, and time-decay ranking
- the memory layer records all chat messages and extracts 17 client profile dimensions that accumulate across conversations, including emotional trend tracking, stress level monitoring, and personal facts memory (up to 20 facts with recency-refresh dedup)
- a unified tools layer (`src/analyst/tools/`) provides `ToolKit` composable builder and 14 tool builders (6 live data scrapers + web search + web fetch + live calendar + article fetch + portfolio sync + image generation + optional live-photo generation + sandboxed Python analysis); all tools route live data operations through the `MacroDataClient` boundary, and a shared MCP bridge exposes a safe read-only subset to Claude Code native turns
- the `ingestion/` package has been fully removed from `analyst-project` — all scraper and data-fetching code now lives exclusively in the standalone `macro-data-service` repo; tools and storage have zero ingestion imports; utility functions (`normalize_indicator_name`, `canonicalize_url`, `content_hash`) were extracted to `src/analyst/utils.py`
- a Docker-based sandbox module (`src/analyst/sandbox/`) provides isolated Python code execution for agent-driven data analysis; code is AST-validated against a security policy, then executed in an ephemeral container with `--network none`, `--read-only`, and resource limits; the `run_python_analysis` tool is available to the research agent, user chat, and data_deep_dive / research_lookup sub-agents
- the execution layer is now split between product-owned host-loop orchestration and provider-native execution: OpenRouter/Anthropic models run through the Python tool-calling loop, while Claude Code can run as a native agent and still access selected analyst tools via the local MCP bridge; the layered conversation stack now lives under `src/analyst/runtime/` (`chat.py`, `conversation_service.py`, `environment_adapter.py`, `platform/telegram.py`, and `capabilities.py`), backend imports are fronted through `src/analyst/engine/backends/`, and `src/analyst/delivery/user_chat.py` remains as a compatibility facade for legacy callers
- a round sub-agent layer is implemented for research, sales, and runtime-assisted content generation, with scoped memory, recursion prevention, and SQLite audit logging of each run
- the portfolio package supports CSV import and live broker sync via an extensible adapter layer (IBKR, Longbridge 长桥, Tiger 老虎), with EWMA risk pipeline, VIX regime signals, and agent-actionable tools
- the Telegram bot is deployed to a Contabo VPS with group chat support (observe silently, reply on @mention), full tool access, time-of-day awareness, absence awareness, typing simulation between multi-bubble messages, inbound user-image understanding, static image generation via Volcengine Seedream with photo delivery and AI watermark disabled by default, optional motion-selfie/live-photo generation via Seedance with Telegram video delivery, and an env-gated Claude Code native-agent path that can use built-in web tools plus shared analyst MCP tools
- the standalone HTTP communication path between `analyst-project` and `macro-data-service` is covered by an end-to-end integration test
- the oversized production modules in storage, delivery, and ingestion have been reconstructed into feature-specific modules behind compatibility facades, so external imports and entrypoints remain stable while the implementation is split by responsibility
- targeted regression coverage for the refactor passed locally (`221 passed` across OECD, gov reports, Telegram, memory, companion check-ins, and news ingestion), the architecture follow-up suites for the layered runtime and capability registry passed locally (environment adapter, conversation service, Telegram platform policy, and declarative capability registry), and the live scraper integration suite in `tests/test_scrapers.py -m live -v` passed against real endpoints on March 13, 2026
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
├── tests/                          ← LOCAL VALIDATION
│   ├── test_broker_ibkr.py         Broker adapter layer: IBKR, Longbridge, Tiger position mapping + session + factory
│   ├── test_sandbox.py             Sandbox policy, container runner, manager, and tool tests (36 tests, all mocked)
│   ├── test_product_layer.py       End-to-end contract and routing smoke tests
│   ├── test_telegram.py            Telegram formatter, bot wiring, and transport regression tests
│   └── test_ws1_engine.py          WS1 live engine + calendar: store, env, CLI, regime parsing
│
├── src/analyst/                    ← LIVE IMPLEMENTATION
│   ├── app.py                      App factory and top-level product wiring
│   ├── cli.py                      Local CLI entrypoint
│   ├── contracts.py                Shared product contracts
│   ├── env.py                      Multi-file .env resolver
│   ├── macro_data/                 Macro-data client boundary + local compatibility service
│   ├── information/                Local information layer using bundled demo data
│   ├── runtime/                    Runtime and prompt profiles, including chat orchestration, environment adapters, platform policy, and capability registry
│   ├── tools/                      14 agent tools — ToolKit builder + live data scrapers + web search/fetch + calendar + portfolio sync + image gen + live photo + sandboxed Python analysis
│   ├── sandbox/                    Docker-based sandboxed Python execution (policy, container runner, manager, Dockerfile)
│   ├── mcp/                        Local MCP bridge exposing selected analyst-owned tools to Claude Code
│   ├── engine/                     Engine service boundary + live engine + executor layer + host loop + provider adapters, with backend namespace in `engine/backends/`
│   ├── storage/                    Transitional local SQLite store and agent-owned memory/trader state
│   ├── memory/                     Client profile extraction (17 dimensions), emotional memory, personal facts, context builders
│   ├── utils.py                    Text/URL utility functions extracted from former ingestion layer
│   ├── delivery/                   Telegram bot (陈襄) with group chat, time awareness, typing simulation, image gen + photo/video delivery + formatters, plus `delivery/user_chat.py` compatibility facade
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

Full test suite (450 tests, scraper tests moved to macro-data-service):

```bash
python3 -m pytest tests/ -q --ignore=tests/test_calendar_normalization.py --ignore=tests/test_document_storage.py
```

Quick local usage:

```bash
# Standalone macro-data service (preferred decoupled path)
cd /home/rick/Desktop/analyst/macro-data-service
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
macro-data-service serve --host 127.0.0.1 --port 8765

# In another shell, point analyst-project at the service
export ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765
export ANALYST_MACRO_DATA_API_TOKEN=

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
- extracted service communication: standalone `macro-data-service` HTTP API verified against the agent via `tests/test_macro_data_integration.py`
- sub-agent execution: scoped tag extraction uses word-boundary matching, memory retrieval respects punctuation boundaries, and both success and error runs are audited with preserved scope tags
- unified tools layer: ToolKit composable builder + 14 tools (6 live data scrapers + web search + web fetch + live calendar + article fetch + portfolio sync + Volcengine image generation + Seedance motion/live-photo generation + sandboxed Python analysis) plus a local MCP bridge for sharing selected read-only analyst tools with Claude Code
- Docker-based sandbox: AST policy validation + ephemeral container execution (--network none, --read-only, resource-limited) for agent-driven Python data analysis
- portfolio risk pipeline: CSV import, broker sync (IBKR/Longbridge/Tiger), EWMA covariance, VIX regime signals, agent-actionable tools
- WeCom and Telegram formatters
- Telegram agent bot with persona (陈襄), group chat support, 13 host-loop tools, inbound image reading from user photos/image documents, Seedream image generation with AI watermark disabled by default and photo delivery, Seedance motion-selfie delivery as Telegram video, and Claude Code native-agent support behind `ANALYST_CLAUDE_CODE_USE_NATIVE_AGENT=1`
- user chat runtime with client profile tracking and conversation recording, now layered across `src/analyst/runtime/chat.py`, `conversation_service.py`, `environment_adapter.py`, `platform/telegram.py`, and `capabilities.py`, with a legacy `delivery/user_chat.py` facade
- integration router

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
