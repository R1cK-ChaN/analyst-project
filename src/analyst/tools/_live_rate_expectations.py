"""Fetch Fed rate probability forward curve from rateprobability.com."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.scrapers import RateProbabilityClient
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler

logger = logging.getLogger(__name__)


class RateExpectationsHandler:
    """Stateful callable that fetches CME FedWatch-equivalent rate probabilities."""

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        include_history = bool(arguments.get("include_history", False))

        try:
            result = RateProbabilityClient().fetch_probabilities()
        except Exception as exc:
            logger.warning("Rate expectations fetch failed: %s", exc)
            return {"error": str(exc)}

        meetings = [
            {
                "meeting_date": m.meeting_date,
                "implied_rate": m.implied_rate,
                "prob_move_pct": m.prob_move_pct,
                "is_cut": m.is_cut,
                "num_moves": m.num_moves,
                "change_bps": m.change_bps,
            }
            for m in result.meetings
        ]

        output: dict[str, Any] = {
            "as_of": result.as_of,
            "current_band": result.current_band,
            "midpoint": result.midpoint,
            "effr": result.effr,
            "meetings": meetings,
        }

        if include_history and result.snapshots:
            output["snapshots"] = {
                label: [
                    {
                        "meeting_date": m.meeting_date,
                        "implied_rate": m.implied_rate,
                        "prob_move_pct": m.prob_move_pct,
                        "is_cut": m.is_cut,
                        "num_moves": m.num_moves,
                        "change_bps": m.change_bps,
                    }
                    for m in snapshot_meetings
                ]
                for label, snapshot_meetings in result.snapshots.items()
            }

        return output


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
