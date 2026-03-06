# Analyst — Workstream Execution Plan

Status note on March 6, 2026:
This document is still the target-state workstream plan. For the current implemented status inside `analyst-project/`, see `00-overview/Implementation_Status.md`.

## Critical Strategic Update (from Marketing Research)

Before reading the workstream plan, internalize these five findings. They change the product shape significantly.

**Finding 1: Start as internal copilot, not public-facing bot.**
A vendor-operated bot that appears to "be the adviser" to end clients is materially riskier than an internal copilot used by licensed staff. Brokers themselves split channels this way — advisers serve signed clients via real-name Enterprise WeChat, not public groups. CSRC IT rules state that third-party IT service institutions must not participate in any link of customer-facing business service. Our product helps the RM draft, prep, and research — the RM decides what goes to the client.

**Finding 2: Competition exists, but not at our layer.**
Wind AI briefing, Eastmoney 妙想/Choice, 同花顺 HithinkGPT, and 招商证券天启大模型 are all real. But they are generic AI research/stock analysis tools. No dominant product owns the "WeCom-native macro copilot for brokerage RMs" position. The whitespace is the workflow layer, not "AI finance."

**Finding 3: B2B procurement is heavier than assumed.**
If the tool touches official client communication channels, expect compliance, IT review, archiving requirements, and possibly multi-month procurement cycles. BOCI's Enterprise WeChat archiving procurement took 3 months from announcement to award. However, a drafting-only productivity copilot for internal use may move faster — it doesn't touch the official client channel directly.

**Finding 4: "Internal tool" helps on CAC side, but doesn't erase all risk.**
CAC generative-AI rules carve out enterprise/internal use not offered to the public. But CSRC says editing/integrating securities research and republishing for profit counts as investment consulting. The safe zone: macro intelligence + internal drafting + meeting prep for licensed staff. The danger zone: specific stock recommendations + bot appearing to be the adviser + public-facing content without disclaimers.

**Finding 5: First clients come from network or don't come at all.**
No web research can answer this. A 48-hour network audit across the entire team is mandatory.

---

## Revised Product Shape

Based on these findings, the MVP is NOT "WeChat 公众号 publishing macro articles to the public." It is:

```
WHAT WE ARE:
  A WeCom-based internal macro copilot for licensed financial teams.
  
  The RM opens WeCom → asks "今晚CPI数据怎么解读，帮我准备一段给客户的话" 
  → gets a draft in 10 seconds → reviews/edits → sends to client themselves.
  
  We never touch the client directly. The licensed human is always in the loop.

WHAT WE ARE NOT:
  A public-facing AI that sends macro advice to investors.
  A bot that replaces the adviser in client conversations.
  A 公众号 giving stock recommendations.
```

This changes the workstream plan in important ways.

---

## Workstream 1: Macro Engine (Engineering)

**Owner:** Technical founder
**Timeline:** Month 1–2
**Dependencies:** None — fully independent

### What to Build

The engine is unchanged from the previous plan. It produces macro analysis. It doesn't know or care who consumes it.

**Month 1 deliverables:**

Data pipeline on VPS:
- FRED API + Fed/ECB/BOJ RSS + calendar scraper (Investing.com/ForexFactory) + yfinance for cross-asset prices
- PBOC/NBS scraper for China-specific data (LPR, RRR, PMI, GDP)
- Xinhua/Caixin RSS for China policy news
- Unified event schema, stored in SQLite
- Scheduled: 30min market prices, 1hr calendar, 4hr central banks, daily FRED

Analyst agent producing output:
- 数据快评 (flash commentary) — triggered by high-importance data releases
- 早盘速递 (pre-market briefing) — scheduled 7:00am CST
- 收盘点评 (after-market wrap) — scheduled 4:30pm CST
- Regime state JSON — updated on every significant event
- Output format: Chinese markdown + structured JSON
- Saved to local files and simple HTTP endpoint

**Month 2 deliverables:**

