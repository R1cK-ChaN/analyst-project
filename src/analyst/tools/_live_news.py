"""Fetch live news headlines from up to 7 financial news sources."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


def build_live_news_tool(*, data_client: MacroDataClient | None = None) -> AgentTool:
    """Factory: create a fetch_live_news AgentTool."""
    handler = MacroDataOperationHandler("fetch_live_news", data_client=data_client)
    return AgentTool(
        name="fetch_live_news",
        description=(
            "Fetch live news headlines from financial news sources. "
            "Aggregates up to 7 sources: investing, forexfactory, tradingeconomics, reuters, bloomberg, ft, wsj. "
            "Use presets 'all', 'premium' (bloomberg/ft/wsj/reuters), or 'free' (investing/ff/te), "
            "or pass a comma-separated list. Never fails completely — returns per-source errors."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "string",
                    "description": "Comma-separated source names or preset: 'all' (default), 'premium', 'free'",
                },
                "section": {
                    "type": "string",
                    "description": "News section/category, e.g. 'markets', 'economy', 'world' (default: markets)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max headlines per source (default 10, max 25)",
                },
            },
        },
        handler=handler,
    )
