# Analyst — Complete Project Package

Standalone Analyst product scaffold. This folder now contains its own installable Python package under `src/analyst/` and can run without importing from the sibling `information/` repo.

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
├── ws1-engine/                     ← ENGINEERING: The macro brain
│   └── WS1_Macro_Engine.md         Data pipeline, agent specs, LLM prompts, regime state design
│
├── ws2-delivery/                   ← ENGINEERING: The delivery channels
│   └── WS2_Delivery_Shell.md       WeCom bot, 公众号, Mini Program, interaction modes, compliance
│
├── ws3-discovery/                  ← MARKETING: Customer research
│   └── WS3_Customer_Discovery.md   Interview scripts, competitive scan template, network audit
│
├── ws4-integration/                ← ENGINEERING: Connect engine to delivery
│   └── WS4_Integration.md          API contracts, message routing, auto-publish, error handling
│
├── ws5-gtm/                        ← MARKETING + FOUNDER: Go-to-market
│   └── WS5_Go_To_Market.md         Seed users, pilot conversion, pricing, content strategy
│
├── analyst-shared/                 ← LEGACY DESIGN NOTE
│   └── README.md                   Historical split-package note; live code moved into `src/analyst/`
│
├── analyst-runtime/                ← LEGACY DESIGN NOTE
│   └── README.md                   Historical split-package note; live code moved into `src/analyst/runtime/`
│
├── analyst-information/            ← LEGACY DESIGN NOTE
│   └── README.md                   Historical split-package note; live code moved into `src/analyst/information/`
│
├── analyst-engine/                 ← LEGACY DESIGN NOTE
│   └── README.md                   Historical split-package note; live code moved into `src/analyst/engine/`
│
├── analyst-delivery/               ← LEGACY DESIGN NOTE
│   └── README.md                   Historical split-package note; live code moved into `src/analyst/delivery/`
│
├── analyst-integration/            ← LEGACY DESIGN NOTE
│   └── README.md                   Historical split-package note; live code moved into `src/analyst/integration/`
│
├── tests/                          ← LOCAL VALIDATION
│   ├── test_product_layer.py       End-to-end contract and routing smoke tests
│   ├── test_telegram.py            Telegram formatter, bot wiring, and transport regression tests
│   └── test_ws1_engine.py          WS1 live engine: store, agent loop, env, CLI, regime parsing
│
├── src/analyst/                    ← LIVE IMPLEMENTATION
│   ├── app.py                      App factory and top-level product wiring
│   ├── cli.py                      Local CLI entrypoint
│   ├── contracts.py                Shared product contracts
│   ├── env.py                      Multi-file .env resolver
│   ├── information/                Local information layer using bundled demo data
│   ├── runtime/                    Runtime and prompt profiles
│   ├── engine/                     Engine service boundary + live engine + agent loop + OpenRouter
│   ├── storage/                    SQLite store (calendar, prices, comms, indicators, regime, notes)
│   ├── ingestion/                  Source adapters (Investing.com, ForexFactory, FRED, Fed RSS, yfinance)
│   ├── delivery/                   WeCom/Telegram formatting and Telegram bot shell
│   └── integration/                Message routing
│
├── data/demo/                      ← LOCAL DEMO DATA
│   ├── events.json                 Sample macro events
│   ├── calendar.json               Sample upcoming releases
│   ├── documents.json              Sample research snippets
│   └── market_prices.json          Sample market snapshot
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

Quick local usage:

```bash
# Demo commands (no API keys needed)
PYTHONPATH=src python3 -m analyst regime
PYTHONPATH=src python3 -m analyst route "帮我写一段关于今晚非农数据的客户消息"

# WS1 live engine commands (requires .env with API keys — see .env.example)
PYTHONPATH=src python3 -m analyst refresh --once
PYTHONPATH=src python3 -m analyst flash --indicator cpi
PYTHONPATH=src python3 -m analyst briefing
PYTHONPATH=src python3 -m analyst wrap
PYTHONPATH=src python3 -m analyst regime-refresh

# Telegram bot
ANALYST_TELEGRAM_TOKEN=your-token PYTHONPATH=src python3 -m analyst.delivery.bot
```

This validates the current standalone implementation:

- bundled demo data + demo engine path
- WS1 live engine: SQLite store, ingestion adapters, agent loop, OpenRouter provider
- WeCom and Telegram formatters
- Telegram polling bot shell
- integration router

## Source Of Truth

Current implementation status:

- `00-overview/Implementation_Status.md`

Live code:

- `src/analyst/`

Target-state planning:

- `00-overview/Workstream_Plan.md`
- `ws1-engine/`
- `ws2-delivery/`
- `ws4-integration/`
