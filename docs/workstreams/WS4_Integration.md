# WS4: Integration — Detailed Specification

Status note on March 6, 2026:
This document describes the target WS4 scope. For the current implemented WS4 slice, see `00-overview/Implementation_Status.md`.

## Owner: Technical Founder
## Timeline: Month 2–3
## Dependencies: WS1 (engine running) + WS2 (delivery shell with placeholders)

---

## What This Workstream Does

WS4 is the glue. It connects the engine (WS1) to the delivery channels (WS2) and adapts the product based on customer discovery findings (WS3). No new features are invented here — it's pure plumbing, routing, formatting, and error handling.

---

## Month 2: Core Connections

### Connection 1: WeCom Bot ↔ Engine

```
USER                          WECOM BOT (WS2)              ENGINE (WS1)
                              (FastAPI server)
  │                                │                           │
  │  sends message                 │                           │
  │ ──────────────────────────→    │                           │
  │                                │  parse + detect mode      │
  │                                │  ─────────────────→       │
  │                                │                    route  │
  │                                │                           │
  │                                │    ┌─ Q&A question        │
  │                                │    ├─ Draft request       │
  │                                │    ├─ Meeting prep        │
  │                                │    ├─ Regime query        │
  │                                │    └─ Calendar query      │
  │                                │                           │
  │                                │  ←──── response (Chinese) │
  │                                │                           │
  │                                │  append disclaimer        │
  │                                │  log interaction          │
  │  receives response             │                           │
  │ ←──────────────────────────    │                           │
```

**Message router implementation:**

```python
# Message routing logic — the core of WS4

import re

# Keyword patterns for mode detection
PATTERNS = {
    "draft": re.compile(r"(帮我写|帮我准备一段|起草|草拟|帮我发|写一段)"),
    "meeting_prep": re.compile(r"(准备要点|沟通要点|会议准备|客户沟通|帮我准备.*会|怎么跟客户说)"),
    "regime": re.compile(r"(宏观状态|体系状态|regime|风险偏好|现在宏观|整体怎么看)"),
    "calendar": re.compile(r"(今天有什么|日历|数据发布|今天数据|本周数据|接下来有什么)"),
}

def detect_mode(message: str) -> str:
    """Detect which interaction mode the user wants."""
    for mode, pattern in PATTERNS.items():
        if pattern.search(message):
            return mode
    return "qa"  # default: general Q&A

async def route_message(message: str, user_id: str) -> str:
    """Route message to appropriate engine function."""
    mode = detect_mode(message)
    user_ctx = await get_user_context(user_id)
    research = await engine.get_latest_research()
    market = await engine.get_market_snapshot()
    
    if mode == "draft":
        response = await engine.generate_draft(message, user_ctx)
        disclaimer = DISCLAIMERS["draft"]
    elif mode == "meeting_prep":
        response = await engine.generate_meeting_prep(message, user_ctx)
        disclaimer = DISCLAIMERS["meeting_prep"]
    elif mode == "regime":
        response = await engine.get_regime_summary()
        disclaimer = DISCLAIMERS["regime"]
    elif mode == "calendar":
        response = await engine.get_today_calendar_formatted()
        disclaimer = DISCLAIMERS["calendar"]
    else:
        response = await engine.answer_question(message, user_ctx)
        disclaimer = DISCLAIMERS["qa"]
    
    # Always append disclaimer
    final_response = f"{response}\n\n{disclaimer}"
    
    # Always log
    await log_interaction(user_id, message, final_response, mode)
    
    return final_response
```

**Latency budget:**

```
Total target: < 15 seconds (P95)

Breakdown:
├── WeCom callback received → parsed:     ~100ms
├── Mode detection + context loading:      ~200ms
├── Engine LLM call:                       ~8-12 seconds (main bottleneck)
├── Disclaimer + formatting:               ~50ms
├── WeCom API send response:               ~200ms
└── Total:                                 ~9-13 seconds

If latency exceeds 15s:
├── Send immediate acknowledgment: "正在分析中，请稍候..."
├── Process in background
└── Send final response as separate message

For regime and calendar queries (no LLM needed):
├── Serve from cache
├── Target: < 2 seconds
└── Update cache every 5 minutes
```

**Error handling:**

```python
async def safe_route_message(message: str, user_id: str) -> str:
    """Route with full error handling."""
    try:
        return await asyncio.wait_for(
            route_message(message, user_id),
            timeout=20.0
        )
    except asyncio.TimeoutError:
        return "⏳ 分析时间较长，请稍后重试。\n\n如需快速查看，可输入"宏观状态"或"今天日历"。"
    except engine.EngineUnavailableError:
        return "⚠️ 系统暂时繁忙，请稍后再试。如有紧急需求，可查看今日公众号文章。"
    except Exception as e:
        await log_error(user_id, message, str(e))
        return "⚠️ 抱歉，处理您的请求时遇到问题。请稍后重试。"
```