Sales agent (Q&A capability):
- Takes question string + client context → returns Chinese answer
- Pure function: text in, text out
- No platform integration yet
- Add: meeting prep mode ("帮我准备明早客户沟通要点")
- Add: draft message mode ("帮我写一段关于今晚非农数据的客户消息")

Quality tuning:
- Collect 20+ real CICC/CITIC/Huatai/GF morning notes
- Compare engine output side-by-side
- Iterate system prompts until indistinguishable in quality
- Test Chinese LLM options: DeepSeek vs Qwen vs Claude+translation
- This is the single most important engineering work

**Definition of done:** Print the engine's 早盘速递 and show it to a financial professional without telling them it's AI-generated. If they believe a human analyst wrote it, the engine is ready.

---

## Workstream 2: Delivery Shell (Engineering/Product)

**Owner:** Technical founder or front-end contractor
**Timeline:** Month 1–2
**Dependencies:** None — fully independent from Workstream 1

### Critical Change: WeCom-First, Not 公众号-First

The marketing research changes the build order. The public 公众号 is secondary. WeCom is primary because:

- It's the channel where RM-client service already happens at brokers
- Internal tool positioning is regulatory safer
- Tencent Cloud documents publishing agents into WeCom
- Brokers like BOCI already use WeCom for official advisory

**Month 1 deliverables:**

WeCom integration:
- Register WeCom developer account
- Build bot that receives messages and returns responses
- Test message types: text, markdown, mini-program card links
- Understand WeCom API: message limits, group vs 1-on-1, archiving compatibility
- Build with placeholder responses (engine not connected yet)

WeChat Official Account (secondary):
- Register and verify (this takes time, start early)
- Design article templates for 早盘速递 and 数据快评
- Manual publishing capability (auto-publish comes in integration phase)
- Purpose: brand building and B2C funnel for later, not the core product

**Month 2 deliverables:**

WeCom copilot features:
- Chat Q&A: user asks macro question → get answer
- Draft mode: "帮我写一段给客户的CPI解读" → get editable draft
- Meeting prep: "明早要跟客户聊美联储，帮我准备要点" → get talking points
- All responses include disclaimer: "此内容由AI辅助生成，请审核后使用"

Mini Program (basic):
- Regime dashboard (visual scores from engine JSON)
- Research archive (past briefings, searchable)
- Today's calendar with engine's pre-event view
- Keep simple — this is a reference tool, not the core interaction

**Definition of done:** A person on WeCom can type a macro question and get a useful, Chinese-language response within 15 seconds. They can also request a client message draft and get editable text.

---

## Workstream 3: Customer Discovery (Marketing)

**Owner:** Marketing teammate
**Timeline:** Week 1–4 (starts immediately, runs parallel)
**Dependencies:** None — zero product needed

### This Workstream Is the Highest Priority

The marketing teammate's research has already answered questions #2, #3, and #4 at a directional level. What remains is fieldwork that only human conversations can provide.

**Week 1–2: Interviews + Network Audit**

5+ Interviews (non-negotiable):
- 3+ RMs or wealth advisors at securities firms
- 1+ compliance or quality-control reviewer at a broker
- 1+ broker-tech or WeCom vendor contact

Interview questions for RMs:
- Walk me through your morning routine — what do you read before market open?
- How many clients do you message every day? What channels?
- When a big macro event happens (CPI, FOMC), how do you write commentary for clients?
- How long does it take you to write a client message after a data release?
- Do you use Wind? Choice? 同花顺? Internal research? 公众号? All of the above?
- If something could draft the first version of your client message, would you trust it enough to send after editing?
- What's the one thing that wastes the most time in your daily workflow?

Interview questions for compliance:
- If an RM uses an AI tool to draft client commentary and then reviews/edits before sending, does that trigger a compliance review?
- What's the difference (from compliance perspective) between an RM writing their own summary of a research report vs an AI writing it?
- Are there specific words, phrases, or content types that would flag a review?
- If this tool runs inside WeCom and all outputs are archived, does that satisfy your archiving requirements?
- What would make you say "no" to this tool?

