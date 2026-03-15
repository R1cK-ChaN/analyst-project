"""Fetch economic calendar events live from Investing.com, ForexFactory, and TradingEconomics."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient
from analyst.storage import SQLiteEngineStore

from ._macro_data import MacroDataOperationHandler


def build_live_calendar_tool(
    store: SQLiteEngineStore | None = None,
    *,
    data_client: MacroDataClient | None = None,
) -> AgentTool:
    """Factory: create a fetch_live_calendar AgentTool."""
    handler = MacroDataOperationHandler(
        "fetch_live_calendar",
        data_client=data_client,
        store=store,
    )
    return AgentTool(
        name="fetch_live_calendar",
        description=(
            "Fetch economic calendar events live from Investing.com, ForexFactory, and/or TradingEconomics right now. "
            "Use this to get the freshest calendar data when you need real-time event schedules, "
            "upcoming releases, or just-published actual values. TradingEconomics provides both market consensus "
            "and its own forecast (in raw_json.te_forecast). Results are also persisted to the store."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source to fetch from: 'investing', 'forexfactory', 'tradingeconomics', or 'all' (default)",
                },
                "importance": {
                    "type": "string",
                    "description": "Filter results by importance: high, medium, low",
                },
                "country": {
                    "type": "string",
                    "description": "Filter results by country code, e.g. US, JP, EU, CN",
                },
            },
        },
        handler=handler,
    )
