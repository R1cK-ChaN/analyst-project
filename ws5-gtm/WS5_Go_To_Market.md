# WS5: Go-to-Market — Detailed Specification

Status note on March 6, 2026:
This document describes the target WS5 work. Current implementation status is tracked in `00-overview/Implementation_Status.md`.

## Owner: Marketing Teammate + Technical Founder
## Timeline: Month 3–6+
## Dependencies: WS1-4 (working product) + WS3 (identified customers)

---

## Strategic Frame

Two go-to-market paths, built sequentially:

```
PATH A: "Internal Productivity Copilot"         PATH B: "Client Communication Platform"
(start here)                                     (grow into later)

Tool helps RM draft/prep/research internally     Tool integrates into client-facing WeCom
RM reviews and sends content themselves           Compliance logging, archiving, audit trail
Does not touch official client channels           Touches official systems

Procurement: team lead can trial and expense     Procurement: IT + compliance + procurement
Timeline: weeks                                  Timeline: months
Price: ¥1,000–3,000/mo per team                 Price: ¥5,000–20,000/mo per department
```

---

## Phase 1: Seed Users (Month 3, Week 1–2)

### Goal
Get 5–10 individual RMs using the product daily. Not a formal enterprise sale — personal productivity tool adoption.

### How to Find Seed Users

```
SOURCE 1: Network audit results (from WS3)
├── Contact every warm intro directly
├── Message: "我做了一个宏观助手工具，能在数据发布后10秒帮你生成客户评论初稿。
│            你要不要试试？完全免费，就是想听听你的反馈。"
└── Target: 3-5 users from this source

SOURCE 2: Interview participants (from WS3)
├── Anyone who said "I'd use this" during interviews
├── They already understand the product — lowest friction
└── Target: 2-3 users from this source

SOURCE 3: Cold outreach (if network is thin)
├── Find active financial 公众号 authors who are also RMs
├── Comment on their posts, build relationship, then introduce tool
├── Slower but builds real relationships
└── Target: 2-3 users from this source
```

### What to Provide Seed Users

```
SETUP (5 minutes):
1. Add our WeCom bot as a contact (send invite link)
2. Bot sends welcome message with instructions
3. User tells bot their market focus (A股/港股/美股/全球)
4. Done — they can start using immediately

DAILY EXPERIENCE:
├── 7:30am: receive 早盘速递 push in WeCom
├── Anytime: type a macro question, get answer
├── Anytime: say "帮我写" to get a client draft
├── Evening: receive 快评 when US data drops
└── All free, no contract, no commitment
```

### What to Track

```
QUANTITATIVE (track automatically):
├── Daily active users (DAU)
├── Messages per user per day
├── Mode breakdown (Q&A vs draft vs prep vs regime vs calendar)
├── Response satisfaction (if user sends 👍/👎)
├── Time of day usage patterns
└── Most common question topics

QUALITATIVE (ask manually):
├── Friday check-in: "这周的内容有用吗？哪里可以改进？"
├── After major events: "今晚CPI快评及时吗？准确吗？你发给客户了吗？"
├── Weekly: 15-min call with 2 users for deeper feedback
└── Ask specifically: "你有没有用我们生成的内容发给客户？改了多少？"
```

### Kill Criteria (Be Honest)

```
AFTER 2 WEEKS:
├── < 3 of 10 users active daily    → Product doesn't fit workflow. Back to WS3.
├── Users say "analysis is shallow"  → Engine quality issue. Back to WS1 tuning.
├── Users say "can't trust AI"       → Trust issue. Add more human-in-loop features.
├── Users say "Wind already does it" → Differentiation issue. Study Wind gap deeper.
└── 5+ users active daily            → CONTINUE. Move to Phase 2.
```

---

## Phase 2: Validate Value (Month 3 Week 3 – Month 4)

### Goal
Prove the tool saves time and improves quality. Collect hard evidence.

### Metrics to Prove