Interview questions for broker-tech/WeCom vendor:
- How are securities firms currently deploying WeCom bots?
- What's the typical procurement cycle for a WeCom-integrated tool?
- Which firms are most progressive on AI tooling?
- What compliance/IT requirements do they impose on third-party WeCom integrations?
- Any firms you know that are actively looking for macro/research AI tools?

48-hour Network Audit (do this in parallel with scheduling interviews):
- Every team member writes down every first-degree connection to: securities firms, wealth management teams, compliance officers, broker IT, WeCom vendors, private fund managers, family office contacts
- Be specific: name, firm, role, relationship strength (close friend vs met once)
- Output: a spreadsheet with columns: Name, Firm, Role, Connection Strength, Who Knows Them
- This list determines whether B2B is viable in the next 3 months

**Week 2–3: Competitive Deep Dive**

Subscribe to and study:
- Wind AI briefing feature — what exactly does it push, how good is it?
- Eastmoney 妙想 — test the AI assistant, document capabilities and gaps
- 同花顺 HithinkGPT / i问财 — test the Q&A, understand what it does well and poorly
- Top 5 macro analyst 公众号 (find out which ones RMs actually follow in interviews)
- Any WeCom-native financial tools already in market

Document for each:
- What it does
- What it doesn't do (the gap)
- Price
- Quality of macro analysis specifically
- Whether it serves the RM workflow or just the end investor

**Week 3–4: Synthesis**

Produce a 2-page document:

Page 1 — Customer Profile:
- Confirmed daily workflow of target RM
- Confirmed pain points (ranked by severity)
- Confirmed content format preferences
- Confirmed willingness to use AI-drafted content (with what caveats)
- Confirmed procurement process and timeline
- Confirmed compliance boundaries

Page 2 — Go-to-Market Readiness:
- List of 3–5 potential pilot firms (from network audit)
- Strength of connection to each (warm intro vs cold)
- Estimated timeline to pilot
- Recommended pilot offer (free trial length, scope, success criteria)
- Key objection we'll face and how to handle it
- Competitive positioning: "Unlike Wind/妙想/同花顺, we focus on [specific gap]"

**Definition of done:** You can answer with confidence: "Our first customer is [specific firm type], they need [specific workflow improvement], they can buy [this way], and we have warm intros to [these 3 firms]." If you can't answer this, do more interviews.

---

## Workstream 4: Integration (Engineering + Product)

**Owner:** Technical founder
**Timeline:** Month 2–3
**Dependencies:** Needs Workstream 1 (engine) + Workstream 2 (shell) minimally working

### Connect Engine to Delivery

Engine → WeCom pipeline:
- WeCom bot receives user message
- Route to appropriate agent mode:
  - General macro question → Sales agent Q&A
  - "帮我准备/帮我写" → Sales agent draft mode
  - "今天有什么数据" → Calendar lookup from engine
  - "现在宏观怎么看" → Regime state summary
