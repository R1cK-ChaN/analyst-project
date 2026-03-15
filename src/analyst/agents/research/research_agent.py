from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from analyst.engine.agent_loop import AgentLoopConfig
from analyst.engine.live_types import AgentTool
from analyst.engine.sub_agent import SubAgentSpec, build_sub_agent_tool
from analyst.tools import (
    ToolKit,
    build_article_tool,
    build_country_indicators_tool,
    build_fed_comms_tool,
    build_indicator_history_tool,
    build_live_markets_tool,
    build_live_news_tool,
    build_portfolio_holdings_tool,
    build_portfolio_risk_tool,
    build_python_analysis_tool,
    build_rate_expectations_tool,
    build_reference_rates_tool,
    build_research_search_tool,
    build_stored_news_tool,
    build_vix_regime_tool,
    build_web_fetch_tool,
    build_web_search_tool,
)
from analyst.tools._live_calendar import build_live_calendar_tool

from ..base import AgentRoleSpec, RoleDependencies, RolePromptContext
from ..companion.spec_builder import build_research_delegation_spec, render_research_delegation_prompt
from .research_prompts import build_research_system_prompt

_RESEARCH_AGENT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "required": ["task"],
    "properties": {
        "task": {"type": "string", "description": "The concrete research question or investigation task."},
        "goal": {"type": "string", "description": "What the companion needs to understand or explain back to the user."},
        "analysis_type": {
            "type": "string",
            "enum": ["general", "macro", "markets", "news", "portfolio"],
            "description": "Dominant category for the task.",
        },
        "time_horizon": {"type": "string", "description": "Relevant time window such as today, this week, 1m, or 2y."},
        "output_format": {
            "type": "string",
            "enum": ["summary", "briefing", "bullet_points", "risk_check", "timeline"],
            "description": "Preferred shape of the analysis output.",
        },
        "context": {"type": "string", "description": "Optional user-safe context or constraints to keep in mind."},
    },
}


def build_research_role_spec() -> AgentRoleSpec:
    return AgentRoleSpec(
        role_id="research",
        build_system_prompt=build_research_system_prompt,
        build_tools=_build_research_tools,
    )


def build_research_agent_tool(
    *,
    provider,
    store: Any | None = None,
) -> AgentTool | None:
    if provider is None:
        return None
    role_spec = build_research_role_spec()
    sub_agent_spec = SubAgentSpec(
        name="research_agent",
        description=(
            "Investigate a macro, market, news, or portfolio question and return a concise factual brief "
            "the companion can relay naturally."
        ),
        system_prompt=role_spec.build_system_prompt(
            RolePromptContext(current_time_label=_research_now_label())
        ),
        tools=role_spec.build_tools(RoleDependencies(store=store, provider=provider)),
        config=AgentLoopConfig(max_turns=4, max_tokens=1400, temperature=0.2),
        parameters=_RESEARCH_AGENT_PARAMETERS,
        build_user_prompt=_build_research_user_prompt,
    )
    return build_sub_agent_tool(sub_agent_spec, provider, store=store, parent_agent="companion")


def _build_research_tools(dependencies: RoleDependencies) -> list[AgentTool]:
    kit = ToolKit()
    kit.add(build_web_search_tool())
    kit.add(build_web_fetch_tool())
    kit.add(build_live_news_tool())
    kit.add(build_article_tool())
    kit.add(build_live_markets_tool())
    kit.add(build_country_indicators_tool())
    kit.add(build_reference_rates_tool())
    kit.add(build_rate_expectations_tool())
    kit.add(build_vix_regime_tool())
    kit.add(build_python_analysis_tool())
    from analyst.tools._analysis_operators import build_analysis_operator_tool
    kit.add(build_analysis_operator_tool(dependencies.store))
    if dependencies.store is not None:
        from analyst.tools._artifact_cache import build_artifact_lookup_tool, build_artifact_store_tool
        kit.add(build_artifact_lookup_tool(dependencies.store))
        kit.add(build_artifact_store_tool(dependencies.store))
        kit.add(build_live_calendar_tool(dependencies.store))
        kit.add(build_portfolio_risk_tool(dependencies.store))
        kit.add(build_portfolio_holdings_tool(dependencies.store))
        kit.add(build_stored_news_tool(dependencies.store))
        kit.add(build_fed_comms_tool(dependencies.store))
        kit.add(build_indicator_history_tool(dependencies.store))
        kit.add(build_research_search_tool(dependencies.store))
    return kit.to_list()


def _build_research_user_prompt(arguments: dict[str, Any]) -> str:
    spec = build_research_delegation_spec(arguments)
    return render_research_delegation_prompt(spec)


def _research_now_label() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M UTC")
