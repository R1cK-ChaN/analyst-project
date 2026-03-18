# Chatbot Feature Inventory

This document catalogues all features the chatbot system supports, split into **core agent capabilities** (platform-agnostic) and **Telegram-specific features**. Use this as a reference when expanding to other platforms — the core layer can be reused as-is; the platform layer needs a new adapter.

---

## Core Agent Capabilities

These work regardless of messaging platform. They live outside `delivery/` and depend only on the engine, runtime, memory, tools, and analysis packages.

### Persona & Identity

- **Character**: 陈襄 (Chen Xiang / Shawn Chan) — SnT veteran, warm and grounded
- **Persona modes**: COMPANION (emotional support, daily chat) and SALES (content/research)
- **Modular prompt system**: 20+ prompt modules assembled per turn based on context (mode, language, group/private, relationship stage, proactive vs reactive)
- **Language matching**: Responds in user's language (Chinese, English, or mixed); auto-detected per turn
- **Identity immunization**: Resists prompt injection attempts to change persona

### Agent Loop & LLM

- **6-turn tool-use loop**: Agent can call up to 6 tools per conversation turn before generating final response
- **Backend**: OpenRouter (default: `google/gemini-3.1-flash-lite-preview`), configurable
- **Sub-agent delegation**: Companion agent can spawn a Research sub-agent (4-turn loop) for deep investigation
- **Interaction modes**: QA, DRAFT, FOLLOW_UP, MEETING_PREP, REGIME, CALENDAR, PREMARKET — auto-detected from user message patterns

### Memory (Three-Layer System)

| Layer | Scope | Contents |
|-------|-------|----------|
| **Conversation history** | Per thread | Last 20 turns of user ↔ assistant messages |
| **Client profile** | Per user | 20+ dimensions: language, timezone, mood, stress, confidence, personal facts, response style, risk appetite, investment horizon, expertise level |
| **Relationship state** | Per user | Intimacy score, stage, tendencies, nicknames, mood history, streak |

- **Profile extraction**: LLM outputs `<profile_update>` tags; parsed and merged after each turn
- **Personal facts**: Extracted from conversation (birthday, family, job, hobbies, etc.)
- **Memory context builder**: Assembles relevant memory into system prompt per turn

### Relationship & Emotional Tracking

- **Intimacy score** (0.0–1.0): Increases with interaction, decays 0.01/day after 1-day grace
- **Stages**: stranger → acquaintance (0.15) → familiar (0.40) → close (0.70)
  - 48-hour cooldown between stage transitions to prevent oscillation
- **Tendency distribution**: confidant / friend / mentor / romantic — nudged by mood and interaction timing
- **Streak tracking**: Consecutive days interacted
- **Mood history**: Last 10 moods with valence scoring; emotional trend computed (improving / declining / stable)
- **Nicknames**: Bidirectional (user→AI, AI→user); extracted from conversation and stored

### Proactive Outreach Logic

The decision logic for when and why to reach out is platform-agnostic:

- **Outreach kinds**: routine check-in, lifestyle ping, emotional follow-up, inactivity reactivation, same-day retry
- **Evaluation**: Based on last interaction time, mood trend, streak, intimacy stage
- **Deduplication**: Semantic similarity check against last 7 days of outreach messages
- **Cooldowns**: Per-kind minimum intervals to prevent over-messaging

### Reminders & Scheduling

- **User reminders**: LLM extracts reminder intent → stored with due_at timestamp → delivered at the right time
- **Companion schedule**: Daily plan slots (morning, lunch, afternoon, dinner, evening) — AI maintains its own "routine" for narrative consistency
- **Routine state machine**: wake → active → dinner → leisure → sleep

### Tools (26 total)

#### Research & Data
| Tool | Description |
|------|-------------|
| `web_search` | Internet search via OpenRouter |
| `web_fetch` | Fetch and extract content from URLs |
| `live_news` | Recent news from macro-data-service |
| `live_markets` | Real-time market data |
| `live_calendar` | Upcoming economic events |
| `country_indicators` | Macro indicators by country |
| `reference_rates` | Central bank rates |
| `rate_expectations` | Market-implied rate expectations |
| `article` | Fetch and parse a specific article |
| `research_agent` | Delegate to 4-turn research sub-agent |