- Response sent back to WeCom within 15 seconds
- All interactions logged (compliance-ready)
- Per-user context memory (remembers what they trade, what they've asked before)

Engine → 公众号 pipeline (secondary):
- Daily auto-format and publish: 早盘速递, 收盘点评
- Event-driven publish: 数据快评 on major releases
- Markdown → WeChat article format with proper styling
- Review queue: optionally hold for human review before publish

Engine → Mini Program:
- API endpoint: current regime scores (JSON)
- API endpoint: article archive with search
- API endpoint: today's calendar with engine's view
- WebSocket or polling for real-time score updates

### Adapt Based on Workstream 3 Findings

This is where customer discovery directly shapes the product:

If interviews reveal RMs mainly need draft messages:
→ Prioritize the "draft client commentary" flow
→ Make it the default WeCom interaction mode
→ Add templates: post-CPI template, post-FOMC template, post-PBOC template

If interviews reveal RMs mainly need morning briefing:
→ Prioritize scheduled push: auto-send 早盘速递 summary to WeCom at 7:30am
→ Make it scannable in 30 seconds (not a full article)
→ Add "一句话总结" (one-sentence summary) at the top

If interviews reveal compliance is the main blocker:
→ Add prominent disclaimer on every output
→ Add compliance log: every generated message archived with timestamp
→ Add "this is a draft — please review before sending" framing on everything
→ Build the audit trail before building features

If interviews reveal procurement is too slow for B2B:
→ Flip to B2C first
→ Accelerate 公众号 content as primary surface
→ Target serious self-directed investors via Rednote → WeChat funnel
→ Revisit B2B after building brand credibility

**Definition of done:** The end-to-end product works: engine produces analysis → WeCom delivers it interactively → user can ask questions, get drafts, see regime scores. A non-technical RM can use it in their daily workflow without any technical setup.

---

## Workstream 5: Go-to-Market (Marketing + Founder)

**Owner:** Marketing teammate + technical founder
**Timeline:** Month 3–5
**Dependencies:** Needs Workstream 1-4 (working product) + Workstream 3 (identified customers)

### The Strategic Frame

The marketing research revealed a crucial insight: **the procurement weight depends on where the tool sits in the workflow.** This creates two distinct GTM paths:

```
PATH A: "Internal Productivity Copilot"              PATH B: "Client Communication Platform"
(lighter procurement, faster sales)                    (heavier procurement, longer cycle)
                                                      
Tool helps RM draft/prep/research internally          Tool integrates into client-facing WeCom
RM reviews and sends content themselves               Tool sends content to clients via WeCom
Does not touch official client channels               Touches official archiving/compliance systems
                                                      
Procurement: team lead can trial and expense          Procurement: IT + compliance + procurement
Timeline: weeks                                       Timeline: months
Price: ¥1,000–3,000/mo per team                      Price: ¥5,000–20,000/mo per department
Compliance: minimal (internal productivity tool)       Compliance: heavy (broker channel rules apply)
                                                      
START HERE ←                                          GROW INTO THIS LATER →
```

**Start with Path A. Grow into Path B after building trust and track record.**

### Phase 1: Seed Users (Month 3, Week 1–2)

**Goal:** Get the product into the hands of 5–10 individual RMs for daily use. Not a formal enterprise sale — just people using it.

Approach — "Personal tool" positioning:
- Reach out to RM contacts from the network audit
- Pitch: "I built a tool that drafts your morning client messages in 10 seconds. Want to try it for free?"
- They install WeCom (or use their existing WeCom), add our bot, start using it
- No formal procurement needed — it's a personal productivity tool, like using ChatGPT but for macro
- This is how Notion, Figma, and every modern SaaS entered enterprises: bottom-up through individual users

What to provide:
- WeCom bot access (invite link)
- 60-second tutorial: "Type any macro question or say '帮我写' to get a client draft"
- Daily push: 早盘速递 summary at 7:30am via WeCom message
- No contract, no payment, no procurement — pure value delivery

What to track:
- Daily active usage (how many messages per user per day)
- Most common question types (Q&A vs draft vs meeting prep)
- Quality feedback (ask every Friday: "Was this week's output useful? What was wrong?")
- Forwarding behavior: do they actually send the drafts to clients?

### Phase 2: Validate Value (Month 3, Week 3 – Month 4)

**Goal:** Prove the tool saves time and improves quality. Collect evidence.

Daily feedback loop:
- Each morning after 早盘速递 publishes, message 3 seed users: "今天的早盘有用吗？缺什么？"
- After each major data release (CPI, NFP, FOMC): "快评及时吗？内容准确吗？你发给客户了吗？"
- Weekly: 15-minute call with 2 users — deeper feedback on workflow fit

Measure:
- Time saved: "Before Analyst, how long did it take you to write morning commentary? Now?"
- Quality perception: "Compared to your firm's internal research, how does Analyst's output rank?"
- Usage stickiness: are they using it every day, or did they try once and forget?
- Trust signal: are they sending AI-drafted content to clients (even after editing)?

Kill criteria (be honest):
- If < 3 of 10 seed users are active after 2 weeks → the product doesn't fit the workflow. Go back to interviews.
- If users say "the macro analysis is wrong/shallow" → the engine needs more tuning before GTM.
- If users say "I can't send AI content to clients, compliance won't allow it" → pivot to pure internal research tool, remove draft-for-client feature.

### Phase 3: Convert to Paid (Month 4–5)

**Goal:** Convert seed users into paying teams. First revenue.

Conversion approach:
- To active seed users: "You've been using this for 4 weeks. Would your team want access? We're offering team plans at ¥1,500/month for the first 3 pilot teams."
- The seed user becomes your internal champion — they sell it to their team lead
- Offer: 3-month pilot at discounted rate, cancel anytime
- Include: team WeCom bot access (up to 10 users), daily push, Q&A, draft mode, Mini Program dashboard

Pricing (Path A — internal productivity copilot):

| Tier | Price | What They Get |
|------|-------|---------------|
| Individual | ¥199/mo | WeCom bot access, daily briefing, Q&A, draft mode |
| Team (≤10) | ¥1,500/mo | Team bot, shared archive, calendar, regime dashboard |
| Team (≤30) | ¥3,000/mo | + priority alerts, meeting prep, custom watchlists |

Do NOT launch with enterprise/compliance/archiving features yet. Those are Path B. Start light.

Formal pilot agreement (keep it simple):
- 1-page agreement: scope, duration, pricing, cancellation terms
- No SLA, no uptime guarantee, no compliance certification
- Frame as "early access pilot" — expectations are lower, feedback is expected
- Include: "All content is AI-assisted and should be reviewed by licensed professionals before external use"

### Phase 4: Build the Evidence Base (Month 4–6)

**Goal:** Create the assets that make the next 20 sales easier.

Track record:
- Start publishing monthly "Analyst regime calls vs market outcomes" scorecard
- Post on 公众号 and Rednote — builds credibility for both B2B and future B2C
- Example: "我们在2月28日CPI发布前标注风险偏好降至0.35（6个月最低），随后A股下跌2.3%"

Case study (even anonymized):
- "A 10-person wealth team at a mid-size securities firm reduced morning prep time from 45 minutes to 10 minutes using Analyst"
- Document: before/after workflow, time saved, quality perception, user quotes
- This becomes the sales deck for the next wave

公众号 content flywheel:
- Publish daily 早盘速递 and event-driven 快评
- Purpose: brand building, SEO, credibility
- Track: reads, shares, new followers
- Quality > frequency — one sharp 快评 shared 500+ times is worth more than daily mediocre content

Rednote presence (low effort, high ROI):
- 2–3 posts per week
- Format: visual macro explainer cards ("一张图看懂本周美联储")
- Purpose: top-of-funnel → "关注我们公众号获取每日宏观简报"
- Test and scale what works; kill what doesn't

### Phase 5: Expand B2B (Month 6–9)

**Goal:** Move from pilot to systematic B2B sales. Begin Path B preparation.

Scale what works:
- If seed users converted → replicate the playbook at 5–10 more firms
- Each paying team lead becomes a referral source: "你有认识的同行需要吗？"
- Financial industry in China is relationship-dense — referrals compound

Begin Path B preparation (if demand signals justify):
- Build compliance logging (every AI-generated message archived with timestamp)
- Build audit trail (who generated what, when, what was edited before sending)
- Build disclaimer system (auto-append compliance language to every output)
- Explore: WeCom message archiving compatibility (this is what BOCI procured for ¥570K)
- Begin conversations with broker compliance teams about formal evaluation
- Expect: 3–6 month procurement cycle for formal institutional deployment

Pricing upgrade for Path B:

| Tier | Price | What They Get |
|------|-------|---------------|
| Department | ¥8,000/mo | Path A + compliance log, audit trail, archiving compatibility |
| Enterprise | Custom | + API, CRM integration, bilingual, SLA, custom coverage scope |

Target: Path B conversations start in month 6, first Path B contract closes month 9–12.

### Phase 6: Layer B2C (Month 9+)

**Goal:** Use brand credibility from B2B to launch consumer subscriptions.

Only start this after:
- 公众号 has 5,000+ organic followers from daily content
- Track record has 6+ months of documented regime calls
- B2B pilots prove the analysis quality is institutional-grade
- Legal review confirms B2C positioning is safe (macro information, not advice)

B2C pricing:

| Tier | Price | What They Get |
|------|-------|---------------|
| Free | ¥0 | 公众号 articles (delayed), weekly summary |
| Standard | ¥49/mo | Real-time alerts, Mini Program, archive, VIP WeChat group |
| Premium | ¥199/mo | + private Q&A, deep analysis, priority alerts, full history |

Distribution:
- 公众号 → free tier conversion
- Rednote → 公众号 → free tier → paid conversion
- Word of mouth from B2B users who share content personally

---

## Updated Timeline View

```
           WK1-2      WK3-4      MONTH 2    MONTH 3    MONTH 4-5   MONTH 6-9
           ────────   ────────   ────────   ────────   ─────────   ─────────

WS1        Build      Chinese    Sales      Tune       Iterate     Expand
Engine     pipeline   quality    agent      based on   based on    coverage
           + analyst  tuning     Q&A +      seed user  paid user
           agent                 draft mode feedback   feedback

WS2        Register   WeCom      Mini       Auto-push  Compliance  Path B
Shell      WeCom +    bot with   Program    pipeline   logging     features
           公众号      placeholder (basic)   working    (prep)

WS3        5 interviews          Synthesize Identify   Referral    Path B
Discovery  + network   Competitive findings  pilot     mapping     compliance
           audit       deep dive            firms                  conversations

WS4                              Connect    Full       Adapt to    Scale
Integrate                        engine ↔   end-to-end WS3
                                 WeCom      working    findings

WS5                                         Seed       Convert     Expand B2B
GTM                                         5-10 RMs   to paid     + prep B2C
                                            (free)     teams
```

---

## Decision Points

These are the moments where we either continue, pivot, or kill:

**Week 4 — After interviews + network audit:**
- If we have 0 warm intros to securities firms → pivot to B2C first (公众号 + Rednote)
- If compliance interviews reveal internal copilot is also risky → reconsider China positioning, possibly start with overseas Chinese market
- If RMs say "I don't need this, Wind already does it" → study Wind's AI feature deeply, find the specific gap or kill B2B

**Month 3 — After 2 weeks of seed usage:**
- If < 3/10 users are active daily → product-workflow fit is wrong, go back to interviews
- If users love the briefing but won't send drafts to clients → remove draft feature, focus on internal research
- If users ask for features we didn't plan → listen, those are the real product

**Month 5 — After paid conversion attempt:**
- If 0 teams convert to paid → pricing is wrong, value prop is wrong, or target customer is wrong
- If 3+ teams convert → double down, start referral engine
- If teams want to pay but procurement blocks them → this confirms Path A/B split, stay on Path A longer

---

## Summary

| Question | Previous Answer | Updated Answer |
|----------|----------------|----------------|
| What do we build first? | Public 公众号 + Telegram | WeCom internal copilot for licensed RMs |
| Who pays first? | Retail investors (¥49/mo) | Small teams of RMs (¥1,500/mo) |
| How do we sell? | Content marketing → conversion | Network intros → seed users → team conversion |
| Client-facing or internal? | Client-facing bot | Internal drafting tool (RM reviews before sending) |
| Compliance approach | Disclaimers on public content | Internal tool positioning + compliance logging |
| 公众号 role | Primary product surface | Brand building + B2C funnel (secondary) |
| Rednote role | Discovery channel | Top-of-funnel → 公众号 → eventually B2C |
| First revenue target | Month 3 (B2C subs) | Month 4–5 (B2B team pilots) |
| Path to enterprise | Not planned | Path A (copilot) → Path B (platform) → enterprise |

**The next move is not product design. It is five interviews and a 48-hour network audit.**
