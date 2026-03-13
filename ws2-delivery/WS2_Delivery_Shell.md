# Analyst — Workstream 2: Delivery Shell (Detailed Specification)

Status note on March 10, 2026:
This document describes the target WS2 scope. For the current implemented WS2 slice, see `00-overview/Implementation_Status.md`.
Current code includes a persona-driven Telegram agent bot (陈襄) deployed to a Contabo VPS with:
- 12-13 live tools (6 data scrapers + web search + web fetch + live calendar + article fetch + portfolio sync + image generation + optional live-photo generation)
- group chat support (observes silently, replies on @mention)
- reply-to-message context: referenced message text extracted and included in LLM prompt, with partial quote support
- user chat agent (`user_chat.py`) with client profile management and media extraction from tool results
- image generation via OpenRouter (`generate_image` tool) with photo delivery alongside text bubbles
- live-photo generation via SeedDance (`generate_live_photo` tool) with video delivery and managed temp-file cleanup
- conversation recording: all messages persisted to SQLite, 17 client profile dimensions extracted and accumulated
- emotional support and tool usage instructions in the persona prompt
WeCom transport, push delivery, and account setup remain target-state work.

## Strategic Context (from Marketing Research)

This workstream was fundamentally reshaped by marketing research findings. Read these before anything else.

**Build order changed.** Previously: 公众号 first, WeCom second. Now: WeCom first, 公众号 second. The product is an internal copilot for licensed RMs, not a public content account.

**The tool never touches the client directly.** The RM asks the tool for a draft → reviews/edits → sends to client themselves. CSRC IT rules state third-party IT services must not participate in any link of customer-facing business service. Our tool helps the licensed human; the licensed human serves the client.

**Two paths, built sequentially.**
- Path A (build now): Internal productivity copilot. Drafting, Q&A, briefing push inside WeCom. No formal procurement needed.
- Path B (build later): Client-facing communication platform with compliance logging, archiving, audit trail. Requires IT/compliance review.

