from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from analyst.agents import RoleDependencies, get_role_spec
from analyst.engine import OpenRouterAnalystEngine
from analyst.engine.live_types import AgentTool, LLMProvider
from analyst.mcp.shared_tools import BASE_SHARED_MCP_TOOL_NAMES
from analyst.storage import SQLiteEngineStore
from analyst.tools import (
    ToolKit,
    build_article_tool,
    build_country_indicators_tool,
    build_fed_comms_tool,
    build_image_gen_tool,
    build_indicator_history_tool,
    build_live_markets_tool,
    build_live_news_tool,
    build_optional_live_photo_tool,
    build_portfolio_holdings_tool,
    build_portfolio_risk_tool,
    build_portfolio_sync_tool,
    build_rate_expectations_tool,
    build_reference_rates_tool,
    build_research_search_tool,
    build_stored_news_tool,
    build_vix_regime_tool,
    build_web_fetch_tool,
    build_web_search_tool,
)
from analyst.tools._live_calendar import build_live_calendar_tool

CLAUDE_CODE_NATIVE_TOOL_NAMES = ("WebSearch", "WebFetch")
COMPANION_SHARED_MCP_TOOL_NAMES = (
    *BASE_SHARED_MCP_TOOL_NAMES,
    "fetch_live_calendar",
    "search_news",
    "get_fed_communications",
    "get_indicator_history",
    "search_research_notes",
)
USER_CHAT_SHARED_MCP_TOOL_NAMES = (
    *COMPANION_SHARED_MCP_TOOL_NAMES,
    "get_portfolio_risk",
    "get_portfolio_holdings",
)

RESEARCH_SUB_AGENT_PARENT_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "data_deep_dive": (
        "get_indicator_history",
        "get_indicator_trend",
        "get_surprise_summary",
        "get_recent_releases",
        "get_today_calendar",
    ),
    "market_scanner": (
        "get_market_snapshot",
        "get_vix_regime",
        "fetch_reference_rates",
        "fetch_rate_expectations",
        "fetch_live_markets",
        "fetch_live_news",
    ),
    "news_researcher": (
        "web_search",
        "web_fetch_page",
        "fetch_live_news",
        "fetch_article",
        "search_news",
        "get_recent_news",
    ),
}

USER_SUB_AGENT_PARENT_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "research_lookup": (
        "fetch_live_markets",
        "fetch_live_news",
        "fetch_article",
        "fetch_country_indicators",
        "fetch_reference_rates",
        "get_regime_summary",
        "get_calendar",
        "web_search",
    ),
    "portfolio_analyst": (
        "get_portfolio_risk",
        "get_portfolio_holdings",
        "get_vix_regime",
        "sync_portfolio_from_broker",
    ),
}

CONTENT_SUB_AGENT_TOOL_BUILDERS: dict[str, tuple[Callable[[], AgentTool], ...]] = {
    "fact_checker": (
        build_live_markets_tool,
        build_reference_rates_tool,
        build_rate_expectations_tool,
        build_country_indicators_tool,
        build_vix_regime_tool,
    ),
    "content_researcher": (
        build_web_search_tool,
        build_web_fetch_tool,
        build_live_news_tool,
        build_article_tool,
        build_live_markets_tool,
    ),
}


@dataclass(frozen=True)
class CapabilityBuildContext:
    engine: OpenRouterAnalystEngine | Any | None = None
    store: SQLiteEngineStore | None = None
    provider: LLMProvider | None = None


@dataclass(frozen=True)
class CapabilitySurfaceSpec:
    surface_id: str
    native_tool_names: tuple[str, ...] = ()
    shared_mcp_tool_names: tuple[str, ...] = ()
    sub_agent_names: tuple[str, ...] = ()
    build_tools: Callable[[CapabilityBuildContext], list[AgentTool]] = field(default=lambda _context: [])


def _build_companion_capabilities(context: CapabilityBuildContext) -> list[AgentTool]:
    return get_role_spec("companion").build_tools(
        RoleDependencies(store=context.store, provider=context.provider),
    )


