from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from analyst.agents import RoleDependencies, get_role_spec
from analyst.engine import OpenRouterAnalystEngine
from analyst.engine.live_types import AgentTool, LLMProvider
from analyst.engine.backends import ClaudeCodeProvider
from analyst.mcp.shared_tools import BASE_SHARED_MCP_TOOL_NAMES
from analyst.storage import SQLiteEngineStore
from analyst.tools import (
    ToolKit,
    build_article_tool,
    build_country_indicators_tool,
    build_live_markets_tool,
    build_live_news_tool,
    build_rate_expectations_tool,
    build_reference_rates_tool,
    build_vix_regime_tool,
    build_web_fetch_tool,
    build_web_search_tool,
)

CLAUDE_CODE_NATIVE_TOOL_NAMES = ("WebSearch", "WebFetch")
COMPANION_SHARED_MCP_TOOL_NAMES = (
    *BASE_SHARED_MCP_TOOL_NAMES,
    "fetch_live_calendar",
    "search_news",
    "get_fed_communications",
    "get_indicator_history",
    "search_research_notes",
    "generate_image",
)
RESEARCH_SUB_AGENT_PARENT_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "data_deep_dive": (
        "get_indicator_history",
        "get_indicator_trend",
        "get_surprise_summary",
        "get_recent_releases",
        "get_today_calendar",
        "run_python_analysis",
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

COMPANION_SUB_AGENT_NAMES: tuple[str, ...] = ()  # research_agent is now an optional HTTP delegate


@dataclass(frozen=True)
class EngineToolSpec:
    name: str
    description: str
    handler_factory: Callable[[OpenRouterAnalystEngine | Any], Callable[[dict[str, object]], str]]
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []}
    )


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
    static_tool_builders: tuple[Callable[[], AgentTool | None], ...] = ()
    optional_tool_builders: tuple[Callable[[], AgentTool | None], ...] = ()
    store_tool_builders: tuple[Callable[[SQLiteEngineStore], AgentTool | None], ...] = ()
    engine_tool_specs: tuple[EngineToolSpec, ...] = ()
    append_sub_agents: Callable[[list[AgentTool], CapabilityBuildContext], list[AgentTool]] | None = None
    build_tools: Callable[[CapabilityBuildContext], list[AgentTool]] | None = None


def _build_companion_capabilities(context: CapabilityBuildContext) -> list[AgentTool]:
    return get_role_spec("companion").build_tools(
        RoleDependencies(store=context.store, provider=context.provider),
    )


def _is_claude_code_provider(context: CapabilityBuildContext) -> bool:
    return isinstance(context.provider, ClaudeCodeProvider)


def _build_declared_surface(spec: CapabilitySurfaceSpec, context: CapabilityBuildContext) -> list[AgentTool]:
    kit = ToolKit()
    for builder in spec.static_tool_builders:
        tool = builder()
        if tool is not None:
            kit.add(tool)
    for builder in spec.optional_tool_builders:
        tool = builder()
        if tool is not None:
            kit.add(tool)
    if context.engine is not None and not _is_claude_code_provider(context):
        for tool_spec in spec.engine_tool_specs:
            kit.add(
                AgentTool(
                    name=tool_spec.name,
                    description=tool_spec.description,
                    parameters=tool_spec.parameters,
                    handler=tool_spec.handler_factory(context.engine),
                )
            )
    if context.store is not None:
        for builder in spec.store_tool_builders:
            tool = builder(context.store)
            if tool is not None:
                kit.add(tool)
    if spec.append_sub_agents is not None:
        for sa_tool in spec.append_sub_agents(kit.to_list(), context):
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
        sub_agent_names=COMPANION_SUB_AGENT_NAMES,
        build_tools=_build_companion_capabilities,
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
    spec = get_capability_surface(surface_id)
    if spec.build_tools is not None:
        tools = spec.build_tools(context)
    else:
        tools = _build_declared_surface(spec, context)
    _validate_surface_sub_agents(spec, tools, provider=provider)
    return tools


def build_content_runtime_tools(
    *,
    provider: LLMProvider | None,
    store: SQLiteEngineStore | None = None,
) -> list[AgentTool]:
    return build_capability_tools("content_runtime", provider=provider, store=store)


def _validate_surface_sub_agents(
    spec: CapabilitySurfaceSpec,
    tools: list[AgentTool],
    *,
    provider: LLMProvider | None,
) -> None:
    if provider is None or not spec.sub_agent_names:
        return
    if isinstance(provider, ClaudeCodeProvider):
        return
    tool_names = {
        name
        for tool in tools
        for name in (getattr(tool, "name", ""),)
        if isinstance(name, str) and name.strip()
    }
    if not tool_names:
        return
    missing = [name for name in spec.sub_agent_names if name not in tool_names]
    if missing:
        raise RuntimeError(
            f"Capability surface {spec.surface_id} declared missing sub-agents: {', '.join(missing)}"
        )
