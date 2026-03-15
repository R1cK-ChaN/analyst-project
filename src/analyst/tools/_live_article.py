"""Fetch a full article using domain-aware scraper routing."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


def build_article_tool(*, data_client: MacroDataClient | None = None) -> AgentTool:
    """Factory: create a fetch_article AgentTool."""
    handler = MacroDataOperationHandler("fetch_article", data_client=data_client)
    return AgentTool(
        name="fetch_article",
        description=(
            "Fetch and extract a full article from a URL. Auto-detects domain and uses specialized "
            "scrapers for Bloomberg, FT, WSJ, and Reuters (with authenticated access for paywalled sites). "
            "Falls back to a generic extractor for other domains. Use this for financial news article URLs."
        ),
        parameters={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The article URL to fetch.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max content characters to return (default 6000, max 12000)",
                },
            },
        },
        handler=handler,
    )
