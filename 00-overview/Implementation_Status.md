# Analyst — Implementation Status

**Status date:** March 7, 2026

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

- macro Q&A response path
- draft-generation path
- meeting-prep path
- regime-summary note generation
- pre-market briefing generation

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

---

## Not Implemented Yet

### Real data ingestion

Not yet implemented inside `analyst-project/`:

- live macro data fetchers
- live government-report crawling
- live news ingestion
- live document parsing
- scheduled refresh jobs

### Real agent backend

Not yet implemented:

- integration with a real LLM backend
- tool-calling loop
- memory store
- user personalization
- prompt/version management beyond local code

### Product storage

Not yet implemented:

- research store
- market state store
- interaction log store
- user context store
- persistent output history

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

Status: partially implemented

Done:

- engine contract layer exists
- regime summary path exists
- pre-market briefing path exists
- Q&A, draft, and meeting-prep generation paths exist

Missing:

- live ingestion
- scheduling
- evaluation harness
- factual grounding beyond bundled demo data

### WS2 Delivery Shell

Status: partially implemented

Done:

- WeCom and Telegram reply formatting
- disclaimers
- channel-oriented message objects
- Telegram bot transport for interactive polling-based delivery
- command handlers for `/start`, `/help`, `/regime`, `/calendar`, and `/premarket`

Missing:

- real WeCom integration
- push scheduling
- account/app setup
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
PYTHONPATH=src python3 -m analyst regime
PYTHONPATH=src python3 -m analyst route "帮我写一段关于今晚非农数据的客户消息"
ANALYST_TELEGRAM_TOKEN=your-token PYTHONPATH=src python3 -m analyst.delivery.bot
python3 -m unittest discover -s tests -v
```

---

## Immediate Next Implementation Targets

1. Replace `data/demo/` with a local Analyst-owned ingestion/store layer.
2. Add persistent research and interaction storage inside `analyst-project/`.
3. Add a real runtime adapter behind the current deterministic runtime interface.
4. Add a production-grade WeCom delivery transport layer and push scheduler.