### Connection 2: Engine → 公众号 Auto-Publish

```
ENGINE (scheduled)              FORMATTER              WEIXIN API
     │                              │                      │
     │  7:00am: generate briefing   │                      │
     │ ────────────────────→        │                      │
     │                              │  markdown → HTML     │
     │                              │  add header image    │
     │                              │  add regime visuals  │
     │                              │  add disclaimer      │
     │                              │ ────────────────→    │
     │                              │                 publish draft
     │                              │                 (or auto-publish)
     │                              │ ←────────────────    │
     │                              │            article URL
     │                              │                      │
     │  push URL to WeCom groups    │                      │
     │ ←────────────────────        │                      │
```

**Article formatting pipeline:**

```python
async def publish_morning_briefing():
    """
    Runs at 7:00am CST. Generates, formats, and publishes.
    """
    # Step 1: Get content from engine
    briefing = await engine.get_morning_briefing()
    regime = await engine.get_regime_state()
    calendar = await engine.get_today_calendar()
    
    # Step 2: Format as WeChat article
    article = format_weixin_article(
        title=f"📊 Analyst早盘速递 | {today_date_cn()}",
        content=briefing["content_md"],
        regime=regime,
        calendar=calendar,
        disclaimer=DISCLAIMERS["push"]
    )
    
    # Step 3: Publish (choose one)
    if AUTO_PUBLISH_ENABLED:
        result = await weixin_api.create_and_publish(article)
        article_url = result["url"]
    else:
        # Push to review queue — human approves before publishing
        await notify_reviewer(article, preview_url)
        return  # human publishes manually
    
    # Step 4: Push article URL to WeCom groups
    summary = f"📊 今日早盘速递已发布\n\n{briefing['one_line_summary']}\n\n👉 点击查看完整分析"
    for webhook in WECOM_WEBHOOKS:
        await send_wecom_card(webhook, title="Analyst早盘速递", 
                              description=summary, url=article_url)
    
    # Step 5: Push to individual WeCom subscribers
    for user_id in SUBSCRIBED_USERS:
        await send_wecom_message(user_id, summary + f"\n\n{article_url}")
```

**Event-driven flash commentary pipeline:**

```python
async def on_data_release(event: dict):
    """
    Called when the calendar scraper detects a new high-importance release.
    Generates flash commentary and pushes immediately.
    """
    if event["importance"] != "high":
        return
    if not event.get("actual"):
        return  # not released yet
    
    # Step 1: Generate flash commentary
    commentary = await engine.get_flash_commentary(event)
    
    # Step 2: Push to WeCom immediately (faster than 公众号)
    wecom_message = format_flash_for_wecom(
        event=event,
        commentary=commentary["content_md"],
        disclaimer=DISCLAIMERS["push"]
    )
    
    for webhook in WECOM_WEBHOOKS:
        await send_wecom_message(webhook, wecom_message)
    
    for user_id in SUBSCRIBED_USERS:
        await send_wecom_message(user_id, wecom_message)
    
    # Step 3: Also publish as 公众号 article (can be delayed)
    if AUTO_PUBLISH_FLASH:
        article = format_weixin_article(
            title=f"⚡ {event['country']}{event['indicator']}快评",
            content=commentary["content_md"],
            disclaimer=DISCLAIMERS["push"]
        )
        await weixin_api.create_and_publish(article)
```

### Connection 3: Engine → Mini Program API

```python
# FastAPI endpoints consumed by Mini Program

@app.get("/api/regime")
async def get_regime():
    """Current regime state for dashboard."""
    regime = await engine.get_regime_state()
    return regime  # JSON directly

@app.get("/api/calendar")
async def get_calendar():
    """Today's economic calendar with Analyst views."""
    return await engine.get_today_calendar()

@app.get("/api/articles")
async def get_articles(page: int = 1, limit: int = 20, type: str = None):
    """Paginated article archive."""
    return await engine.search_archive(page=page, limit=limit, type=type)

@app.get("/api/articles/{article_id}")
async def get_article(article_id: str):
    """Single article content."""
    return await engine.get_article(article_id)

@app.get("/api/search")
async def search(q: str):
    """Full-text search across all content."""
    return await engine.search_archive(query=q)
```

---

## Month 3: Adapt Based on WS3 Findings

This is where WS3 (customer discovery) directly shapes the product. The specific adaptations depend on what interviews reveal.

**Adaptation matrix:**

