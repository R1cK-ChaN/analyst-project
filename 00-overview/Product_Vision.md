# Analyst — Product Vision

## One-Line Positioning

We replace the repetitive macro-analysis and client-explaining work of sell-side and wealth teams, inside the channels China's financial clients already use.

---

## What Analyst Is

Analyst is a WeChat-native macro intelligence platform with chat, push, dashboard, and API. It functions as a macro strategist and client-service copilot — not a public stock-advice bot.

The role it replaces is closer to **sell-side macro strategist + sales assistant** than a classic IBD analyst. Every day, macro sales and wealth teams at Chinese securities firms do the same work: read overnight data, write morning notes, push commentary to clients on WeChat, answer the same questions 50 times ("今晚非农怎么看？"), and prep for client calls. Analyst automates all of that, at higher speed and consistency, inside the same WeChat/WeCom channels these teams already live in.

---

## Why This, Why Now

**The demand is real.** China has the world's largest base of active investors, and macro literacy is rising. Every tariff headline, FOMC decision, or CPI surprise triggers thousands of WeChat messages between advisors and clients asking "what does this mean for us?" The sell-side analyst writing that note is the bottleneck.

**The delivery channel is ready.** WeChat/Weixin has 1.4 billion MAU. WeCom integrates with WeChat and supports enterprise communication, customer service, chat, Mini Programs, and enterprise apps. Tencent Cloud already documents publishing intelligent agents to WeChat Official Accounts and WeCom so accounts can reply to user messages automatically. The infrastructure exists — the macro brain doesn't.

**The regulatory path is clear.** Positioning as macro intelligence and workflow tooling for licensed teams — not public investment advice — is the safest entry. CSRC requires approval for securities investment consulting, and is currently not accepting new applications for investment consulting institutions. Public-facing generative AI services fall under the Interim Measures for Generative AI Services, while internal enterprise tools that are not provided to the public do not. Our positioning: **macro intelligence + workflow + client servicing first, regulated investment advice later or through licensed partners.**

---

## Who We Serve

### Tier 1: Licensed Financial Teams (best first customer)

Securities firms' wealth management teams, institutional sales teams, private-bank and wealth-advisory teams, smaller brokers without strong in-house macro coverage, and cross-border desks serving clients who need global macro translated into client-ready language.

Why they're the best first customer: they already live in WeChat/WeCom, they already need daily client communication, they can pay more than retail, and internal-tool positioning is safer than public advisory positioning under current rules.

### Tier 2: Private Funds, Family Offices, Corporate Treasury

They need macro regime awareness, fast summaries, cross-asset interpretation, fewer meetings, and faster decisions. They don't need a full sell-side relationship — they need the output without the overhead.

### Tier 3: Serious Self-Directed Investors (later)

Lower-touch subscription. Standard briefings. Educational macro content. Serve them after the product is proven with professional users. Do not start with mass retail stock-tipping.

---

## What We Provide

### Service A: Core Macro Content

This is the must-have product — the analyst's brain.

**Daily (automated, push to followers):**

- **早盘速递 (Pre-Market Briefing)** — What happened overnight in US/Europe/Asia markets, what's on today's economic calendar, what to watch, key levels. Delivered before market open (~7:30am CST for A-shares, adjusted for HK/US sessions).

- **数据快评 (Flash Commentary)** — When CPI, NFP, PMI, FOMC, PBOC, LPR, tariff news, or geopolitical events drop, instant commentary within minutes. Not "CPI was 3.4%" — rather "美国CPI连续第三次超预期，联储降息预期大幅回调，对A股港股意味着什么？" Connects the data to the narrative, to policy expectations, to cross-asset implications, to what Chinese investors actually care about.

- **收盘点评 (After-Market Wrap)** — What moved, why, what changed in the regime view, what to watch tonight/tomorrow.

**Weekly:**

- **宏观周报 (Weekly Macro Review)** — Synthesizes the week's data, updates the regime assessment, provides a cross-asset outlook for the week ahead.

