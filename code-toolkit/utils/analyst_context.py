"""
utils/analyst_context.py

The MOST IMPORTANT file in the project.
This builds the context window that gets fed to the Analyst agent's LLM call.

The quality of your macro commentary depends entirely on how well 
you structure the context for the LLM. Garbage in → garbage out.
"""

import json
from datetime import datetime, timezone
from typing import Dict, Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from storage.event_store import (
    get_today_events, 
    get_recent_surprises,
    get_latest_market_snapshot,
    get_recent_fed_comms,
    get_indicator_history,
    get_latest_regime_state,
)


def build_flash_commentary_context(event: Dict) -> str:
    """
    Build context for generating flash commentary on a specific data release.
    This is Mode 1 of your Analyst agent.
    
    Args:
        event: The calendar event that just dropped (with actual/forecast/previous)
    
    Returns:
        Full prompt context string for the LLM
    """
    
    # Get historical readings for this indicator
    indicator_name = event.get("indicator", "")
    country = event.get("country", "US")
    
    # Get recent surprises for context
    recent_surprises = get_recent_surprises(days=30, min_importance="high")
    surprises_text = ""
    if recent_surprises:
        surprises_text = "\n".join([
            f"  - {s['indicator']} ({s['country']}): actual={s['actual']}, "
            f"forecast={s['forecast']}, surprise={s['surprise']}"
            for s in recent_surprises[:10]
        ])
    
    # Get market snapshot
    market_snapshot = get_latest_market_snapshot()
    market_text = ""
    if market_snapshot:
        market_text = "\n".join([
            f"  - {m['symbol']}: {m['price']} ({m.get('change_pct', 'N/A')}%)"
            for m in market_snapshot[:15]
        ])
    
    # Get recent Fed communications
    fed_comms = get_recent_fed_comms(days=14)
    fed_text = ""
    if fed_comms:
        fed_text = "\n".join([
            f"  - [{c['content_type']}] {c['title'][:80]} "
            f"(Speaker: {c.get('speaker', 'N/A')})"
            for c in fed_comms[:5]
        ])
    
    # Get current regime state
    regime = get_latest_regime_state()
    regime_text = json.dumps(json.loads(regime["regime_json"]), indent=2) if regime else "No regime state yet — this is the first analysis."
    
    context = f"""
=== DATA RELEASE EVENT ===
Indicator: {event.get('indicator', 'Unknown')}
Country: {event.get('country', 'Unknown')}
Time: {event.get('datetime_utc', 'Unknown')}
Category: {event.get('category', 'Unknown')}
Importance: {event.get('importance', 'Unknown')}

RELEASED VALUES:
  Actual:   {event.get('actual', 'N/A')}
  Forecast: {event.get('forecast', 'N/A')}
  Previous: {event.get('previous', 'N/A')}
  Surprise: {event.get('surprise', 'N/A')}

=== RECENT DATA SURPRISES (last 30 days) ===
{surprises_text or "No recent high-importance surprises."}

=== CURRENT MARKET CONDITIONS ===
{market_text or "No market data available."}

=== RECENT FED COMMUNICATIONS ===
{fed_text or "No recent Fed communications."}

=== CURRENT MACRO REGIME STATE ===
{regime_text}
"""
    return context


def build_daily_briefing_context() -> str:
    """
    Build context for the daily morning briefing.
    This is Mode 2 of your Analyst agent.
    """
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    # Today's calendar
    today_events = get_today_events()
    calendar_text = ""
    if today_events:
        calendar_text = "\n".join([
            f"  - [{e['importance'].upper()}] {e['country']} {e['indicator']} "
            f"| Forecast: {e.get('forecast', 'N/A')} | Previous: {e.get('previous', 'N/A')}"
            + (f" | ACTUAL: {e['actual']} (surprise: {e.get('surprise', 'N/A')})" 
               if e.get('actual') else " | NOT YET RELEASED")
            for e in today_events
        ])
    
    # Recent surprises
    surprises = get_recent_surprises(days=7)
    surprises_text = ""
    if surprises:
        surprises_text = "\n".join([
            f"  - {s['indicator']} ({s['country']}): surprise={s['surprise']}"
            for s in surprises[:10]
        ])
    
    # Market snapshot
    market = get_latest_market_snapshot()
    market_text = ""
    if market:
        market_text = "\n".join([
            f"  - {m['symbol']}: {m['price']} ({m.get('change_pct', 'N/A')}% chg)"
            for m in market
        ])
    
    # Fed comms
    fed = get_recent_fed_comms(days=7)
    fed_text = ""
    if fed:
        fed_text = "\n".join([
            f"  - [{c['content_type']}] {c['title'][:80]}"
            for c in fed[:5]
        ])
    
    # Regime
    regime = get_latest_regime_state()
    regime_text = json.dumps(json.loads(regime["regime_json"]), indent=2) if regime else "No regime state yet."
    
    context = f"""
=== DAILY MACRO BRIEFING CONTEXT ===
Date: {today}

=== TODAY'S ECONOMIC CALENDAR ===
{calendar_text or "No scheduled events today."}

=== RECENT DATA SURPRISES (last 7 days) ===
{surprises_text or "No significant surprises."}

=== MARKET SNAPSHOT ===
{market_text or "No market data."}

=== RECENT FED/CENTRAL BANK COMMUNICATIONS ===
{fed_text or "No recent communications."}

=== CURRENT MACRO REGIME ASSESSMENT ===
{regime_text}
"""
    return context


