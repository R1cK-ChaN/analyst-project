# WS3: Customer Discovery — Detailed Specification

Status note on March 6, 2026:
This document describes the target WS3 work. Current implementation status is tracked in `00-overview/Implementation_Status.md`.

## Owner: Marketing Teammate
## Timeline: Week 1–4 (starts immediately, runs parallel)
## Dependencies: None (zero product needed)

---

## This Is the Highest Priority Workstream

Nothing in WS1, WS2, WS4, or WS5 matters if we're building for the wrong customer or solving the wrong problem. Every design decision in the product is currently assumption-based. This workstream converts assumptions into facts.

---

## Week 1–2: Interviews + Network Audit

### Task A: Arrange and Conduct 5+ Interviews

**Target interviewees:**

| # | Role | Why | What We Learn |
|---|------|-----|---------------|
| 1-3 | RMs or wealth advisors at securities firms | They are the primary user | Daily workflow, pain points, content needs |
| 4 | Compliance or QC reviewer at a broker | They decide what can ship | What's allowed, what's blocked, what triggers review |
| 5 | Broker-tech or WeCom vendor contact | They know the procurement landscape | How firms buy tools, what's already deployed |

**Interview script for RMs / Wealth Advisors:**

```
WARM-UP (2 min)
"感谢你抽时间聊。我在做一个宏观研究相关的项目，想了解一下你的日常工作流程。
没有标准答案，我就是想听听你的真实体验。"

DAILY WORKFLOW (10 min)
1. "每天早上开盘前，你一般做什么准备工作？"
   Follow-up: "大概花多长时间？"

2. "你从哪些渠道获取宏观信息？"
   Probe: Wind? Choice? 公众号? 内部研报? 同事分享? 
   Follow-up: "哪个渠道你觉得最有用？为什么？"

3. "你每天大概给多少个客户发消息？通过什么渠道？"
   Probe: 企业微信? 普通微信? 电话? 
   Follow-up: "发的内容主要是什么？自己写还是转发？"

CLIENT COMMUNICATION (10 min)
4. "当一个重要数据出来（比如美国CPI、非农），你怎么跟客户沟通？"
   Follow-up: "从数据公布到你发出评论，大概多长时间？"
   Follow-up: "你觉得这个过程中最花时间的是什么？"

5. "你有没有模板或固定格式？还是每次都重新写？"

6. "如果有一个工具能在数据公布后10秒内帮你生成一个初稿，
   你愿意用吗？你会直接发给客户还是先改一改？"
   Follow-up: "你觉得客户会在意是AI写的吗？"

TOOLS & PROCUREMENT (5 min)
7. "你们团队现在用什么工具辅助工作？"
   Probe: Wind AI? 妙想? 同花顺? 其他AI工具?

8. "如果要买一个新工具，流程是怎样的？"
   Probe: 你自己能决定? 还是要团队负责人/IT/合规审批?
   Follow-up: "大概要多久？"

9. "你觉得一个这样的工具值多少钱一个月？"

CLOSING (3 min)
10. "在你的日常工作中，如果有一件事能被自动化或简化，你最希望是什么？"

11. "你身边有没有同事或朋友也可能对这个感兴趣？能介绍认识吗？"
```

**Interview script for Compliance / QC Reviewer:**

```
1. "如果客户经理用AI工具起草宏观评论，然后自己审核修改后发给客户，
   这在合规层面需要走什么流程？"

2. "AI生成的内容和RM自己写的内容，在合规审查上有什么区别？"

3. "有什么特定的词汇、表述或内容类型会触发合规审查？"
   Probe: "建议买入"? 具体股票代码? 收益预测?

4. "如果这个工具运行在企业微信内部，所有输出都有归档记录，
   这是否满足你们的合规要求？"

5. "什么情况下你会说'这个工具不能用'？红线在哪里？"

6. "你们目前对RM的微信/企微沟通内容有什么监管要求？"
```

**Interview script for Broker-Tech / WeCom Vendor:**

```
1. "证券公司目前是怎么部署企业微信机器人的？常见的用途是什么？"

2. "一个企微集成的工具，典型的采购周期是多长？要过哪些关？"

3. "哪些券商在AI工具方面比较积极？"

4. "对第三方企微集成工具，券商一般有什么IT和合规要求？"

5. "你知道有券商在主动寻找宏观/研究类AI工具吗？"
```

### Task B: 48-Hour Network Audit

**Every team member fills out this spreadsheet within 48 hours:**

```
| Name | Firm | Role | Connection Type | Who On Our Team Knows Them | Notes |
|------|------|------|-----------------|---------------------------|-------|
|      |      | RM / Wealth Advisor / Compliance / IT / Management |
|      |      | Close friend / Former colleague / Met at event / Friend of friend |
```

**Target firm types:**

```
PRIORITY 1: Mid-size securities firms' wealth teams
├── These are most likely to adopt — big enough to have budget,
│   small enough to not have strong in-house macro coverage
├── Examples: 国元证券, 东兴证券, 西部证券, 长城证券, 国联证券
└── Also: 东方证券, 兴业证券 wealth divisions

PRIORITY 2: Large firm wealth/sales teams (harder to enter, but bigger prize)
├── CICC 中金, CITIC 中信, Huatai 华泰, GF 广发, Haitong 海通
└── Approach individual RMs, not the institution

PRIORITY 3: Private banks and IFAs
├── 招行私行, 工行私行, 建行私行 — wealth advisor teams
└── Independent financial advisors who lack research support

PRIORITY 4: WeCom vendors and broker-tech contacts
├── Anyone who sells tools to securities firms
└── They know who's buying and what gaps exist
```