- **主题深度 (Thematic Deep Dive)** — "美联储还能降息吗？", "日元套利交易逆转对港股的影响", "中国刺激政策到底有没有效？", "关税升级的三种情景分析"

**Persistent:**

- **宏观体系状态 (Macro Regime State)** — A structured, machine-readable assessment of the global macro environment that updates continuously. Tracks risk appetite, central bank stance, growth momentum, inflation trend, liquidity conditions, dominant market narrative, and what would break it. Includes explicit cross-asset implications for rates, dollar, equities, credit, commodities, and crypto.

- **情景分析 (Scenario Framework)** — Bullish / base / risk case with probabilities, updated as evidence accumulates.

- **"昨天到今天变了什么？" (What Changed)** — A daily diff of the regime state, highlighting what shifted and why. This is the single most useful output for busy PMs.

### Service B: Conversational Client Service

This is what makes it feel like having a sell-side analyst on call — the Sales Agent.

- **Ask-anything chat in WeChat/WeCom** — Client asks "今天CPI数据怎么看？" and gets a thoughtful, contextualized answer within seconds, not a generic chatbot response.

- **Personalized by client type** — The agent remembers whether this client trades A-shares, HK, US, or cross-border. Adjusts language, examples, and implications accordingly.

- **"今晚美联储议息，我该跟客户说什么？" (Meeting Prep)** — For wealth advisors: draft talking points, key scenarios, client-appropriate language. The agent becomes a prep assistant before every client call.

- **Draft follow-up messages** — After a big data release, generate client-appropriate WeChat messages that advisors can review, edit, and send. Saves hours of repetitive writing.

- **FAQ memory and client memory** — Tracks what each client has asked about, their interests, their portfolio focus. Over time, responses become increasingly tailored.

### Service C: Institutional Workflow Tools

This is what makes institutions pay real money — the difference between a "content account" and a "product."

- **API and webhooks** — Raw regime scores, flash commentary, and alerts as structured JSON. For quant teams, risk systems, and internal dashboards.

- **Alert routing by client segment** — Wealth team serving conservative retirees gets different alert framing than the team serving active traders.

- **Analyst note archive and search** — Full searchable history of all commentary. "Show me everything we said about inflation in Q4 2025."

- **Bilingual CN/EN summaries** — For cross-border teams serving both mainland and international clients.

- **Compliance/audit log** — Record of all generated content and client interactions.

- **Team workspace** — Multiple users (RMs, sales, PMs) accessing the same macro intelligence with role-based views.

- **CRM-linked memory** — Connects client interaction history with the Sales agent's memory for seamless handoffs between team members.

- **Approved talking points** — Pre-vetted, compliance-friendly language that client-facing staff can use directly.

---

## Product Architecture

### Four Layers

```
┌─────────────────────────────────────────────────────┐
│  LAYER 4: Enterprise / API                           │
│  API, webhooks, team workspace, compliance log,      │
│  CRM integration, bilingual output                   │
├─────────────────────────────────────────────────────┤
│  LAYER 3: Mini Program / Dashboard                   │
│  Regime dashboard, research archive, watchlists,     │
│  score history, settings, subscription management    │
├─────────────────────────────────────────────────────┤
│  LAYER 2: WeChat + WeCom Delivery                    │
│  Official Account (公众号) for content push           │
│  WeCom for enterprise client service                 │
│  Chat bot for Q&A                                    │
│  Group chats for community                           │
├─────────────────────────────────────────────────────┤
│  LAYER 1: Core Macro Engine                          │
│  Data ingestion, LLM analysis, regime state,         │
│  flash commentary, daily briefings, deep analysis    │
└─────────────────────────────────────────────────────┘
```

### Agent Architecture (Three Agents, Same Loop, Different Roles)

All three agents share the same underlying loop (observe → think → act) but differ in system prompts, tools, memory, and cadence.

**Agent 1: Analyst Agent (the brain)**