def _build_user_chat_capabilities(context: CapabilityBuildContext) -> list[AgentTool]:
    engine = context.engine

    if engine is None:
        return _build_companion_capabilities(context)

    def get_regime(arguments: dict[str, object]) -> str:
        del arguments
        note = engine.get_regime_summary()
        return note.body_markdown

    def get_calendar(arguments: dict[str, object]) -> str:
        del arguments
        items = engine.get_calendar(limit=5)
        if not items:
            return "No upcoming calendar events."
        return "\n".join(
            f"- {item.indicator} ({item.country}) | "
            f"预期 {item.expected or '待定'} | 前值 {item.previous or '未知'} | {item.notes}"
            for item in items
        )

    def get_premarket(arguments: dict[str, object]) -> str:
        del arguments
        note = engine.build_premarket_briefing()
        return note.body_markdown

    kit = ToolKit()
    kit.add(build_web_search_tool())
    kit.add(build_web_fetch_tool())
    kit.add(build_image_gen_tool())
    live_photo_tool = build_optional_live_photo_tool()
    if live_photo_tool is not None:
        kit.add(live_photo_tool)
    kit.add(
        AgentTool(
            name="get_regime_summary",
            description="Fetch the current macro regime state including scores, key drivers, and market snapshot.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_regime,
        )
    )
    kit.add(
        AgentTool(
            name="get_calendar",
            description="Fetch upcoming economic data releases from local cache. For live/real-time calendar data, prefer fetch_live_calendar instead.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_calendar,
        )
    )
    kit.add(
        AgentTool(
            name="get_premarket_briefing",
            description="Fetch the pre-market briefing including overnight highlights and today's key data.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=get_premarket,
        )
    )
    kit.add(build_live_news_tool())
    kit.add(build_article_tool())
    kit.add(build_live_markets_tool())
    kit.add(build_country_indicators_tool())
    kit.add(build_reference_rates_tool())
    kit.add(build_rate_expectations_tool())
    if context.store is not None:
        kit.add(build_live_calendar_tool(context.store))
        kit.add(build_portfolio_risk_tool(context.store))
        kit.add(build_portfolio_holdings_tool(context.store))
        kit.add(build_portfolio_sync_tool(context.store))
        kit.add(build_stored_news_tool(context.store))
        kit.add(build_fed_comms_tool(context.store))
        kit.add(build_indicator_history_tool(context.store))
        kit.add(build_research_search_tool(context.store))
    kit.add(build_vix_regime_tool())
    if context.provider is not None:
        from analyst.engine.sub_agent_specs import build_user_sub_agents

        for sa_tool in build_user_sub_agents(kit.to_list(), context.provider, context.store):
            kit.add(sa_tool)
    return kit.to_list()


def _build_content_runtime_capabilities(context: CapabilityBuildContext) -> list[AgentTool]:
    if context.provider is None:
        return []
    from analyst.engine.sub_agent_specs import build_content_sub_agents

    return build_content_sub_agents(context.provider, context.store)


CAPABILITY_MATRIX: dict[str, CapabilitySurfaceSpec] = {
    "companion": CapabilitySurfaceSpec(
        surface_id="companion",
        native_tool_names=CLAUDE_CODE_NATIVE_TOOL_NAMES,
        shared_mcp_tool_names=COMPANION_SHARED_MCP_TOOL_NAMES,
        sub_agent_names=("research_agent",),
        build_tools=_build_companion_capabilities,
    ),
    "user_chat": CapabilitySurfaceSpec(
        surface_id="user_chat",
        native_tool_names=CLAUDE_CODE_NATIVE_TOOL_NAMES,
        shared_mcp_tool_names=USER_CHAT_SHARED_MCP_TOOL_NAMES,
        sub_agent_names=tuple(USER_SUB_AGENT_PARENT_TOOL_NAMES),
        build_tools=_build_user_chat_capabilities,
    ),
    "content_runtime": CapabilitySurfaceSpec(
        surface_id="content_runtime",
        sub_agent_names=tuple(CONTENT_SUB_AGENT_TOOL_BUILDERS),
        build_tools=_build_content_runtime_capabilities,
    ),
}


def get_capability_surface(surface_id: str) -> CapabilitySurfaceSpec:
    normalized = str(surface_id).strip().lower()
    try:
        return CAPABILITY_MATRIX[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown capability surface: {surface_id}") from exc


def build_capability_tools(
    surface_id: str,
    *,
    engine: OpenRouterAnalystEngine | Any | None = None,
    store: SQLiteEngineStore | None = None,
    provider: LLMProvider | None = None,
) -> list[AgentTool]:
    context = CapabilityBuildContext(engine=engine, store=store, provider=provider)
    return get_capability_surface(surface_id).build_tools(context)


def build_content_runtime_tools(
    *,
    provider: LLMProvider | None,
    store: SQLiteEngineStore | None = None,
) -> list[AgentTool]:
    return build_capability_tools("content_runtime", provider=provider, store=store)