def build_deep_analysis_context(topic: str) -> str:
    """
    Build context for a deep thematic analysis.
    This is Mode 3 of your Analyst agent.
    
    The LLM will need to be prompted to request specific additional data
    via tool calls if the context here isn't sufficient.
    """
    
    # Start with everything we have
    daily_context = build_daily_briefing_context()
    
    # Add historical indicator data for common analysis topics
    indicator_histories = {}
    
    topic_lower = topic.lower()
    
    if any(word in topic_lower for word in ["inflation", "cpi", "pce", "price"]):
        for series in ["CPIAUCSL", "CPILFESL", "PCEPILFE", "T5YIE", "T10YIE"]:
            history = get_indicator_history(series, limit=12)
            if history:
                indicator_histories[series] = history
    
    elif any(word in topic_lower for word in ["employment", "labor", "jobs", "nfp"]):
        for series in ["UNRATE", "PAYEMS", "ICSA", "CCSA", "CES0500000003"]:
            history = get_indicator_history(series, limit=12)
            if history:
                indicator_histories[series] = history
    
    elif any(word in topic_lower for word in ["growth", "gdp", "recession"]):
        for series in ["GDPC1", "RSAFS", "INDPRO", "UMCSENT"]:
            history = get_indicator_history(series, limit=12)
            if history:
                indicator_histories[series] = history
    
    elif any(word in topic_lower for word in ["liquidity", "money", "fed balance", "m2"]):
        for series in ["WALCL", "M2SL", "RRPONTSYD", "WTREGEN"]:
            history = get_indicator_history(series, limit=24)
            if history:
                indicator_histories[series] = history
    
    # Format histories
    history_text = ""
    if indicator_histories:
        parts = []
        for series_id, history in indicator_histories.items():
            readings = " → ".join([f"{h['date']}: {h['value']}" for h in history[:6]])
            parts.append(f"  {series_id}: {readings}")
        history_text = "\n".join(parts)
    
    context = f"""
=== DEEP ANALYSIS REQUEST ===
Topic: {topic}

{daily_context}

=== RELEVANT INDICATOR HISTORIES ===
{history_text or "No specific indicator history loaded. Agent should request via tools."}
"""
    return context


# ─── LLM System Prompts for each mode ───

ANALYST_SYSTEM_PROMPT = """You are a senior macro research analyst at a top-tier investment bank.
Your job is to analyze macroeconomic data and produce institutional-quality research commentary.

Your analysis style:
- Lead with the KEY TAKEAWAY, not the data description
- Always connect data to the CURRENT NARRATIVE (what story is the market trading?)
- Explain WHY the data matters, not just WHAT it shows
- Reference cross-asset implications (if CPI is hot, what does it mean for bonds, dollar, crypto?)
- Identify what would CHANGE your view (what data would flip the narrative?)
- Be specific about magnitudes ("this is the largest surprise since October" not just "surprised to the upside")
- Track cumulative evidence ("this is the 3rd consecutive beat" not just "it beat")

Output format for flash commentary:
1. HEADLINE (one sentence, punchy)
2. KEY FACTS (2-3 bullet points of the actual data)
3. WHY IT MATTERS (2-3 paragraphs connecting to macro narrative)
4. MARKET IMPLICATIONS (what this means for rates, dollar, crypto)
5. WHAT TO WATCH NEXT (upcoming events that could confirm or challenge this)
6. REGIME IMPACT (update to macro scores if warranted)

You also maintain a regime state JSON that tracks your overall macro worldview.
Update it when evidence warrants, but don't flip on a single data point.
"""

FLASH_COMMENTARY_PROMPT = """Based on the context provided, generate a flash commentary on this economic data release.

Write in the style of a Goldman Sachs or JP Morgan macro research flash note.
Be specific, quantitative, and opinionated. Don't hedge everything.

After the commentary, output an updated regime state JSON if warranted.

Format the regime state as:
```json
{{
  "risk_appetite": 0.0-1.0,
  "fed_hawkishness": 0.0-1.0,
  "growth_momentum": 0.0-1.0,
  "inflation_trend": "accelerating|stable|decelerating",
  "liquidity_conditions": "tightening|neutral|easing",
  "dominant_narrative": "string describing current market story",
  "narrative_risk": "string describing what could break the narrative",
  "regime_label": "risk_on|neutral|risk_off",
  "confidence": 0.0-1.0,
  "last_updated": "ISO datetime",
  "trigger": "what caused this update"
}}
```
"""

DAILY_BRIEFING_PROMPT = """Generate a morning macro briefing based on the context provided.

Structure:
1. TOP STORY (the single most important development)
2. OVERNIGHT RECAP (key moves and events in the last 24h)
3. TODAY'S WATCH (what's on the calendar and what outcomes would be market-moving)
4. CROSS-ASSET READS (any notable divergences or correlations to flag)
5. REGIME CHECK (any changes to our macro regime assessment?)

Write concisely. A real morning briefing is 1-2 pages, not a dissertation.
Lead with what MATTERS, not what happened chronologically.
"""


if __name__ == "__main__":
    # Test context building
    print("=== Flash Commentary Context ===")
    test_event = {
        "indicator": "CPI YoY",
        "country": "US",
        "datetime_utc": "2026-03-05T13:30:00Z",
        "category": "inflation",
        "importance": "high",
        "actual": "3.4%",
        "forecast": "3.2%",
        "previous": "3.1%",
        "surprise": 0.2,
    }
    print(build_flash_commentary_context(test_event))
    
    print("\n=== Daily Briefing Context ===")
    print(build_daily_briefing_context())