- Watches: economic data (FRED, BLS, BEA), central bank comms (Fed/ECB/BOJ/PBOC RSS), cross-asset prices (yfinance), economic calendar (Investing.com/ForexFactory scrape), news (Finnhub, Alpha Vantage, Google News RSS)
- Produces: flash commentary, daily briefings, deep analysis, regime state updates
- Memory (private): working notes, draft analysis, confidence calibration
- Memory (published): finished research → Shared Research Store
- Cadence: event-driven (data releases) + scheduled (daily briefing, weekly review)
- Language: generates in Chinese (primary) and English (for bilingual clients)

**Agent 2: Trader Agent (the proof — internal only)**

- Reads: Analyst's regime state and research
- Does: manages positions to generate a verifiable track record
- Purpose: proves the Analyst's signals have portfolio value; demonstrates API integration
- The Trader is not the product. The Analyst is the product. The Trader is the proof.
- Initial scope: crypto (beachhead, company alignment), expandable to multi-asset
- Memory (published): aggregated track record only → Performance Store

**Agent 3: Sales Agent (the relationship layer)**

- Reads: Research Store (gated by client tier), Performance Store, client profiles
- Does: answers client questions, drafts messages, preps meeting talking points, handles objections, manages relationships
- Channels: WeChat/WeCom chat, group messages
- Memory (private): per-client profiles, conversation history, preferences, watchlists
- Hard boundary: never sees Trader positions or strategy parameters

### Memory Architecture

```
SHARED STORES:

  Research Store
  ├── Published analyst output (flash notes, briefings, regime state)
  ├── Schema-enforced, tagged by tier and client_safe flag
  └── Write: Analyst only | Read: Trader, Sales (gated)

  Performance Store
  ├── Aggregated track record (no positions)
  └── Write: Trader only | Read: Sales only

  Market State Store
  ├── Latest cross-asset prices, yields, spreads
  ├── Economic calendar with consensus
  └── Write: Scrapers | Read: All agents

HARD BOUNDARIES:
  - Analyst never sees trading positions
  - Sales agent never sees strategy parameters
  - Clients never see other clients' data
  - Agents publish structured JSON, never raw context
```

---

## Platform Strategy

### WeChat/WeCom = Main Product

```
WeChat Official Account (公众号)
├── Daily articles: 早盘速递, 数据快评, 收盘点评
├── Weekly articles: 宏观周报, 主题深度
├── Public-facing content and brand surface
├── Free tier: everyone can follow and read
└── Acquisition channel for paid tiers

WeCom (企业微信)
├── Enterprise client service delivery
├── Chat bot integration for Q&A
├── Client segmentation and routing
├── Message templates for advisors
├── Compliance logging
└── Primary channel for B2B paid tiers

WeChat Mini Program (小程序)
├── Live regime dashboard with visual scores
├── Today's calendar with Analyst's pre-event view
├── Research archive (searchable, filterable)
├── Watchlist with personalized implications
├── Score history and regime change timeline
├── Subscription management and settings
└── Premium feature surface
```

### Rednote (小红书) = Discovery Only

```
Rednote
├── Short-form macro explainers (图文笔记)
│   "3分钟看懂今天的非农数据"
│   "一张图理解美联储点阵图"
├── Visual cards with key takeaways
├── Thought leadership and brand building
├── Purpose: top-of-funnel acquisition
└── Convert serious users → WeChat ecosystem
```

Rednote is for discovery. WeChat is for retention and monetization. Do not try to build the core product on Rednote.

---

## Data Sources (All Free or Low-Cost)

