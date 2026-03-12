"""Fetch NY Fed reference rates (SOFR, EFFR, OBFR) live."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.scrapers import NYFedRatesClient
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler

logger = logging.getLogger(__name__)

_VALID_RATE_TYPES = {"sofr", "effr", "obfr", "all"}


class ReferenceRatesHandler:
    """Stateful callable that fetches NY Fed money market rates."""

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        rate_type = (arguments.get("rate_type") or "all").lower().strip()
        last_n = min(int(arguments.get("last_n", 3)), 10)

        if rate_type not in _VALID_RATE_TYPES:
            return {"error": f"Invalid rate_type '{rate_type}'. Use: sofr, effr, obfr, or all", "rates": []}

        try:
            client = NYFedRatesClient()
            if rate_type == "sofr":
                rates = client.fetch_sofr(last_n=last_n)
            elif rate_type == "effr":
                rates = client.fetch_effr(last_n=last_n)
            elif rate_type == "obfr":
                rates = client.fetch_obfr(last_n=last_n)
            else:
                rates = client.fetch_all_rates(last_n=last_n)
        except Exception as exc:
            logger.warning("Live rates fetch failed: %s", exc)
            return {"error": str(exc), "rates": []}

        items = [
            {
                "date": r.date,
                "type": r.type,
                "rate": r.rate,
                "percentile_1": r.percentile_1,
                "percentile_25": r.percentile_25,
                "percentile_75": r.percentile_75,
                "percentile_99": r.percentile_99,
                "volume_billions": r.volume_billions,
                "target_rate_from": r.target_rate_from,
                "target_rate_to": r.target_rate_to,
            }
            for r in rates
        ]

        return {
            "rate_type": rate_type,
            "total": len(items),
            "rates": items,
        }


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
