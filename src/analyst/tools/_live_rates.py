"""Fetch NY Fed reference rates (SOFR, EFFR, OBFR) live."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


def build_reference_rates_tool(*, data_client: MacroDataClient | None = None) -> AgentTool:
    """Factory: create a fetch_reference_rates AgentTool."""
    handler = MacroDataOperationHandler("fetch_reference_rates", data_client=data_client)
    return AgentTool(
        name="fetch_reference_rates",
        description=(
            "Fetch NY Fed reference rates: SOFR, EFFR, OBFR with full distribution data "
            "(percentiles, volume, target rate band). Use to get current money market conditions "
            "and recent rate history. Complements fetch_rate_expectations (where markets expect rates to go)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "rate_type": {
                    "type": "string",
                    "description": "Rate type: 'sofr', 'effr', 'obfr', or 'all' (default)",
                },
                "last_n": {
                    "type": "integer",
                    "description": "Number of recent observations (default 3, max 10)",
                },
            },
        },
        handler=handler,
    )