```
ECONOMIC DATA
├── FRED API (free)           US macro: GDP, CPI, NFP, yields, M2, Fed balance sheet
├── BLS / BEA RSS (free)      Original source for US employment, inflation, GDP
├── PBOC website (scrape)     China monetary policy, LPR, RRR
├── NBS China (scrape)        China PMI, GDP, industrial production, retail sales
├── ECB / BOJ RSS (free)      European and Japanese monetary policy

MARKET PRICES
├── yfinance (free)           Cross-asset: SPX, NDX, HSI, CSI300, DXY, USDCNY,
│                             gold, oil, copper, bond yields, VIX
├── Exchange APIs (free)      Crypto: BTC, ETH, funding rates, OI
└── Wind/Choice (if budget)   A-share specific data (future upgrade)

CENTRAL BANK COMMUNICATIONS
├── Fed RSS (free)            FOMC statements, speeches, minutes
├── ECB / BOJ / BOE RSS       Global central bank comms
├── PBOC announcements         Scrape official site for PBOC communications
└── China State Council        Policy announcements, stimulus signals

NEWS & INTELLIGENCE
├── Finnhub API (free)        Structured market news with sentiment
├── Alpha Vantage (free)      News with sentiment scores
├── Google News RSS (free)    Customizable: "Fed policy", "China economy", "tariffs"
├── Xinhua / CCTV RSS         China official news source
├── Caixin / 21st Century     China financial media
└── CoinDesk / The Block      Crypto-specific (for company alignment)

CALENDAR
├── Investing.com (scrape)    Global economic calendar with actual/forecast/previous
├── ForexFactory (scrape)     Alternative calendar source
└── China calendar sources    NBS release schedule, PBOC meeting dates
```

---

## Pricing

### B2B Tiers (primary revenue)

| Tier | Price | For Whom | What They Get |
|------|-------|----------|---------------|
| Team Standard | ¥2,000/mo (~$280) | Small broker wealth teams | Full content push, WeCom bot, Mini Program, 5 seats |
| Team Pro | ¥5,000/mo (~$700) | Mid-size securities firm teams | + meeting prep, client segmentation, draft messages, 15 seats |
| Enterprise | Custom | Large institutions | + API, compliance log, CRM integration, bilingual, SLA, unlimited seats |

### B2C Tiers (secondary, later)

| Tier | Price | For Whom | What They Get |
|------|-------|----------|---------------|
| Free | ¥0 | Anyone | 公众号 articles, delayed commentary |
| Standard | ¥49/mo (~$7) | Active investors | Real-time alerts, Mini Program dashboard, archive, VIP group |
| Premium | ¥199/mo (~$28) | Serious self-directed | + private Q&A chat, deep analysis, priority alerts, full history |

### Revenue Math

- 5 Team Standard clients = ¥10,000/mo → covers all infrastructure + API costs
- 10 Team Standard clients = ¥20,000/mo → meaningful revenue for a solo/small team
- B2C is gravy on top, not the foundation

---

## Regulatory Positioning

**What we are:** Macro information service and workflow tool for licensed financial professionals. We provide data aggregation, analysis, and communication automation. We do not provide personalized investment advice to the public.

**What we are not:** Securities investment consulting firm, public investment advisor, or tip-selling service.

**Key compliance principles:**

- B2B enterprise positioning (internal tool for licensed teams) avoids public-facing AI service requirements under the Interim Measures for Generative AI Services
- All content framed as macro analysis and information, not buy/sell recommendations
- Disclaimers on all published content
- Compliance/audit logging for institutional clients
- No public stock-tipping or portfolio recommendations
- If regulated advisory needed in future: partner with licensed institution, don't apply for own license (CSRC currently not accepting new applications)

---

## Cost Structure (Year 1 MVP)

```
INFRASTRUCTURE
  Contabo VPS Singapore (or Alibaba Cloud HK)    $120–300/year
  Domain + DNS                                      $20/year
  WeChat Official Account verification             ¥300/year (~$42)

DATA SOURCES
  FRED, BLS, BEA, Fed RSS, ECB RSS                  FREE
  Finnhub, Alpha Vantage, Google News RSS            FREE
  yfinance, CFTC data                                FREE

LLM API
  Anthropic Claude (English analysis)           $300–800/year
  Chinese LLM (DeepSeek/Qwen for CN generation) $200–500/year

TOTAL YEAR 1:                                  ~$1,000–1,700/year
```

Note: for serving Chinese clients, you may need a Chinese LLM (DeepSeek, Qwen, or similar) for high-quality Chinese language generation, supplemented by Claude for English-language macro analysis and reasoning. Or use Claude for reasoning and translate/localize as a post-processing step.

---

## Build Sequence

