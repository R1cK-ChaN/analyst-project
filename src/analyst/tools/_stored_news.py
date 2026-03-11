"""Search stored news archive with FTS, time-decay scoring, and rich filters."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.storage import SQLiteEngineStore

logger = logging.getLogger(__name__)


class StoredNewsHandler:
    """Callable that queries the ingested news archive via store.get_news_context()."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = (arguments.get("query") or "").strip() or None
        days = min(int(arguments.get("days", 7)), 30)
        limit = min(int(arguments.get("limit", 10)), 25)
        impact_level = (arguments.get("impact_level") or "").strip() or None
        feed_category = (arguments.get("feed_category") or "").strip() or None
        finance_category = (arguments.get("finance_category") or "").strip() or None
        country = (arguments.get("country") or "").strip() or None
        asset_class = (arguments.get("asset_class") or "").strip() or None
        timezone_name = (arguments.get("timezone") or "").strip() or None

        try:
            articles = self._store.get_news_context(
                query=query,
                days=days,
                limit=limit,
                impact_level=impact_level,
                feed_category=feed_category,
                finance_category=finance_category,
                country=country,
                asset_class=asset_class,
                display_timezone=timezone_name,
            )
        except Exception as exc:
            logger.warning("search_news failed: %s", exc)
            return {"error": str(exc), "articles": []}

        return {
            "total": len(articles),
            "days": days,
            "articles": articles,
        }


def build_stored_news_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a search_news AgentTool backed by the stored news archive."""
    handler = StoredNewsHandler(store)
    return AgentTool(
        name="search_news",
        description=(
            "Search the stored news archive (140+ RSS feeds, 23 categories). "
            "Supports keyword search (FTS), time range, and filters by impact level, "
            "feed category (centralbanks/markets/forex/commodities/china/etc.), "
            "finance category (monetary_policy/inflation/rates/growth/labor/geopolitics/etc.), "
            "country code, and asset class. Results are ranked by time-decay + impact-weight scoring."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search (FTS or LIKE fallback). Optional — omit to browse by filters alone.",
                },
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (default 7, max 30)",
                },
                "impact_level": {
                    "type": "string",
                    "description": "Filter by impact: critical, high, medium, low",
                },
                "feed_category": {
                    "type": "string",
                    "description": "Filter by source category: centralbanks, markets, forex, commodities, china, etc.",
                },
                "finance_category": {
                    "type": "string",
                    "description": "Filter by topic: monetary_policy, inflation, rates, growth, labor, geopolitics, etc.",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country code (e.g. US, CN, JP, EU)",
                },
                "asset_class": {
                    "type": "string",
                    "description": "Filter by asset class (e.g. equities, fixed_income, fx, commodities)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10, max 25)",
                },
                "timezone": {
                    "type": "string",
                    "description": "Optional IANA timezone for display, e.g. Asia/Singapore",
                },
            },
        },
        handler=handler,
    )