#### Portfolio
| Tool | Description |
|------|-------------|
| `portfolio_risk` | Portfolio risk metrics and analysis |
| `portfolio_holdings` | Current position data |
| `portfolio_sync` | Sync from brokers (IBKR, Tiger, Longbridge) |
| `vix_regime` | VIX-based market regime scoring |

#### Stored Data
| Tool | Description |
|------|-------------|
| `stored_news` | Search archived news in SQLite |
| `stored_research` | Search stored research notes |
| `indicator_history` | Historical indicator time series |
| `fed_comms` | Fed communications archive |
| `rag_search` | Vector search over documents (Milvus + BM25) |

#### Computation
| Tool | Description |
|------|-------------|
| `python_analysis` | Execute Python code in Docker sandbox |
| `analysis_operator` | Run typed analysis operators (13 operators) |
| `artifact_lookup` / `artifact_store` | Cache and retrieve analysis results |

#### Content Generation
| Tool | Description |
|------|-------------|
| `generate_image` | AI image generation (Volcengine/Doubao) |
| `generate_live_photo` | Short animated selfie-style videos |

### Analysis Operators (13)

Typed algebra with input/output validation (Series / Dataset / Metric / Signal):

- **Fetch**: `fetch_series`, `fetch_dataset`
- **Transform**: `resample`, `rolling`, `pct_change`, `threshold`
- **Relation**: `difference`, `correlation`, `align`, `combine`
- **Signal**: `trend`, `regression`, `compare`

Artifacts are SHA-256 identified and cached in SQLite with TTL per operator type.

### Sandbox Execution

- **Policy validation**: AST-based — blocks file I/O, subprocess, network, imports of dangerous modules
- **Docker runner**: Resource-limited container execution
- **Output**: status, result, stdout, error, timed_out

### Injection Detection

- Pattern-based scanner detects prompt injection in user input
- When triggered: masks `generate_image` and `research_agent` tools to limit attack surface

---

## Telegram Platform Features

These are specific to the Telegram delivery layer (`src/analyst/delivery/`). A new platform (e.g., WeChat, Discord, WhatsApp) would need equivalent implementations.

### Message Handling

- **Inbound types**: Text, photos, image-as-document, documents (PDF, TXT, CSV, JSON, MD, PY, DOCX, XLSX)
- **Document extraction**: Downloads file → extracts text (pymupdf for PDF, python-docx for Word, openpyxl for Excel, UTF-8 decode for text) → injects into LLM prompt
- **Document limits**: Max 10 MB file size, max 8,000 chars extracted text (truncated with marker)
- **Image processing**: Downloads photo → normalizes (EXIF rotation, RGB conversion, resize to 1536px max edge) → base64 data URI → multimodal LLM input
- **Caption handling**: Telegram photos/documents can have captions instead of text; both are extracted
- **Message filter**: `TEXT | PHOTO | Document.ALL` minus commands

### Message Formatting & Sending

