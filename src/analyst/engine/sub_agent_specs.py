from __future__ import annotations

import logging
from typing import Any

from .agent_loop import AgentLoopConfig
from .live_types import AgentTool, LLMProvider
from .sub_agent import SubAgentSpec, build_sub_agent_tool

logger = logging.getLogger(__name__)


def build_research_sub_agents(
    parent_tools: list[AgentTool],
    provider: LLMProvider,
    store: Any | None = None,
) -> list[AgentTool]:
    """Build sub-agent tools for the Research agent (LiveAnalystEngine)."""
    by_name = {t.name: t for t in parent_tools}

    specs = [
        SubAgentSpec(
            name="data_deep_dive",
            description=(
                "Investigate a specific macro indicator or data release in depth. "
                "Returns a concise analytical summary with historical context and surprise patterns."
            ),
            system_prompt=(
                "You are a macro data analyst sub-agent. Given an indicator or data release:\n"
                "1. Gather historical data and recent releases\n"
                "2. Analyze surprise patterns and trends\n"
                "3. Produce a concise analytical summary (max 300 words)\n"
                "Be factual. Cite specific numbers. Do not speculate beyond the data.\n"
                "Reply in the same language as the task."
            ),
            tools=_pick(by_name, [
                "get_indicator_history", "get_indicator_trend", "get_surprise_summary",
                "get_recent_releases", "get_today_calendar",
            ]),
            config=AgentLoopConfig(max_turns=3, max_tokens=1200, temperature=0.2),
        ),
        SubAgentSpec(
            name="market_scanner",
            description=(
                "Scan current cross-asset market conditions: prices, volatility regime, "
                "rates, and live news. Returns a structured market snapshot summary."
            ),
            system_prompt=(
                "You are a cross-asset market scanner sub-agent. Given a scanning task:\n"
                "1. Check current market prices and movements\n"
                "2. Assess volatility regime and rate expectations\n"
                "3. Note any breaking news or significant moves\n"
                "4. Produce a concise market conditions summary (max 300 words)\n"
                "Focus on what moved and why. Be specific with numbers.\n"
                "Reply in the same language as the task."
            ),
            tools=_pick(by_name, [
                "get_market_snapshot", "get_vix_regime", "fetch_reference_rates",
                "fetch_rate_expectations", "fetch_live_markets", "fetch_live_news",
            ]),
            config=AgentLoopConfig(max_turns=3, max_tokens=1200, temperature=0.2),
        ),
        SubAgentSpec(
            name="news_researcher",
            description=(
                "Deep-dive research on a specific news topic. Searches multiple sources, "
                "fetches articles, and synthesizes findings into a comprehensive briefing."
            ),
            system_prompt=(
                "You are a news research sub-agent. Given a topic:\n"
                "1. Search for relevant recent news across sources\n"
                "2. Fetch and read key articles for detail\n"
                "3. Synthesize findings into a clear briefing (max 400 words)\n"
                "Distinguish facts from speculation. Note conflicting reports.\n"
                "Reply in the same language as the task."
            ),
            tools=_pick(by_name, [
                "web_search", "web_fetch_page", "fetch_live_news",
                "fetch_article", "search_news", "get_recent_news",
            ]),
            config=AgentLoopConfig(max_turns=4, max_tokens=1500, temperature=0.2),
        ),
    ]

    return [build_sub_agent_tool(spec, provider, store, parent_agent="research") for spec in specs]


