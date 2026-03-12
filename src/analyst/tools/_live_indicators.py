"""Fetch country economic indicators live from TradingEconomics."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.scrapers import TradingEconomicsIndicatorsClient
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler

logger = logging.getLogger(__name__)


class CountryIndicatorsHandler:
    """Stateful callable that fetches a country's economic indicators."""

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        country = (arguments.get("country") or "united-states").lower().strip()
        category_filter = (arguments.get("category") or "").lower().strip()
        limit = min(int(arguments.get("limit", 50)), 100)

        try:
            indicators = TradingEconomicsIndicatorsClient().fetch_indicators(country=country)
        except Exception as exc:
            logger.warning("Live indicators fetch failed for %s: %s", country, exc)
            return {"error": str(exc), "indicators": []}

        items = [
            {
                "name": ind.name,
                "last": ind.last,
                "previous": ind.previous,
                "highest": ind.highest,
                "lowest": ind.lowest,
                "unit": ind.unit,
                "date": ind.date,
                "category": ind.category,
            }
            for ind in indicators
        ]

        if category_filter:
            items = [
                i for i in items
                if category_filter in i["category"].lower() or category_filter in i["name"].lower()
            ]

        items = items[:limit]

        return {
            "country": country,
            "total": len(items),
            "indicators": items,
        }


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
