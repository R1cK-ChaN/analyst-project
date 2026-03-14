from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from analyst.engine.live_types import AgentTool
from analyst.storage import SQLiteEngineStore
from analyst.tools import (
    build_article_tool,
    build_country_indicators_tool,
    build_fed_comms_tool,
    build_image_gen_tool,
    build_indicator_history_tool,
    build_live_calendar_tool,
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
)


ToolBuilder = Callable[[SQLiteEngineStore | None], AgentTool | None]


@dataclass(frozen=True)
class SharedMcpToolSpec:
    name: str
    build_tool: ToolBuilder
    requires_store: bool = False


def _stateless(builder: Callable[[], AgentTool]) -> ToolBuilder:
    def _build(_store: SQLiteEngineStore | None) -> AgentTool:
        return builder()

    return _build


def _optional_stateless(builder: Callable[[], AgentTool | None]) -> ToolBuilder:
    def _build(_store: SQLiteEngineStore | None) -> AgentTool | None:
        return builder()

    return _build


def _store_bound(builder: Callable[[SQLiteEngineStore], AgentTool]) -> ToolBuilder:
    def _build(store: SQLiteEngineStore | None) -> AgentTool | None:
        if store is None:
            return None
        return builder(store)

    return _build


BASE_SHARED_MCP_TOOL_NAMES: tuple[str, ...] = (
    "fetch_live_news",
    "fetch_article",
    "fetch_live_markets",
    "fetch_country_indicators",
    "fetch_reference_rates",
    "fetch_rate_expectations",
    "get_vix_regime",
)

STORE_SHARED_MCP_TOOL_NAMES: tuple[str, ...] = (
    "fetch_live_calendar",
    "search_news",
    "get_fed_communications",
    "get_indicator_history",
    "search_research_notes",
    "get_portfolio_risk",
    "get_portfolio_holdings",
)

MEDIA_SHARED_MCP_TOOL_NAMES: tuple[str, ...] = (
    "generate_image",
    "generate_live_photo",
)

MUTATION_SHARED_MCP_TOOL_NAMES: tuple[str, ...] = (
    "sync_portfolio_from_broker",
)


SHARED_MCP_TOOL_SPECS: dict[str, SharedMcpToolSpec] = {
    "fetch_live_news": SharedMcpToolSpec("fetch_live_news", _stateless(build_live_news_tool)),
    "fetch_article": SharedMcpToolSpec("fetch_article", _stateless(build_article_tool)),
    "fetch_live_markets": SharedMcpToolSpec("fetch_live_markets", _stateless(build_live_markets_tool)),
    "fetch_country_indicators": SharedMcpToolSpec("fetch_country_indicators", _stateless(build_country_indicators_tool)),
    "fetch_reference_rates": SharedMcpToolSpec("fetch_reference_rates", _stateless(build_reference_rates_tool)),
    "fetch_rate_expectations": SharedMcpToolSpec("fetch_rate_expectations", _stateless(build_rate_expectations_tool)),
    "get_vix_regime": SharedMcpToolSpec("get_vix_regime", _stateless(build_vix_regime_tool)),
    "fetch_live_calendar": SharedMcpToolSpec("fetch_live_calendar", _store_bound(build_live_calendar_tool), requires_store=True),
    "search_news": SharedMcpToolSpec("search_news", _store_bound(build_stored_news_tool), requires_store=True),
    "get_fed_communications": SharedMcpToolSpec("get_fed_communications", _store_bound(build_fed_comms_tool), requires_store=True),
    "get_indicator_history": SharedMcpToolSpec("get_indicator_history", _store_bound(build_indicator_history_tool), requires_store=True),
    "search_research_notes": SharedMcpToolSpec("search_research_notes", _store_bound(build_research_search_tool), requires_store=True),
    "get_portfolio_risk": SharedMcpToolSpec("get_portfolio_risk", _store_bound(build_portfolio_risk_tool), requires_store=True),
    "get_portfolio_holdings": SharedMcpToolSpec("get_portfolio_holdings", _store_bound(build_portfolio_holdings_tool), requires_store=True),
    "generate_image": SharedMcpToolSpec("generate_image", _stateless(build_image_gen_tool)),
    "generate_live_photo": SharedMcpToolSpec("generate_live_photo", _optional_stateless(build_optional_live_photo_tool)),
    "sync_portfolio_from_broker": SharedMcpToolSpec("sync_portfolio_from_broker", _store_bound(build_portfolio_sync_tool), requires_store=True),
}


def default_shared_mcp_tool_names(*, include_store_tools: bool) -> tuple[str, ...]:
    if include_store_tools:
        return (*BASE_SHARED_MCP_TOOL_NAMES, *STORE_SHARED_MCP_TOOL_NAMES)
    return BASE_SHARED_MCP_TOOL_NAMES


def validate_shared_mcp_tool_names(tool_names: tuple[str, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for name in tool_names:
        normalized = str(name).strip()
        if not normalized or normalized not in SHARED_MCP_TOOL_SPECS or normalized in ordered:
            continue
        ordered.append(normalized)
    return tuple(ordered)


def build_shared_mcp_tools(
    *,
    tool_names: tuple[str, ...],
    db_path: str | Path | None = None,
) -> list[AgentTool]:
    validated = validate_shared_mcp_tool_names(tool_names)
    if not validated:
        return []

    store: SQLiteEngineStore | None = None
    if db_path:
        store = SQLiteEngineStore(db_path=Path(db_path))

    tools: list[AgentTool] = []
    for name in validated:
        spec = SHARED_MCP_TOOL_SPECS[name]
        tool = spec.build_tool(store)
        if tool is not None:
            tools.append(tool)
    return tools
