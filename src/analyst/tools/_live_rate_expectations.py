"""Fetch Fed rate probability forward curve from rateprobability.com."""

from __future__ import annotations

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


def build_rate_expectations_tool(*, data_client: MacroDataClient | None = None) -> AgentTool:
    """Factory: create a fetch_rate_expectations AgentTool."""
    handler = MacroDataOperationHandler("fetch_rate_expectations", data_client=data_client)
    return AgentTool(
        name="fetch_rate_expectations",
        description=(
            "Fetch Fed rate probability forward curve (CME FedWatch equivalent). "
            "Shows market-implied rate expectations for upcoming FOMC meetings, including "
            "probability of moves, implied rates, and cut/hike direction. "
            "Optionally includes historical snapshots (1w/3w/6w/10w ago). "
            "Complements fetch_reference_rates (where rates are now)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "Include historical snapshots (1w, 3w, 6w, 10w ago). Default false.",
                },
            },
        },
        handler=handler,
    )