```
TIME SAVED:
├── Before: "How long did it take you to write morning commentary?"
├── After:  "How long does it take now (with Analyst generating first draft)?"
├── Target: 50%+ time reduction (e.g., 45 min → 15 min)
└── Document as: "Analyst节省了RM每天30分钟的宏观准备时间"

QUALITY PERCEPTION:
├── Ask: "Compared to your firm's internal research, how does Analyst rank?"
│   Scale: 1-5 (1=much worse, 5=much better)
├── Target: average 3.5+ (comparable or better)
└── Document specific quality wins: "Analyst的CPI快评比我们内部研报快了2小时"

TRUST / ADOPTION:
├── Ask: "Did you send Analyst-generated content to a client this week?"
├── If yes: "How much did you edit before sending?"
├── Track editing rate: heavy edit (rewrote >50%) vs light edit (<20%) vs sent as-is
└── Target: majority light edit or sent as-is

STICKINESS:
├── Week-over-week retention: % of users active week 2 who are still active week 4
├── Target: 60%+ retention
└── Users who drop off: ask why (critical feedback)
```

### Weekly Feedback Loop

```
MONDAY: Review weekend/overnight coverage quality
WEDNESDAY: Check mid-week engagement metrics
FRIDAY: Send feedback survey to all seed users (2 questions max)
  Q1: "本周Analyst内容最有用的是什么？" (open text)
  Q2: "最需要改进的是什么？" (open text)
```

---

## Phase 3: Convert to Paid (Month 4–5)

### Goal
Convert seed users into paying teams. First revenue.

### Conversion Script

```
TO ACTIVE SEED USERS (individually, via WeCom):

"[Name]，你用Analyst已经[X]周了。
从使用数据看，你平均每天用[Y]次，最常用的是[mode: 写客户评论/早盘速递/Q&A]。

我们正在开放团队版，你觉得你们团队其他[RM/同事]会用吗？

团队版（最多10人）首批优惠价：¥1,500/月
包含：早盘速递推送 + 快评推送 + Q&A + 客户评论起草 + 沟通准备 + 宏观仪表盘

前3个团队享受3个月试用价，不满意随时取消。

你觉得怎么样？"
```

### Pricing (Path A)

```
INDIVIDUAL (for seed users who want to keep personal access):
├── Price: ¥199/月
├── Includes: WeCom bot, daily push, Q&A, draft mode, Mini Program
└── Positioning: "coffee money for a personal macro strategist"

TEAM STANDARD (≤10 seats):
├── Price: ¥1,500/月 (launch price, normally ¥2,000)
├── Includes: everything Individual + shared archive + team calendar
└── Positioning: "less than hiring one intern"

TEAM PRO (≤30 seats):
├── Price: ¥3,000/月 (launch price, normally ¥5,000)
├── Includes: everything Standard + meeting prep + client segmentation + priority alerts
└── Positioning: "replaces one junior macro analyst's workload"
```

### Pilot Agreement (Keep Simple)

```
ONE PAGE:
├── Scope: WeCom-based macro intelligence copilot for internal use
├── Duration: 3 months initial pilot
├── Pricing: ¥X/month, billed monthly
├── Cancellation: cancel anytime with 7 days notice
├── Data: all AI-generated content for internal reference only
├── Disclaimer: "AI辅助生成内容，不构成投资建议，使用前请自行审核"
├── No SLA, no uptime guarantee (pilot expectations)
└── Mutual NDA (if they request)
```

---

## Phase 4: Build Evidence (Month 4–6)

### Track Record (Most Powerful Marketing Asset)

```
START RECORDING FROM DAY ONE:
├── Every regime state update: timestamp + scores + trigger event
├── Every flash commentary: what we said + what happened after
├── Monthly scorecard:
│   ├── "我们在3月5日CPI前标注风险偏好降至0.35"
│   ├── "随后48小时内，A股下跌1.8%，港股下跌2.1%"
│   └── "Analyst体系状态的前瞻性指示得到验证"
└── Publish monthly on 公众号: "Analyst月度复盘"
```

### Case Study Template

```
TITLE: "[Firm type] 如何用Analyst节省每天30分钟的宏观准备时间"

BEFORE (pain):
├── RM每天花45分钟阅读研报、准备客户评论
├── 重要数据发布后2-3小时才能完成客户沟通
└── 团队10个RM写的评论质量参差不齐

AFTER (with Analyst):
├── 早盘准备时间从45分钟缩短到15分钟
├── 数据快评在发布后5分钟内推送到团队
├── 团队基于同一份专业底稿各自修改，质量更统一

USER QUOTE:
"[Name/anonymized], [Title], [Firm type]"
"Analyst的早盘速递帮我省了很多时间，特别是在美国数据发布的晚上，
我现在可以在10分钟内准备好给客户的评论。"
```

---