**Output of network audit:** A ranked list of potential pilot firms with warm intro paths. If this list is empty or weak, the B2B strategy needs to change.

---

## Week 2–3: Competitive Deep Dive

### Subscribe to and Test These Products

```
PRODUCT                 WHAT TO TEST                              COST
──────────────────────────────────────────────────────────────────────
Wind AI 万得AI          AI briefing feature, push to WeChat        Need Wind subscription
Eastmoney 妙想/Choice   AI research assistant, Q&A capabilities    Free trial available
同花顺 HithinkGPT       i问财 Q&A, stock analysis                  Free tier available
招商证券天启大模型       If accessible externally                    May be internal only
Top 5 macro 公众号      Content quality, format, engagement         Free (subscribe)
```

**For each competitor, document:**

```
1. WHAT IT DOES
   - Core features (list them)
   - Content types (briefing? Q&A? analysis?)
   - Asset coverage (A-shares only? Global?)
   - Macro depth (surface-level or institutional quality?)

2. WHAT IT DOESN'T DO (THE GAP)
   - Does it draft client-ready messages? (probably not)
   - Does it do meeting prep? (probably not)
   - Does it live inside WeCom as an interactive copilot? (probably not)
   - Does it maintain a persistent regime state? (probably not)
   - Does it personalize by user? (probably not)

3. QUALITY ASSESSMENT
   - Print their macro output
   - Print our engine's output (from WS1)
   - Compare side by side
   - Where are we better? Where are they better?

4. PRICING AND DISTRIBUTION
   - How much does it cost?
   - How do users access it? (app? web? WeChat? WeCom?)
   - What's the adoption like? (user reviews, download numbers)

5. POSITIONING OPPORTUNITY
   - Given gaps #2, what's our wedge?
   - Draft: "Unlike [competitor], Analyst focuses on [specific gap]"
```

### Find Top 5 Macro 公众号 That RMs Actually Follow

Ask in every interview: "你关注哪些宏观类的公众号？"

Then subscribe and study:
- Format: long article? Short card? Visual? Text-heavy?
- Frequency: daily? Weekly? Event-driven?
- Tone: academic? Conversational? Opinionated?
- Engagement: read counts, likes, shares
- What makes people forward their articles?

These are your real competitors for attention. Study them closely.

---

## Week 3–4: Synthesis

### Deliverable 1: Customer Profile (1 page)

```
TARGET USER: [role, firm type, daily workflow summary]
CONFIRMED PAIN POINTS (ranked):
  1. [biggest time sink in their daily workflow]
  2. [second biggest]
  3. [third]
CURRENT TOOLS: [what they use today and satisfaction level]
AI READINESS: [would they use AI-drafted content? With what caveats?]
PROCUREMENT: [how they buy tools, who approves, typical timeline]
PRICING SENSITIVITY: [what they said about willingness to pay]
CONTENT PREFERENCES: [format, length, tone, frequency]
KEY QUOTES: [2-3 direct quotes from interviews that capture the need]
```

### Deliverable 2: Go-to-Market Readiness (1 page)

```
PILOT CANDIDATES: [3-5 firms with warm intro paths]
  Firm A: [name, connection, strength, estimated timeline]
  Firm B: [name, connection, strength, estimated timeline]
  ...
RECOMMENDED PILOT OFFER: [free trial? discounted? duration?]
KEY OBJECTION: [what pushback we'll face and how to handle it]
COMPETITIVE POSITIONING: "Unlike [X], we focus on [Y]"
COMPLIANCE FINDING: [what is allowed, what is not, where is the line]
CHANNEL FINDING: [WeCom confirmed? Which mode? Group or 1-on-1?]
KILL SIGNAL: [what finding would make us stop or pivot]
```

### Deliverable 3: Updated Recommendations

Based on findings, recommend adjustments to:
- WS1: should the engine output format change? Different content types needed?
- WS2: WeCom confirmed as primary? Any delivery changes needed?
- WS5: B2B still viable? Pricing adjustment? Different target firm type?

---

## Decision Point (End of Week 4)

| Finding | Action |
|---------|--------|
| 3+ warm intros, RMs confirm pain, compliance allows copilot | Continue B2B as planned |
| Warm intros exist but compliance blocks internal copilot | Reposition as pure research content (公众号 only) |
| Zero warm intros to securities firms | Pivot to B2C first (公众号 + Rednote) or overseas Chinese market |
| RMs say "Wind AI already does this well enough" | Study Wind's gap deeply or kill B2B positioning |
| RMs say "I'd use this every day" with enthusiasm | Accelerate — move to seed users immediately |

---

## Definition of Done

You can confidently answer all of these:

1. Who exactly is our customer? (role, firm type, specific names)
2. What is their #1 daily pain point that we solve?
3. Would they use AI-drafted content for client communication? (yes/no/with what conditions)
4. How do they buy tools and how long does it take?
5. Who are we competing against and what's our specific wedge?
6. Do we have warm intros to 3+ potential pilot firms?
7. What does compliance say is allowed vs not allowed?
8. Should we continue as planned, pivot, or kill?
