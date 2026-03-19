"""Research delegate tool — calls research-service over HTTP.

Replaces the in-process SubAgentHandler with a thin HTTP delegate.
The companion agent uses this tool exactly like the old research_agent tool —
same name, same parameters, same return shape.
"""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool

from .client import ResearchClient, coerce_research_client

logger = logging.getLogger(__name__)

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


class ResearchDelegateHandler:
    def __init__(self, client: ResearchClient) -> None:
        self._client = client

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._client.investigate(arguments)
        except Exception as exc:
            logger.warning("Research delegate call failed: %s", exc)
            return {"status": "error", "error": str(exc)}


def build_research_delegate_tool(
    client: ResearchClient | None = None,
) -> AgentTool | None:
    """Build a research_agent tool that delegates to the research-service via HTTP.

    Returns None if no research client is available (ANALYST_RESEARCH_BASE_URL not set).
    """
    resolved = coerce_research_client(client=client)
    if resolved is None:
        return None
    handler = ResearchDelegateHandler(resolved)
    return AgentTool(
        name="research_agent",
        description=(
            "Investigate a macro, market, news, or portfolio question and return a concise factual brief "
            "the companion can relay naturally."
        ),
        parameters=_RESEARCH_AGENT_PARAMETERS,
        handler=handler,
    )
