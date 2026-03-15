"""Fetch country economic indicators live from TradingEconomics."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


def build_country_indicators_tool(*, data_client: MacroDataClient | None = None) -> AgentTool:
    """Factory: create a fetch_country_indicators AgentTool."""
    handler = MacroDataOperationHandler("fetch_country_indicators", data_client=data_client)
    return AgentTool(
        name="fetch_country_indicators",
        description=(
            "Fetch a comprehensive country economic profile from TradingEconomics (~400 indicators). "
            "Includes GDP, inflation, employment, trade, government, business, consumer, and more. "
            "Filter by category keyword. Complements get_indicator_history (FRED time-series depth)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Country slug, e.g. 'united-states', 'china', 'euro-area' (default: united-states)",
                },
                "category": {
                    "type": "string",
                    "description": "Keyword filter on category/name (partial match), e.g. 'gdp', 'inflation', 'employment'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max indicators to return (default 50, max 100)",
                },
            },
        },
        handler=handler,
    )