- **Bubble splitting**: Long responses auto-split at 4,096 chars (Telegram's limit) or at `[SPLIT]` markers
- **Markdown**: Uses Telegram's basic Markdown (not MarkdownV2)
- **Multi-bubble delivery**: Sequential sends with typing indicator between bubbles
- **Media sending**: `reply_photo` for images, `reply_video` for live photos, `reply_text` for text
- **Generated media cleanup**: Temp files (prefixed `analyst_gen_`) auto-deleted after sending

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Persona greeting — introduces 陈襄 |
| `/help` | Explains bot capabilities |
| `/checkins_on` | Enable proactive check-ins for this chat |
| `/checkins_off` | Disable proactive check-ins |

### Group Chat

- **Trigger detection**:
  - Direct @mention of bot username
  - Reply to bot's own message
  - Autonomous intervention (see below)
- **@Mention resolution**: `TEXT_MENTION` entities → user_id; `MENTION` entities → @username → looked up in group members table
- **Group member tracking**: Stores user_id, display_name, telegram username per group; auto-updated on each message
- **Group relational roles**: Detects role declarations ("我是妈妈", "I am the boss") and stores per-member relationship tags
- **Group message buffer**: Last 50 messages / 1,500 chars rendered as context for the LLM
- **Group message persistence**: All messages stored in `group_messages` table

#### Autonomous Intervention

The bot can jump into group conversations without being mentioned:

| Trigger | Score | Description |
|---------|-------|-------------|
| Name mention | 0.70 | Someone mentions "陈襄" / "Shawn" by name |
| Interest match | 0.40 | Keywords matching bot's expertise (markets, macro) |
| Unanswered question | 0.60 | A question sits without reply |
| Emotional distress | 0.80 | Emotional cue tokens detected |

- **Suppression**: Recent intervention penalty, humor/support/tension markers reduce score
- **Threshold**: Score ≥ 0.60 to intervene
- **Delay**: 30–180 seconds (randomized per trigger type)
- **Daily cap**: Max 3 interest-triggered interventions per day
- **Style**: Ultra-brief (1 sentence), like overhearing a conversation

### Proactive Outreach Delivery

The core logic decides *what* and *when*; Telegram handles *how*:

- **Check-in job**: Runs every 5 minutes, evaluates all active companions
- **Send windows** (by relationship stage):
  - stranger: blocked
  - acquaintance: 09:00–21:00
  - familiar: 08:00–23:00
  - close: 08:00–23:30 (extended to 01:00 if romantic tendency + late-night activity >50%)
- **Typing simulation**: Sends `ChatAction.TYPING` before responses
- **First-reply delay**: Randomized human-like delay (2–12s instant, 15–45s normal, 2–4min deep stories, 5–15s emotional)
- **"Seen, no rush" pattern**: ~80% chance of 3–8s delay, ~20% chance of 60–180s delay

### Image Decision Layer

Controls when the bot sends generated images (Telegram-specific rate limiting):

- Max 1–2 generated images per day (varies by relationship stage)
- Separate lower limit for proactive images
- 5-day rolling warmup count
- Suppressed during high stress or late night (unless romantic + high late-night activity)

### Inbound Image Handling

- **Direct photo**: Telegram `PhotoSize` → largest resolution selected
- **Image-as-document**: `Document` with `image/*` MIME type → same processing as photo
- **Reply-to image**: User replies to a message containing a photo → image extracted with `source="reply"`
- **Multimodal prompt**: Text instruction + base64 image → sent as structured content list to LLM

---

## Platform Expansion Checklist

When adding a new platform, implement these adapter components:

| Component | What to build | Reference |
|-----------|---------------|-----------|
| **Message receiver** | Webhook/polling that extracts text, images, documents from platform messages | `bot.py:handle_message` |
| **Message sender** | Send text (with platform char limit splitting), images, videos | `bot.py:_send_bot_bubbles` |
| **Document extractor** | Download files from platform API, call shared `_extract_text_from_bytes` | `bot_media.py` |
| **Image extractor** | Download images, call shared `_encode_image_data_uri` | `bot_media.py` |
| **Group adapter** | Member tracking, mention detection, intervention triggers | `group_intervention.py` |
| **Command router** | Platform-specific command syntax (slash commands, keywords, etc.) | `bot.py:CommandHandler` |
| **Outreach sender** | Platform API calls for proactive messages; send window enforcement | `bot.py:_send_companion_proactive_message` |
| **Formatter** | Platform-specific markdown/rich text formatting | `user_chat.py:split_into_bubbles` |
| **Typing indicator** | Platform's "typing..." signal | `ChatAction.TYPING` |
| **History adapter** | Map platform thread/channel IDs to conversation threading model | `bot_history.py` |

The core layer (`engine/`, `runtime/`, `memory/`, `tools/`, `analysis/`, `sandbox/`) requires **zero changes** for a new platform.