def build_sales_sub_agents(
    parent_tools: list[AgentTool],
    provider: LLMProvider,
    store: Any | None = None,
) -> list[AgentTool]:
    """Build sub-agent tools for the Sales agent (Telegram bot)."""
    by_name = {t.name: t for t in parent_tools}

    specs = [
        SubAgentSpec(
            name="research_lookup",
            description=(
                "Look up macro/market information to answer a client question. "
                "Returns a factual summary with relevant data points."
            ),
            system_prompt=(
                "You are a research lookup sub-agent for the sales team. Given a question:\n"
                "1. Gather relevant market data, macro indicators, and news\n"
                "2. Focus on what the client needs to know\n"
                "3. Produce a clear, factual summary (max 250 words)\n"
                "Be specific with numbers. Avoid jargon.\n"
                "Reply in the same language as the task."
            ),
            tools=_pick(by_name, [
                "fetch_live_markets", "fetch_live_news", "fetch_article",
                "fetch_country_indicators", "fetch_reference_rates",
                "get_regime_summary", "get_calendar", "web_search",
            ]),
            config=AgentLoopConfig(max_turns=3, max_tokens=1200, temperature=0.3),
        ),
        SubAgentSpec(
            name="portfolio_analyst",
            description=(
                "Analyze client portfolio risk, holdings, and volatility exposure. "
                "Returns a risk assessment with key metrics."
            ),
            system_prompt=(
                "You are a portfolio analysis sub-agent. Given a portfolio task:\n"
                "1. Check portfolio holdings and risk metrics\n"
                "2. Assess volatility regime implications\n"
                "3. Produce a concise risk summary (max 200 words)\n"
                "Focus on actionable risk insights.\n"
                "Reply in the same language as the task."
            ),
            tools=_pick(by_name, [
                "get_portfolio_risk", "get_portfolio_holdings",
                "get_vix_regime", "sync_portfolio_from_broker",
            ]),
            config=AgentLoopConfig(max_turns=3, max_tokens=1000, temperature=0.2),
        ),
    ]

    return [build_sub_agent_tool(spec, provider, store, parent_agent="sales") for spec in specs]


def build_content_sub_agents(
    provider: LLMProvider,
    store: Any | None = None,
) -> list[AgentTool]:
    """Build sub-agent tools for the Professional Content agent (OpenRouterAgentRuntime)."""
    # Content sub-agents need their own tool instances since there's no parent tool list
    from analyst.tools import (
        build_country_indicators_tool,
        build_live_markets_tool,
        build_live_news_tool,
        build_rate_expectations_tool,
        build_reference_rates_tool,
        build_vix_regime_tool,
        build_web_fetch_tool,
        build_web_search_tool,
        build_article_tool,
    )

    fact_checker_tools = [
        build_live_markets_tool(),
        build_reference_rates_tool(),
        build_rate_expectations_tool(),
        build_country_indicators_tool(),
        build_vix_regime_tool(),
    ]

    content_researcher_tools = [
        build_web_search_tool(),
        build_web_fetch_tool(),
        build_live_news_tool(),
        build_article_tool(),
        build_live_markets_tool(),
    ]

    specs = [
        SubAgentSpec(
            name="fact_checker",
            description=(
                "Verify claims and fetch real-time data to enrich professional content. "
                "Returns verified data points and corrections."
            ),
            system_prompt=(
                "You are a fact-checking sub-agent for professional content. Given a claim or topic:\n"
                "1. Fetch current market data and macro indicators\n"
                "2. Verify or correct any specific claims\n"
                "3. Return verified data points (max 200 words)\n"
                "Only state what the data shows. Flag any discrepancies.\n"
                "Reply in the same language as the task."
            ),
            tools=fact_checker_tools,
            config=AgentLoopConfig(max_turns=3, max_tokens=1000, temperature=0.1),
        ),
        SubAgentSpec(
            name="content_researcher",
            description=(
                "Fetch additional market and macro context for richer professional content generation. "
                "Returns supplementary research material."
            ),
            system_prompt=(
                "You are a content research sub-agent. Given a topic:\n"
                "1. Search for relevant news and market context\n"
                "2. Fetch supporting data and quotes\n"
                "3. Return a research brief (max 300 words)\n"
                "Provide material that enriches content, not a finished draft.\n"
                "Reply in the same language as the task."
            ),
            tools=content_researcher_tools,
            config=AgentLoopConfig(max_turns=3, max_tokens=1200, temperature=0.2),
        ),
    ]

    return [build_sub_agent_tool(spec, provider, store, parent_agent="content") for spec in specs]


def _pick(by_name: dict[str, AgentTool], names: list[str]) -> list[AgentTool]:
    """Pick a subset of tools by name, logging warnings for missing ones."""
    missing = [n for n in names if n not in by_name]
    if missing:
        logger.warning("Sub-agent _pick: missing tools %s (available: %s)", missing, list(by_name))
    return [by_name[n] for n in names if n in by_name]
