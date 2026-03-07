# WS1: Macro Engine — Detailed Specification

Status note on March 7, 2026:
Month 1 scope (data pipeline + analyst agent) is implemented and merged to main. The live engine path is in `src/analyst/engine/`, `src/analyst/storage/`, and `src/analyst/ingestion/`. Live OpenRouter/FRED execution has been tested locally with mocks; end-to-end network verification is pending. For full implementation status, see `00-overview/Implementation_Status.md`.

## Owner: Technical Founder
## Timeline: Month 1–2
## Dependencies: None (fully independent)

---

## What This Workstream Delivers

The macro engine is the brain of Analyst. It ingests data from free sources, processes it through LLM agents, and produces structured output in Chinese. It has zero knowledge of delivery channels — it writes to files and an API endpoint. WS2 (delivery) and WS4 (integration) handle getting the output to users.

---

## Month 1: Data Pipeline + Analyst Agent

### Week 1-2: Data Pipeline

**Goal:** All free data sources ingesting on schedule, stored in SQLite, unified schema.

```
Data Source              Frequency        Implementation
──────────────────────────────────────────────────────────
FRED API                 Daily 6am CST    scrapers/fred_client.py
BLS RSS                  On publish       feedparser, check hourly
BEA RSS                  On publish       feedparser, check hourly
Fed speeches RSS         Every 4 hours    scrapers/fed_scraper.py
Fed press releases RSS   Every 4 hours    scrapers/fed_scraper.py
ECB/BOJ/BOE RSS          Every 4 hours    feedparser
Investing.com calendar   Every 1 hour     scrapers/investing_calendar.py
ForexFactory calendar    Every 1 hour     scrapers/investing_calendar.py
yfinance prices          Every 30 min     scrapers/market_scraper.py
Finnhub news             Every 30 min     finnhub-python (free key)
Alpha Vantage news       Every 1 hour     requests (free key)
Google News RSS          Every 1 hour     feedparser (custom macro feeds)
PBOC announcements       Every 2 hours    custom scraper (pboc.gov.cn)
NBS China data           Daily            custom scraper (stats.gov.cn)
Xinhua finance RSS       Every 1 hour     feedparser
```

**China-specific sources (add to code-toolkit):**

```python
# PBOC / NBS / China sources to add

CHINA_SOURCES = {
    "pboc_announcements": "http://www.pbc.gov.cn/rss/zhengcehuobisi.xml",
    "pboc_stats": "http://www.pbc.gov.cn/rss/tongjihuobisi.xml",
    "xinhua_finance": "http://www.news.cn/fortune/news_fortune.xml",
    "china_state_council": "http://www.gov.cn/rss/guowuyuan.xml",
}

# NBS (National Bureau of Statistics) - must scrape, no RSS
# Key indicators: PMI, GDP, CPI, Industrial Production, Retail Sales
NBS_CALENDAR = {
    "PMI": {"day": "last_day_of_month", "time": "09:00 CST"},
    "CPI": {"day": "~10th", "time": "09:30 CST"},
    "GDP": {"day": "quarterly ~15th", "time": "10:00 CST"},
}
```

**Unified event schema (all sources normalize to this):**

```json
{
    "timestamp": "2026-03-05T14:30:00Z",
    "source": "fred",
    "type": "economic_release",
    "category": "inflation",
    "country": "US",
    "indicator": "CPI_YOY",
    "actual": 3.4,
    "forecast": 3.2,
    "previous": 3.1,
    "surprise": 0.2,
    "importance": "high",
    "raw_json": {}
}
```

**Deliverables:**
- All scrapers running on cron schedule on Contabo VPS
- SQLite database with tables: calendar_events, market_prices, central_bank_comms, indicators
- `python main.py --once` fetches all data successfully
- `python main.py --schedule` runs continuously

### Week 3-4: Analyst Agent

**Goal:** Agent produces flash commentary (数据快评) and daily briefings (早盘速递) in Chinese at institutional quality.

**Analyst Agent system prompt:**

```
你是一位顶级投资银行的高级宏观研究策略师。

你的分析风格：
- 先说核心结论，再解释数据
- 每个数据都要和当前市场叙事联系起来（市场在交易什么故事？）
- 解释数据为什么重要，而不仅仅是数据是什么
- 分析跨资产影响（CPI超预期对债券、美元、股市、加密货币分别意味着什么？）
- 指出什么会改变你的观点（什么数据会颠覆当前叙事？）
- 要具体量化（"这是10月以来最大的偏差"而不是"超预期"）
- 跟踪累积证据（"这是连续第三次超预期"而不只是"超预期"）

你的输出语言：中文（简体）
你的目标读者：中国的证券公司财富管理团队、客户经理、基金经理
你需要把全球宏观事件和中国投资者关心的问题联系起来
```