**Competition context.** Wind AI briefing, Eastmoney 妙想, 同花顺 HithinkGPT, 招商证券天启大模型 all exist. But none owns the "WeCom-native macro copilot for RMs" position. Our shell must feel like a personal macro strategist inside WeCom, not another generic AI research terminal.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  DELIVERY SHELL                                          │
│  (All components are "dumb pipes" — no content           │
│   generation happens here. Engine provides all content.) │
│                                                          │
│  ┌───────────────────────────────────────────────┐      │
│  │  A. WeCom Bot (PRIMARY — build first)          │      │
│  │     Internal copilot for licensed RMs           │      │
│  │     Chat Q&A, draft mode, briefing push         │      │
│  └───────────────────────────────────────────────┘      │
│                                                          │
│  ┌───────────────────────────────────────────────┐      │
│  │  B. WeChat Official Account (SECONDARY)        │      │
│  │     Brand building, B2C funnel                  │      │
│  │     Daily articles, public credibility           │      │
│  └───────────────────────────────────────────────┘      │
│                                                          │
│  ┌───────────────────────────────────────────────┐      │
│  │  C. Mini Program (REFERENCE TOOL)              │      │
│  │     Regime dashboard, archive, calendar          │      │
│  └───────────────────────────────────────────────┘      │
│                                                          │
│  ┌───────────────────────────────────────────────┐      │
│  │  D. API Layer (FUTURE — Path B)                │      │
│  │     JSON endpoints, webhooks, institutional      │      │
│  └───────────────────────────────────────────────┘      │
│                                                          │
│  ALL components read from the same engine output.        │
│  Engine writes: Chinese markdown + structured JSON       │
│  Shell reads and delivers. Shell generates nothing.      │
└─────────────────────────────────────────────────────────┘
```

---

## Component A: WeCom Bot (PRIMARY — Month 1–2)

This is the core product surface. Everything else is secondary.

### Why WeCom, Not Regular WeChat

- WeCom connects 14 million real enterprises, serving 750 million WeChat users daily through WeCom
- Brokers like BOCI, Cinda, and Chuancai already use WeCom for official advisory and client service
- WeCom 5.0 (released August 2025) integrates AI capabilities natively, including smart bots and intelligent search
- Tencent Cloud documents publishing intelligent agents to WeCom
- WeCom API supports message sending, contact management, callback events, media upload, and bot integration
- WeCom provides enterprise-grade message archiving — critical for future Path B compliance
- Internal enterprise applications on WeCom don't require public-facing GenAI filing under CAC rules

### Technical Implementation

**Two integration modes available:**

```
MODE 1: WeCom Bot (Webhook)                MODE 2: WeCom Self-Built App (Agent)
──────────────────────────                  ──────────────────────────────────
Simpler, faster to build                    More powerful, more control
Send messages to group chats                Full 2-way conversation
via webhook URL                             Callback-based message handling
No callback (can't receive messages)        Can receive and respond to messages
Good for: push-only (briefing delivery)     Good for: interactive Q&A + drafting
                                            
BUILD BOTH: Webhook for push,               
            Agent for interactive            
```

**WeCom Self-Built App setup:**

```
Step 1: Register WeCom (企业微信) account
        → Get CorpID (企业ID)

Step 2: Create Self-Built App (自建应用) in WeCom Admin Console
        → App Management → Build Your Own → Create App
        → Set name: "Analyst 宏观助手"
        → Set visibility scope (which employees can access)
        → Get AgentId and Secret

Step 3: Configure callback (接收消息)
        → Set API reception URL (your server endpoint)
        → Generate Token and EncodingAESKey
        → Your server must respond to Tencent's verification request

Step 4: Implement message handling
        → Receive XML callback when user sends message
        → Parse message → route to engine → get response
        → Send reply via WeCom API
```

**Server-side architecture:**

```python
# Simplified WeCom bot architecture

# ── Incoming message handler ──
@app.post("/wecom/callback")
async def wecom_callback(request: Request):
    """
    Tencent sends XML callback here when a user messages the bot.
    Parse, route to engine, respond.
    """
    xml_data = await request.body()
    message = decrypt_and_parse(xml_data)
    
    user_id = message["FromUserName"]
    content = message["Content"]
    
    # Route to appropriate engine mode
    if is_draft_request(content):
        # "帮我写..." / "帮我准备..." → Draft mode
        response = await engine.generate_draft(content, user_id)
    elif is_calendar_query(content):
        # "今天有什么数据" → Calendar lookup
        response = await engine.get_today_calendar()
    elif is_regime_query(content):
        # "现在宏观怎么看" → Regime summary
        response = await engine.get_regime_summary()
    else:
        # General macro Q&A
        response = await engine.answer_question(content, user_id)
    
    # Add disclaimer
    response += "\n\n⚠️ 此内容由AI辅助生成，请审核后使用"
    
    # Send reply
    await send_wecom_message(user_id, response)


# ── Scheduled push (via webhook) ──
async def push_morning_briefing():
    """
    Runs at 7:30am CST. Pushes 早盘速递 to all subscribed groups/users.
    """
    briefing = await engine.get_morning_briefing()
    
    # Push to webhook groups
    for webhook_url in SUBSCRIBED_GROUPS:
        await send_webhook_message(webhook_url, briefing)
    
    # Push to individual users via Agent API
    for user_id in SUBSCRIBED_USERS:
        await send_wecom_message(user_id, briefing)
```

### Interaction Modes (What the RM Sees)

**Mode 1: Q&A (default)**

```
RM types:  "今晚CPI数据怎么看？"
Bot replies: [2-3 paragraph macro analysis in Chinese]
             [cross-asset implications]
             ⚠️ 此内容由AI辅助生成，请审核后使用
```

**Mode 2: Draft for Client (keyword trigger: 帮我写/帮我准备/草拟)**

```
RM types:  "帮我写一段今晚非农数据的客户点评"
Bot replies: ---客户消息草稿---
             
             [2-3 paragraph client-appropriate commentary]
             [plain language, no jargon]
             [ends with forward-looking statement]
             
             ---草稿结束---
             ⚠️ 以上为AI草稿，请审核修改后发送给客户
```

**Mode 3: Meeting Prep (keyword trigger: 准备/会议/沟通要点)**

```
RM types:  "明早要跟VIP客户聊美联储决议，帮我准备沟通要点"
Bot replies: 📋 客户沟通准备要点
             
             1. 核心结论：[one sentence]
             2. 关键数据：[3 bullet points]
             3. 对客户持仓影响：[based on client profile if known]
             4. 客户可能的问题及建议回答：
                Q: [anticipated question 1]
                A: [suggested answer]
                Q: [anticipated question 2]
                A: [suggested answer]
             5. 需要注意：[risk/caveat]
             
             ⚠️ 此内容由AI辅助生成，请结合客户实际情况调整
```

**Mode 4: Regime Check (keyword trigger: 宏观/体系/状态/regime)**

```
RM types:  "现在宏观状态怎么样"
Bot replies: 📊 宏观体系状态 (更新于: 2026-03-06 08:00 CST)
             
             风险偏好:    ██░░░░  0.35 (偏弱)
             美联储鹰派度: █████░  0.78 (偏鹰)
             增长动能:    ███░░░  0.55 (中性偏弱)
             通胀趋势:    去通胀停滞
             流动性环境:   收紧中
             
             主导叙事: 软着陆叙事承压，市场定价2次降息但数据指向0-1次
             叙事风险: 若下次CPI再超预期，可能触发再加速恐慌
             
             上次更新触发: 美国CPI连续第三次超预期
```

**Mode 5: Calendar (keyword trigger: 日历/今天/数据/事件)**

```
RM types:  "今天有什么重要数据"
Bot replies: 📅 2026-03-06 经济日历
             
             🔴 高重要性:
             21:30 美国 非农就业 (预期: +180K, 前值: +143K)
             21:30 美国 失业率 (预期: 4.0%, 前值: 4.0%)
             
             🟡 中重要性:
             17:00 欧元区 GDP修正值 (预期: 0.1%, 前值: 0.1%)
             
             💡 Analyst观点: 今晚非农是本周最重要事件。
             若大幅超预期(>220K)，将强化"不降息"叙事，
             美元走强，风险资产承压。关注薪资增速分项。
```

### Disclaimer System (Critical for Compliance)

Every single output from the WeCom bot must include a disclaimer. This is non-negotiable.

```python
# Disclaimer templates by interaction mode

DISCLAIMERS = {
    "qa": "⚠️ 此内容由AI辅助生成，仅供内部参考，不构成投资建议。",
    
    "draft": "⚠️ 以上为AI辅助生成的草稿，请审核修改后再发送给客户。"
            "内容不构成投资建议，请确保符合公司合规要求。",
    
    "meeting_prep": "⚠️ 此内容由AI辅助生成，请结合客户实际情况调整。"
                    "不构成投资建议。",
    
    "regime": "⚠️ 宏观状态评估由AI模型生成，仅供参考，不构成投资建议。",
    
    "push": "⚠️ 此简报由AI辅助生成，仅供内部参考。"
}

def append_disclaimer(content: str, mode: str) -> str:
    return f"{content}\n\n{DISCLAIMERS.get(mode, DISCLAIMERS['qa'])}"
```

### Interaction Logging (Path B Preparation)

Even in Path A, log everything. This prepares for Path B compliance requirements and provides data for quality improvement.

```python
# Log every interaction — prepare for compliance from day one

@dataclass
class InteractionLog:
    timestamp: str          # ISO 8601
    user_id: str            # WeCom user ID
    user_corp: str          # Which firm they belong to
    input_text: str         # What the RM asked
    output_text: str        # What we generated
    mode: str               # qa / draft / meeting_prep / regime / calendar
    engine_model: str       # Which LLM generated this
    disclaimer_shown: bool  # Always True
    response_time_ms: int   # Latency tracking
    
    # Path B additions (add later):
    # edited_text: str      # What the RM actually sent (if we can capture)
    # forwarded: bool       # Whether RM sent it to client
    # compliance_reviewed: bool
```

### Month 1 Deliverables

```
Week 1-2:
├── WeCom account registration and verification
├── Self-Built App created ("Analyst 宏观助手")
│   ├── AgentId, Secret, Token, EncodingAESKey obtained
│   └── Visibility scope set (initially: your own team for testing)
├── Server endpoint for callback configured
│   ├── FastAPI server on Contabo VPS
│   ├── Tencent verification handshake working
│   └── Can receive and echo back messages
├── Webhook bot created for push delivery
│   ├── Webhook URL obtained
│   └── Can send markdown messages to a test group
└── Message handling skeleton
    ├── Receives message → logs it → sends placeholder response
    ├── Keyword routing: detect 帮我写/准备/日历/宏观 etc.
    └── Disclaimer auto-appended to every response

Week 3-4:
├── All 5 interaction modes working with placeholder content
│   ├── Q&A: receives question, returns "placeholder answer + disclaimer"
│   ├── Draft: detects "帮我写", returns "placeholder draft + disclaimer"  
│   ├── Meeting prep: detects "准备", returns "placeholder prep + disclaimer"
│   ├── Regime: detects "宏观状态", returns "placeholder regime + disclaimer"
│   └── Calendar: detects "今天", returns "placeholder calendar + disclaimer"
├── Scheduled push working
│   ├── 7:30am CST: sends placeholder 早盘速递 via webhook
│   ├── Event-triggered: manual trigger sends placeholder 快评
│   └── Push format tested: markdown renders correctly in WeCom
├── Interaction logging
│   ├── Every message in/out logged to SQLite
│   └── Basic analytics: messages per day, modes used, response times
└── Ready for engine connection (Workstream 4)
```

**Definition of done (Month 1):** The WeCom bot receives messages, routes them by keyword, returns formatted placeholder responses with disclaimers, pushes scheduled briefings to groups, and logs everything. No engine connection needed yet — this shell works independently.

### Month 2 Deliverables

```
Week 5-6 (after engine connection in WS4):
├── Live engine responses replacing placeholders
│   ├── Real macro Q&A powered by Analyst agent
│   ├── Real client drafts powered by Sales agent
│   ├── Real meeting prep powered by Sales agent
│   ├── Real regime state from engine JSON
│   └── Real calendar from engine's economic calendar
├── Per-user context memory
│   ├── Store: user_id → {firm, role, asset_focus, conversation_history}
│   ├── First interaction: "你好！我是Analyst宏观助手。请问你主要关注哪些市场？"
│   ├── Subsequent: responses tailored to their known interests
│   └── Simple SQLite storage, nothing complex
├── Response quality monitoring
│   ├── Sample 10% of responses for manual review
│   ├── Track: response time P50/P95 (target: <15 seconds)
│   └── Flag: any response without disclaimer (should never happen)
└── Error handling
    ├── Engine timeout → "正在分析中，请稍候..." + retry
    ├── Engine failure → "暂时无法回答，请稍后再试"
    ├── Rate limit → queue messages, process in order
    └── Never show raw error messages or stack traces to users
```

---

## Component B: WeChat Official Account (SECONDARY — Month 1–2)

The 公众号 is NOT the core product. It serves three purposes: brand credibility, B2C funnel for later, and a public archive of the Analyst's track record.

### Setup (Month 1, can run parallel)

```
Week 1:
├── Register WeChat Official Account (服务号 or 订阅号)
│   ├── 服务号 (Service Account): 4 articles/month, but has Mini Program + menu
│   ├── 订阅号 (Subscription Account): daily articles, but limited features
│   └── Recommendation: 订阅号 for daily content, add 服务号 later for Mini Program
├── Verify account (requires Chinese business entity or individual ID)
│   ├── This can take 1-3 weeks — start immediately
│   └── Cost: ¥300/year verification fee
├── Design article templates
│   ├── 早盘速递 template: header image, structured sections, visual scores
│   ├── 数据快评 template: headline, key data, analysis, implications
│   └── 收盘点评 template: market moves, regime update, tomorrow preview
└── Manual publishing workflow (before automation)
    ├── Engine generates markdown → you format in WeChat editor → publish
    ├── This is fine for Month 1 — automation comes in WS4
    └── Target: publish daily 早盘速递 starting week 2

Week 3-4:
├── Content calendar established
│   ├── Daily 7:30am: 早盘速递
│   ├── Event-driven: 数据快评 (whenever major data drops)
│   ├── Daily 5:00pm: 收盘点评 (if significant moves)
│   └── Weekly Sunday: 宏观周报
├── Article format refined based on early reader feedback
└── Follower tracking: target 200+ followers by end of Month 2
```

### Article Format (What Gets Published)

```
┌──────────────────────────────────────────┐
│  📊 Analyst 早盘速递 | 2026.03.06        │
│                                          │
│  ▎一句话总结                              │
│  昨晚美国CPI连续第三次超预期，           │
│  联储降息预期大幅回调，今日亚太承压。     │
│                                          │
│  ▎宏观体系状态                            │
│  风险偏好 ██░░░░ 0.35                    │
│  鹰派指数 █████░ 0.78                    │
│  体系标签: 风险回避                       │
│                                          │
│  ▎隔夜要点                               │
│  • [Key point 1 with analysis]           │
│  • [Key point 2 with analysis]           │
│  • [Key point 3 with analysis]           │
│                                          │
│  ▎今日关注                               │
│  21:30 美国非农就业 (重要性: 🔴)          │
│  预期: +180K | 前值: +143K               │
│  关注要点: [what to watch for]            │
│                                          │
│  ▎跨资产影响                              │
│  A股: [view]  港股: [view]               │
│  美债: [view]  美元: [view]              │
│  黄金: [view]  加密: [view]              │
│                                          │
│  ⚠️ 本文由AI辅助生成，仅供参考，          │
│  不构成投资建议。                          │
└──────────────────────────────────────────┘
```

### Auto-Publish Pipeline (Month 2, part of WS4)

```python
# Auto-publish to 公众号 (after WS4 integration)

async def publish_morning_briefing():
    """
    Runs at 7:15am CST.
    Gets engine output → formats as WeChat article → publishes.
    """
    # Get content from engine
    briefing = await engine.get_morning_briefing()
    regime = await engine.get_regime_state()
    calendar = await engine.get_today_calendar()
    
    # Format as WeChat article HTML
    article_html = format_weixin_article(
        template="morning_briefing",
        content=briefing,
        regime=regime,
        calendar=calendar,
        disclaimer=DISCLAIMERS["push"]
    )
    
    # Option A: Auto-publish (if confident in quality)
    await weixin_api.publish_article(article_html)
    
    # Option B: Push to review queue (safer for early stage)
    await notify_reviewer(
        channel="wecom",
        message=f"早盘速递已生成，请审核后发布: {preview_link}"
    )
```

---

## Component C: Mini Program (REFERENCE TOOL — Month 2)

The Mini Program is a dashboard and archive — not a chat interface. Users come here to check scores, search past analysis, and view the calendar. Keep it simple.

### Features (MVP)

```
SCREEN 1: Regime Dashboard (首页)
├── Visual gauge: 风险偏好 (risk appetite score, 0-1)
├── Visual gauge: 鹰派指数 (Fed hawkishness, 0-1)
├── Visual gauge: 增长动能 (growth momentum, 0-1)
├── Text: 通胀趋势, 流动性环境
├── Text: 主导叙事 (dominant narrative, 1-2 sentences)
├── Text: 叙事风险 (narrative risk, 1 sentence)
├── Badge: 体系标签 (regime label: 风险偏好/中性/风险回避)
├── Timestamp: 最后更新时间 + 触发事件
└── Link: "查看详细分析" → today's 早盘速递 article

SCREEN 2: Economic Calendar (经济日历)
├── Today's events with importance flags (🔴🟡🟢)
├── For each event: indicator, country, time, forecast, previous
├── If released: actual value + surprise + Analyst's quick take
├── This week's upcoming events
└── Filter: by country (US/CN/EU/JP) and importance

SCREEN 3: Research Archive (研究归档)
├── Searchable list of all published analysis
├── Filter: by type (早盘/快评/周报/深度)
├── Filter: by date range
├── Search: keyword search across all content
├── Tier gating: free users see titles + first paragraph
│   Standard users see everything
└── Each article links to full 公众号 article

SCREEN 4: Settings (设置)
├── Alert preferences: which events trigger WeCom push
├── Market focus: A股/港股/美股/外汇/商品/加密 (used to personalize)
├── Push schedule: enable/disable 早盘/收盘/快评
└── Subscription tier management (future)
```

### Technical Implementation

```
Framework: Tencent Mini Program (微信小程序)
├── Use Tencent's native framework (not React/Vue — Mini Program has its own)
├── WXML (template) + WXSS (style) + JS (logic)
├── Or use uni-app / Taro for cross-platform development

Backend API (same FastAPI server as WeCom bot):
├── GET /api/regime       → current regime state JSON
├── GET /api/calendar     → today's economic calendar
├── GET /api/articles     → paginated article list
├── GET /api/articles/:id → single article content
├── GET /api/search?q=    → full-text search
└── Auth: Mini Program login → user_id → tier check

Data flow:
├── Mini Program calls API on open
├── Regime dashboard polls every 5 minutes (or on pull-to-refresh)
├── Calendar updates hourly
├── Articles update on publish
└── All data comes from the same engine storage (SQLite/PostgreSQL)
```

### Month 2 Deliverables

```
Week 5-6:
├── Mini Program registered and approved by Tencent
├── Regime dashboard screen working (reads from engine JSON)
├── Calendar screen working (reads from engine calendar data)
├── Basic article list (static data for testing)
└── Navigation between screens

Week 7-8:
├── Research archive with search working
├── Settings screen (alert preferences, market focus)
├── Connected to live engine data (via WS4 integration)
├── Pull-to-refresh on dashboard
└── Deep link: WeCom message → Mini Program article
```

---

## Component D: API Layer (FUTURE — Path B, Month 6+)

Not built in MVP. Documented here for architecture planning only.

```
FUTURE API ENDPOINTS:
├── GET  /api/v1/regime              → current regime state
├── GET  /api/v1/regime/history      → historical regime states
├── GET  /api/v1/flash/:event_id     → specific flash commentary
├── GET  /api/v1/briefing/latest     → latest daily briefing
├── GET  /api/v1/calendar            → economic calendar with Analyst views
├── POST /api/v1/ask                 → Q&A endpoint (for institutional integration)
├── WebSocket /ws/regime             → real-time regime updates
└── Webhook registration             → push regime changes to client systems

Authentication: API key per institution
Rate limits: tiered by subscription
Format: JSON
Documentation: OpenAPI/Swagger

This is what the company's crypto trading agents will consume.
This is what institutional clients will integrate into their workflows.
Build this only after B2B traction proves demand.
```

---

## Path A → Path B Upgrade Checklist

When marketing signals justify moving to Path B (tool integrated into official client channels), these components must be added to the delivery shell:

```
COMPLIANCE FEATURES (Path B additions):
├── Message archiving
│   ├── Every AI-generated output stored with full audit trail
│   ├── Timestamp, user, input, output, model version, disclaimer shown
│   ├── Compatible with WeCom conversation archiving
│   └── Retention: configurable per institution (minimum 3 years)
│
├── Content review queue
│   ├── Option: all AI output held for human review before visible
│   ├── Compliance officer can approve/reject/edit
│   ├── Audit log of all review decisions
│   └── SLA tracking: time from generation to approval
│
├── User management
│   ├── Role-based access: RM, Team Lead, Compliance, Admin
│   ├── RM sees: Q&A, draft, briefing
│   ├── Compliance sees: all outputs + audit log + review queue
│   ├── Admin sees: team management + usage analytics
│   └── SSO integration with broker's existing identity system
│
├── Approved talking points
│   ├── Pre-vetted, compliance-approved response templates
│   ├── Analyst generates → compliance reviews → approved version stored
│   ├── RMs can pull approved talking points without waiting for live generation
│   └── "After tonight's FOMC, use these approved talking points with clients"
│
├── Client segmentation
│   ├── Tag clients: 保守型/稳健型/积极型
│   ├── Tag clients: A股/港股/美股/全球
│   ├── Auto-adjust draft tone and content based on client tags
│   └── Team lead sets segmentation rules, tool applies them
│
└── Analytics dashboard (for team leads)
    ├── Usage: messages per RM per day
    ├── Response quality: compliance rejection rate
    ├── Time saved: before vs after Analyst
    └── Most common questions (content gap identification)
```

---

## Full Timeline (WS2 Only)

```
MONTH 1                           MONTH 2                        MONTH 3+
──────                            ──────                         ──────

Week 1-2:                         Week 5-6:                      Integration with
• WeCom account + app setup       • Engine connected (WS4)       seed users
• Callback endpoint working       • Live Q&A working             • Iterate based on
• Webhook push working            • Live drafts working          RM feedback
• Placeholder responses           • Mini Program MVP             • Add features RMs
• 公众号 registration started      • Per-user memory              actually request
• Article templates designed       • Error handling               • Quality monitoring
                                                                 
Week 3-4:                         Week 7-8:                      Path B prep:
• All 5 interaction modes         • Auto-publish to 公众号        • Compliance logging
  working (with placeholders)     • Mini Program connected        • Archiving
• Scheduled push working          • Search working                • Review queue
• Interaction logging active      • Deep links WeCom→Mini         • (only if demand
• 公众号 manual publishing         • Push notifications            signals justify)
  started (daily 早盘)                                           
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| WeCom app approval delayed | Start registration week 1. Have backup: personal WeChat group testing while waiting. |
| Message formatting issues (markdown rendering) | Test all format types in WeCom client early. WeCom supports markdown in bot messages but rendering varies by client version. |
| Response latency too high (>15s) | Implement streaming where WeCom supports it. Show "正在分析..." status. Pre-generate common content (daily briefing, regime summary) to serve from cache. |
| 公众号 verification rejected | Ensure Chinese business entity or valid individual ID. Financial content may face additional review — keep initial articles educational/informational, not advisory. |
| Tencent API rate limits | WeCom API: ~2000 messages/min per app. Well within our needs. Cache regime state and calendar — don't call engine on every request. |
| User confuses AI output with investment advice | Disclaimer on every single message, no exceptions. Never generate specific stock/fund buy/sell recommendations. Frame everything as "macro environment analysis." |
| Competitor copies the WeCom bot approach | Speed advantage: ship first. Quality advantage: better macro engine. Relationship advantage: per-user memory and personalization compound over time. |

---

## Definition of Done (WS2 Complete)

The delivery shell is done when:

1. An RM on WeCom can type a macro question and get a useful Chinese-language answer within 15 seconds
2. An RM can say "帮我写一段CPI点评给客户" and get an editable draft with disclaimer
3. An RM can say "帮我准备明早客户沟通要点" and get structured talking points
4. A scheduled 早盘速递 arrives in WeCom groups at 7:30am every trading day
5. A flash 快评 arrives within 5 minutes of a major data release
6. The Mini Program shows a live regime dashboard, calendar, and searchable archive
7. The 公众号 publishes daily articles (initially manual, then automated)
8. Every single output includes an appropriate disclaimer
9. Every interaction is logged with timestamp, user, input, output, and mode
10. A non-technical RM can use the entire product without any setup or training