```
IF INTERVIEWS REVEAL...                    THEN ADJUST...

RMs mainly need draft messages             → Make "帮我写" the default mode
                                           → Add templates: post-CPI, post-FOMC, post-PBOC
                                           → Add client-type selector: 保守/稳健/积极

RMs mainly need morning briefing           → Prioritize scheduled push quality
                                           → Make WeCom push scannable in 30 seconds
                                           → Add "一句话总结" as first line always

Compliance is the main blocker             → Add prominent disclaimer on EVERY output
                                           → Add "此为AI草稿" watermark on drafts
                                           → Build audit log viewer for compliance team
                                           → Remove any feature that could be construed as advice

Procurement is too slow for B2B            → Flip to B2C first
                                           → Accelerate 公众号 as primary surface
                                           → WeCom bot as personal tool (no firm integration)

RMs want China macro more than US          → Weight PBOC/NBS/China data more heavily
                                           → Lead briefings with A-share/HK implications
                                           → US data as secondary context, not headline

RMs ask for features we didn't plan        → LISTEN. These are the real product.
                                           → Common surprises: "can it summarize 
                                             this research report?", "can it compare
                                             what different analysts are saying?"
```

---

## Per-User Context Memory

```python
# Simple per-user context stored in SQLite

CREATE TABLE user_context (
    user_id TEXT PRIMARY KEY,
    corp_name TEXT,           -- which firm
    role TEXT,                -- RM / PM / analyst / advisor
    asset_focus TEXT,         -- "A股,港股,美股" or "全球"
    client_types TEXT,        -- "保守型为主" or "积极型为主"
    language_pref TEXT,       -- "简体中文" (default)
    first_interaction TEXT,   -- timestamp
    last_interaction TEXT,    -- timestamp
    total_messages INTEGER,   -- usage tracking
    common_topics TEXT,       -- JSON: ["inflation", "fed", "china_policy"]
    notes TEXT                -- any manual notes
);

# On first interaction
async def onboard_new_user(user_id: str):
    await send_wecom_message(user_id, 
        "你好！我是Analyst宏观助手 👋\n\n"
        "我可以帮你：\n"
        "📊 回答宏观问题\n"
        "✏️ 起草客户评论（输入"帮我写..."）\n"
        "📋 准备客户沟通要点（输入"帮我准备..."）\n"
        "📅 查看今日经济日历（输入"今天日历"）\n"
        "🌐 查看宏观体系状态（输入"宏观状态"）\n\n"
        "请问你主要关注哪些市场？（A股/港股/美股/全球）"
    )
```

---

## Caching Strategy

```python
# Cache frequently-accessed data to reduce latency and LLM costs

CACHE = {
    "regime_state": {
        "ttl": 300,           # 5 minutes
        "source": engine.get_regime_state
    },
    "today_calendar": {
        "ttl": 600,           # 10 minutes
        "source": engine.get_today_calendar
    },
    "market_snapshot": {
        "ttl": 180,           # 3 minutes
        "source": engine.get_market_snapshot
    },
    "morning_briefing": {
        "ttl": 3600,          # 1 hour (only changes once per day)
        "source": engine.get_morning_briefing
    },
}

# Regime and calendar queries → serve from cache (< 2s response)
# Q&A and draft queries → always call LLM (8-12s response)
```

---

## Monitoring and Alerting

```python
# Track these metrics from day one

METRICS = {
    # Health
    "engine_uptime": "is the engine running?",
    "wecom_api_health": "can we send/receive WeCom messages?",
    "llm_api_latency_p95": "how fast is the LLM responding?",
    
    # Usage
    "daily_messages_total": "total messages received",
    "daily_messages_by_mode": "breakdown: qa / draft / prep / regime / calendar",
    "daily_active_users": "unique user_ids per day",
    "daily_push_sent": "briefings pushed to groups/users",
    
    # Quality
    "response_latency_p50": "median response time",
    "response_latency_p95": "95th percentile response time",
    "error_rate": "% of messages that returned error",
    "disclaimer_rate": "% of messages with disclaimer (must be 100%)",
}

# Alert if:
# - Engine down for > 5 minutes
# - Response latency P95 > 20 seconds
# - Error rate > 5%
# - Disclaimer rate < 100% (CRITICAL — fix immediately)
# - Morning briefing not generated by 7:15am CST
```

---

## Definition of Done

1. WeCom bot responds to all 5 interaction modes with real engine content
2. Message routing correctly detects keywords and routes to appropriate mode
3. Response latency < 15 seconds P95 for LLM calls, < 2 seconds for cached queries
4. 早盘速递 auto-publishes to 公众号 and pushes to WeCom every trading day by 7:30am
5. Flash 快评 pushes to WeCom within 5 minutes of high-importance data release
6. Mini Program displays live regime dashboard and searchable article archive
7. Per-user context memory tracks asset focus and personalizes responses
8. Error handling gracefully covers all failure modes (timeout, engine down, rate limit)
9. All interactions logged with full audit trail
10. Monitoring dashboard shows health, usage, and quality metrics