**Three output modes:**

Mode 1 — 数据快评 (Flash Commentary):
- Triggered when: high-importance data releases (CPI, NFP, FOMC, PMI, PBOC)
- Input: event data + context (recent surprises, market snapshot, Fed comms, regime state)
- Output: 300-500 word Chinese commentary + regime state update if warranted
- Latency target: < 60 seconds from data release to output ready
- Format: markdown with sections (一句话总结 / 核心数据 / 为什么重要 / 跨资产影响 / 接下来关注)

Mode 2 — 早盘速递 (Morning Briefing):
- Triggered: scheduled, 7:00am CST every trading day
- Input: overnight events, market moves, today's calendar, recent Fed comms, regime state
- Output: 500-800 word Chinese briefing
- Format: markdown with sections (一句话总结 / 隔夜要点 / 今日关注 / 跨资产状态 / 体系评估)

Mode 3 — 收盘点评 (After-Market Wrap):
- Triggered: scheduled, 4:30pm CST on trading days (or 10pm CST for US session wrap)
- Input: day's market moves, any data released, regime changes
- Output: 200-400 word Chinese summary
- Format: shorter, more concise than morning briefing

**Regime state schema:**

```json
{
    "risk_appetite": 0.35,
    "fed_hawkishness": 0.78,
    "growth_momentum": 0.55,
    "inflation_trend": "disinflation_stalling",
    "liquidity_conditions": "tightening",
    "dominant_narrative": "软着陆叙事承压，市场定价2次降息但数据指向0-1次",
    "narrative_risk": "若下次CPI再超预期，可能触发再加速恐慌",
    "regime_label": "risk_off",
    "confidence": 0.72,
    "cross_asset_implications": {
        "rates": "利率higher for longer，10Y向4.8%靠拢",
        "dollar": "美元偏强，DXY在105上方有支撑",
        "a_shares": "外资流出压力，关注北向资金动态",
        "hk_stocks": "港股受美债利率压制，科技股承压",
        "us_equities": "估值压缩风险，价值优于成长",
        "commodities": "黄金受实际利率对冲支撑，原油区间震荡",
        "crypto": "风险回避压力，BTC横盘整理，山寨币跑输"
    },
    "key_themes": [
        "sticky_services_inflation",
        "labor_market_resilience",
        "global_liquidity_divergence",
        "china_stimulus_effectiveness",
        "boj_normalization_spillovers"
    ],
    "last_updated": "2026-03-05T15:00:00Z",
    "trigger": "美国CPI连续第三次超预期"
}
```

**LLM choice decision (test during Week 3-4):**

```
Option A: Claude for reasoning → translate to Chinese
├── Pro: strongest macro reasoning ability
├── Con: translation step adds latency and may lose nuance
└── Test: generate English analysis, then translate with DeepSeek/Qwen

Option B: DeepSeek-V3 or Qwen-2.5 for Chinese-native generation
├── Pro: native Chinese, no translation needed, cheaper
├── Con: may have weaker macro reasoning than Claude
└── Test: give same context, compare output quality to real CICC notes

Option C: Claude for reasoning + structured output → Chinese LLM for final prose
├── Pro: best reasoning + best Chinese writing
├── Con: two API calls, higher latency and cost
└── Test: Claude outputs structured bullet points, Chinese LLM expands into prose

Recommendation: Test all three in Week 3. Pick based on quality, not speed.
The output must read like it was written by a native Chinese macro analyst.
```

**Quality benchmark:**
- Collect 20+ real morning notes from CICC (中金), CITIC (中信), Huatai (华泰), GF (广发)
- Print engine output and real notes side by side
- Can a financial professional tell which is AI? If yes → keep tuning
- Focus areas: terminology accuracy (宏观术语), narrative flow, cross-asset logic

---

## Month 2: Sales Agent + Quality Tuning

### Week 5-6: Sales Agent

**Goal:** Agent that answers macro questions, drafts client messages, and preps meeting talking points — all in Chinese.

**Sales Agent system prompt:**

