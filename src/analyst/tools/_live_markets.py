"""Fetch live cross-asset market quotes from TradingEconomics."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.scrapers import TradingEconomicsMarketsClient
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler

logger = logging.getLogger(__name__)

_VALID_ASSET_CLASSES = {"index", "commodity", "fx", "bond", "stock", "crypto"}


class LiveMarketsHandler:
    """Stateful callable that fetches live market quotes."""

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        asset_class = (arguments.get("asset_class") or "all").lower().strip()

        try:
            quotes = TradingEconomicsMarketsClient().fetch_markets()
        except Exception as exc:
            logger.warning("Live markets fetch failed: %s", exc)
            return {"error": str(exc), "quotes": []}

        items = [
            {
                "name": q.name,
                "asset_class": q.asset_class,
                "price": q.price,
                "change": q.change,
                "change_pct": q.change_pct,
                "symbol": q.symbol,
            }
            for q in quotes
        ]

        if asset_class != "all" and asset_class in _VALID_ASSET_CLASSES:
            items = [q for q in items if q["asset_class"].lower() == asset_class]

        return {
            "total": len(items),
            "asset_class_filter": asset_class,
            "quotes": items,
        }


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