## Phase 5: Scale B2B (Month 6–9)

### Referral Engine

```
EVERY PAYING CLIENT:
├── Monthly check-in: "使用体验如何？有什么建议？"
├── If satisfied: "你有认识的同行也需要这样的工具吗？推荐成功双方各优惠一个月"
├── Financial industry in China is relationship-dense
└── 1 happy client → 2-3 warm intros
```

### Outbound (if referrals alone aren't enough)

```
TARGET: wealth team leads at mid-size securities firms
CHANNEL: LinkedIn (领英) / WeCom direct / conference networking
MESSAGE: "我们帮助[similar firm]的财富团队把每天宏观准备时间从45分钟减少到15分钟。
         每天早上7:30自动推送专业级宏观简报，数据发布后5分钟内生成客户评论初稿。
         有兴趣了解一下吗？"
ASSET: case study + monthly track record scorecard
```

### Path B Preparation (parallel)

```
IF 5+ paying B2B clients and demand signals for deeper integration:
├── Build compliance logging (audit trail)
├── Build content review queue (compliance officer approval flow)
├── Build role-based access (RM / team lead / compliance / admin)
├── Explore WeCom message archiving compatibility
├── Begin conversations with broker compliance teams
├── Prepare for formal procurement process
└── Expect 3-6 month cycle for first Path B deal
```

---

## Phase 6: Layer B2C (Month 9+)

### Prerequisites

```
ONLY START B2C WHEN:
├── 公众号 has 5,000+ organic followers
├── Track record has 6+ months of documented regime calls
├── B2B pilots prove analysis quality is institutional-grade
├── Legal review confirms B2C positioning is safe
└── Engine is stable and doesn't need daily babysitting
```

### B2C Launch Plan

```
ACQUISITION:
├── 公众号 daily content → free tier conversion
├── Rednote thought leadership → 公众号 → free tier → paid
├── Word of mouth from B2B users who share content personally
└── Targeted 投放 on WeChat/Rednote if ROI justifies

PRICING:
├── Free: 公众号 articles (delayed), weekly summary
├── ¥49/月 Standard: real-time alerts, Mini Program, archive, VIP群
├── ¥199/月 Premium: private Q&A, deep analysis, priority alerts, full history
```

### Rednote Strategy (Top-of-Funnel Only)

```
CONTENT TYPES (test which performs best):
├── 图文卡片: "3分钟看懂今天的非农数据" (infographic cards)
├── 轮播图: "一张图理解美联储点阵图" (carousel format)
├── 短文: "为什么CPI超预期对A股投资者很重要" (short article)
└── Every post ends with: "关注我们公众号获取每日宏观简报"

FREQUENCY: 2-3 posts per week
GOAL: build followers, test formats, drive 公众号 conversion
METRIC: 收藏(saves) and 分享(shares) matter more than 点赞(likes)
DO NOT: try to monetize on Rednote directly
```

---

## Revenue Milestones

```
MONTH 3:   First seed users (free)
MONTH 4:   First revenue (1-2 individual ¥199/mo)
MONTH 5:   First team (1 team at ¥1,500/mo)
MONTH 6:   ¥5,000/mo revenue (covers all costs)
MONTH 9:   ¥15,000-20,000/mo revenue (3-5 teams + individuals)
MONTH 12:  ¥30,000-50,000/mo (5-10 teams + B2C starting)
```

---

## Decision Points

| When | Question | If Yes | If No |
|------|----------|--------|-------|
| Month 3, Week 2 | 3+ seed users active daily? | Continue to Phase 2 | Go back to WS3, re-interview |
| Month 4 | Seed users confirm time saved? | Continue to Phase 3 | Engine quality issue, back to WS1 |
| Month 5 | 2+ teams converted to paid? | Scale B2B | Wrong pricing, wrong customer, or wrong value prop |
| Month 6 | 5+ paying clients? | Begin Path B prep | Stay on Path A, expand laterally |
| Month 9 | Revenue covers costs? | Layer B2C | Focus on B2B unit economics first |

---

## Definition of Done (WS5 Phase 1-3)

1. 5+ seed users acquired and onboarded
2. 3+ seed users active daily after 2 weeks
3. Documented evidence: time saved, quality perception, trust level
4. 2+ teams converted to paid subscriptions
5. Case study written (even anonymized)
6. Monthly track record scorecard published
7. Referral pipeline producing warm intros to next wave of clients