### Phase 1: Prove the Brain (Month 1–2)

Build the Analyst agent. Wire up FRED + Fed RSS + economic calendar + cross-asset prices + PBOC/NBS sources. Generate daily 早盘速递 and 数据快评 in Chinese. Publish to a WeChat Official Account. Get 200+ followers reading daily.

**Success metric:** Financial professionals screenshot and forward your notes in their client groups.

### Phase 2: Add the Conversation (Month 2–3)

Build the Sales agent as a WeCom/WeChat chat bot. Let users ask macro questions and get contextualized answers. Add meeting prep capability ("今晚FOMC，帮我准备一下明早客户沟通要点").

**Success metric:** Daily returning users asking questions, not just passive readers.

### Phase 3: First Paying Teams (Month 3–5)

Approach 3–5 small/mid securities firm wealth teams. Offer pilot access. Build Mini Program with regime dashboard and research archive. Add client segmentation and alert routing.

**Success metric:** 3+ paying B2B clients.

### Phase 4: Build the Track Record (Month 4–8)

Deploy Trader agent internally (crypto, for company alignment). Record regime calls systematically. Publish monthly "calls vs market" scorecard on the Official Account to build credibility.

**Success metric:** 6+ months of documented regime call accuracy.

### Phase 5: Scale B2B (Month 6–12)

Compliance logging. Team workspaces. CRM integration. Bilingual output. API access. Approach larger institutions. Rednote content for brand building and inbound leads.

**Success metric:** 10+ paying B2B clients, revenue covering full operating costs.

### Phase 6: Layer on B2C (Month 9–12+)

Launch paid B2C tiers. Premium Q&A. Deeper Mini Program features. Consider mobile app. Expand Rednote presence for user acquisition.

**Success metric:** 200+ paying individual subscribers.

---

## Company Alignment

The company builds crypto quantfin agents for trading. Analyst sits upstream:

```
Analyst Platform
  → regime scores, macro intelligence (API)
    → company's crypto trading agents consume signals
      → auto-adjust strategy/risk based on macro context
        → better risk-adjusted returns
```

Analyst's core engine is domain-independent. The company's trading agents are crypto execution. Clean separation, mutual value. The external product (serving Chinese financial teams) and the internal integration (feeding the company's quant system) run on the same engine.

---

## Competitive Moat

Five dimensions that compound over time:

1. **WeChat-native distribution** — Built where China's financial professionals already work, not forcing them to a new app. This is a distribution moat, not a technology moat.

2. **Regime state history** — After 12 months, a verifiable timestamped record of macro calls in Chinese. No competitor has this. Impossible to retroactively fabricate.

3. **Client memory** — The Sales agent accumulates per-client context: what they trade, what they ask about, what language they prefer. Switching to a competitor means losing this personalized experience.

4. **Speed in Chinese** — Flash commentary in native Chinese within minutes of a US data release. The human analyst at CICC or CITIC is still drafting. Analyst publishes first.

5. **B2B workflow lock-in** — Once a wealth team builds their daily client communication around Analyst's output, switching costs are high. It's embedded in their workflow, their WeCom, their client groups.

---

## Summary

| Question | Answer |
|----------|--------|
| What is it? | WeChat-native macro intelligence platform with chat, push, dashboard, and API |
| What position? | Macro strategist + client-service copilot, not public stock-advice bot |
| What services? | Flash notes, daily briefing, Q&A, meeting prep, watchlist alerts, archive, API |
| Best first customers? | Licensed financial teams (securities firms, wealth teams, private banks) |
| Second customers? | Private funds, family offices, corporate treasury |
| Third customers? | Serious self-directed investors (lower-touch, later) |
| Primary platform? | WeChat/WeCom (product) + Mini Program (dashboard) |
| Secondary platform? | Rednote (discovery and brand only) |
| Revenue model? | B2B team subscriptions first (¥2,000–5,000/mo), B2C subscriptions later (¥49–199/mo) |
| Regulatory stance? | Macro intelligence + workflow tool for licensed teams, not public investment advice |