```
你是一位证券公司的高级宏观策略师助理。

你的角色：
- 帮助客户经理（RM）回答宏观问题
- 帮助RM起草给客户的宏观评论
- 帮助RM准备客户沟通要点
- 用清晰、专业但不过于学术的中文回答

你的规则：
- 永远不要给出具体的股票/基金买卖建议
- 永远不要说"建议买入/卖出某某股票"
- 你提供的是宏观环境分析和框架，不是投资建议
- 每条回复末尾必须附带免责声明
- 如果用户要求起草客户消息，明确标注"这是AI草稿，请审核后使用"
- 记住用户之前的问题和偏好，提供个性化回答

你可以使用的数据：
- Analyst引擎的宏观体系状态
- 最新的经济数据和日历
- 最近的央行通讯
- 跨资产市场快照
- 你不能访问任何交易持仓或策略参数
```

**Input/Output contract:**

```python
# Sales Agent interface — pure function, no platform dependency

class SalesAgent:
    async def answer_question(
        self, 
        question: str,           # User's question in Chinese
        user_context: dict,      # {firm, role, asset_focus, history}
        research_store: dict,    # Latest analyst output + regime state
        market_state: dict       # Current prices, calendar
    ) -> str:
        """Returns Chinese answer + disclaimer"""
    
    async def generate_draft(
        self,
        request: str,            # "帮我写一段CPI点评给客户"
        user_context: dict,
        research_store: dict,
        client_type: str         # "conservative" / "moderate" / "aggressive"
    ) -> str:
        """Returns client-appropriate draft + draft disclaimer"""
    
    async def generate_meeting_prep(
        self,
        topic: str,              # "美联储决议" / "非农数据"
        user_context: dict,
        research_store: dict
    ) -> str:
        """Returns structured talking points + disclaimer"""
```

### Week 7-8: Quality Tuning + China Localization

**Goal:** Output quality matches real sell-side notes. China-specific macro covered properly.

**Tuning checklist:**

```
TERMINOLOGY:
├── 美联储 not 联邦储备  (use common Chinese financial terms)
├── 非农就业 not 非农业就业人口
├── 降息/加息 not 降低/提高利率
├── 北向资金 (northbound capital) — must use for A-share context
├── LPR, MLF, RRR — PBOC terms must be accurate
└── Review with a Chinese finance professional

CHINA-SPECIFIC CONTEXT:
├── Every US data release → explain relevance to A-shares and HK stocks
├── PBOC/NBS data → primary coverage, not afterthought
├── RMB/CNY movements → always noted in cross-asset implications
├── China policy signals → State Council, NPC, PBOC statements
├── Tariff/trade war → bilateral US-China framing
└── Timezone awareness: US data drops 8:30pm-10pm Beijing time

TONE:
├── Professional but accessible (not academic)
├── Opinionated (have a view, don't hedge everything)
├── Concise (RMs read on mobile, keep it scannable)
├── No emojis except in structured sections (📊📅🔴🟡)
└── Compare to CICC 中金公司 style — authoritative but readable

OUTPUT FORMAT:
├── Short paragraphs (2-3 sentences max)
├── Bold key numbers and conclusions
├── Use Chinese punctuation correctly（，。、）
├── Section headers with ▎prefix for visual scanning
└── One-sentence summary (一句话总结) always at the top
```

---

## Engine Output Endpoints

The engine exposes these to WS4 (integration layer):

```python
# Engine output API — consumed by WS4 integration

class EngineAPI:
    # ── Content generation ──
    async def get_morning_briefing() -> dict:
        """Returns {content_md: str, regime: dict, calendar: list}"""
    
    async def get_flash_commentary(event: dict) -> dict:
        """Returns {content_md: str, regime_update: dict|None}"""
    
    async def get_market_wrap() -> dict:
        """Returns {content_md: str}"""
    
    # ── Sales agent ──
    async def answer_question(question: str, user_ctx: dict) -> str:
    async def generate_draft(request: str, user_ctx: dict) -> str:
    async def generate_meeting_prep(topic: str, user_ctx: dict) -> str:
    
    # ── Data queries ──
    async def get_regime_state() -> dict:
    async def get_today_calendar() -> list:
    async def get_market_snapshot() -> dict:
    async def get_recent_events(days: int) -> list:
    async def search_archive(query: str) -> list:
```

---

## Definition of Done

1. Data pipeline: all sources ingesting on schedule, stored in SQLite
2. Analyst agent: produces 早盘速递 in Chinese that reads like a real sell-side note
3. Analyst agent: produces 数据快评 within 60 seconds of a data release
4. Regime state: updates correctly based on cumulative evidence
5. Sales agent: answers macro questions in natural Chinese
6. Sales agent: generates client-appropriate drafts with disclaimer
7. Sales agent: produces structured meeting prep talking points
8. Quality: a Chinese financial professional cannot reliably distinguish engine output from real CICC/CITIC notes
9. All output exposed via simple Python API for WS4 to consume
