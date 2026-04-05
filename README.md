# Companion Agent (陈襄/Shawn Chan)

Self-contained chatbot with COMPANION (emotional support, daily chat).

## Architecture

```
analyst-project/
│
├── analyst/                       ← Python package
│   ├── cli.py                     CLI entrypoint (companion-chat, media-gen)
│   ├── contracts.py               Shared data contracts
│   ├── env.py                     Multi-file .env resolver
│   ├── utils.py                   Text/URL utility functions
│   ├── agents/                    Agent role specs (companion) with prompt builders
│   ├── delivery/                  Telegram bot, persona/soul prompt modules, timing, outreach, media, groups
│   ├── engine/                    Agent loop, executor, LLM provider adapters (OpenRouter, Claude Code)
│   ├── memory/                    Three-layer memory: profile, relationship state, topic state
│   ├── runtime/                   Chat orchestration, conversation service, capability registry
│   ├── tools/                     3 companion tools: image gen, live photo, web search
│   ├── storage/                   SQLite store (WAL mode) with feature-specific mixins
│   ├── mcp/                       MCP bridge for Claude Code native tool integration
│   ├── analysis/                  Artifact cache + 13 analysis operators (shared infra, not used by companion)
│   └── sandbox/                   Docker-based Python sandbox (shared infra, not used by companion)
│
├── tests/                         ← ~1046 tests
├── docs/                          ← Feature documentation
│   └── chatbot-features.md        Complete feature inventory
└── pyproject.toml                 ← Package config
```

## Quick Start

```bash
# Install
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

# CLI chat (requires OPENROUTER_API_KEY in .env)
analyst-cli companion-chat --once "最近太难做了"

# Image generation
analyst-cli media-gen --prompt "sunset over Hong Kong harbour"

# Telegram bot (requires ANALYST_TELEGRAM_TOKEN in .env)
analyst-telegram
```

## Companion Agent

- **3 tools**: `generate_image` (Volcengine/Doubao), `generate_live_photo` (Seedance, optional), `web_search` (OpenRouter `:online`)
- **6-turn agent loop**: Model decides when to use tools — no rule-based gating
- **LLM**: OpenRouter (default `x-ai/grok-4.1-fast`), configurable
- **Memory**: Conversation history (20 turns) + client profile (20+ dimensions) + relationship state (intimacy, stages, tendencies)
- **Social awareness**: Disengagement detection, self-focus drift, question taxonomy, reciprocity enforcement

## Related Services (in other repo)

| Service | Location | Purpose |
|---------|----------|---------|
| macro-data-service | `/home/rick/Desktop/analyst/macro-data-service` | Economic data scraping & API |
| research-service | `/home/rick/Desktop/analyst/research-service` | Research agent (decoupled) |

## Deployment

Production server: `rick@vl`, service: `analyst-telegram.service`

```bash
ssh rick@vl "cd ~/analyst-project && git pull && sudo systemctl restart analyst-telegram.service"
```

## Tests

```bash
python3 -m pytest tests/ -q
```
