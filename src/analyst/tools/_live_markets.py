"""Fetch live cross-asset market quotes from TradingEconomics."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


def build_live_markets_tool(*, data_client: MacroDataClient | None = None) -> AgentTool:
    """Factory: create a fetch_live_markets AgentTool."""
    handler = MacroDataOperationHandler("fetch_live_markets", data_client=data_client)
    return AgentTool(
        name="fetch_live_markets",
        description=(
            "Fetch live cross-asset market quotes from TradingEconomics (~90 instruments). "
            "Covers indices, commodities, FX, bonds, stocks, and crypto. "
            "Filter by asset_class or get all. Complements get_market_snapshot (yfinance from store)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "asset_class": {
                    "type": "string",
                    "description": "Filter by asset class: 'index', 'commodity', 'fx', 'bond', 'stock', 'crypto', or 'all' (default)",
                },
            },
        },
        handler=handler,
    )
