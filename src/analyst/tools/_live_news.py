"""Fetch live news headlines from up to 7 financial news sources."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.scrapers import (
    BloombergNewsClient,
    FTNewsClient,
    ForexFactoryNewsClient,
    InvestingNewsClient,
    ReutersNewsClient,
    TradingEconomicsNewsClient,
    WSJNewsClient,
)

logger = logging.getLogger(__name__)

_PRESETS: dict[str, tuple[str, ...]] = {
    "all": ("investing", "forexfactory", "tradingeconomics", "reuters", "bloomberg", "ft", "wsj"),
    "premium": ("bloomberg", "ft", "wsj", "reuters"),
    "free": ("investing", "forexfactory", "tradingeconomics"),
}


class LiveNewsHandler:
    """Stateful callable that aggregates headlines from multiple news scrapers."""

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_sources = (arguments.get("sources") or "all").lower().strip()
        section = arguments.get("section") or "markets"
        limit = min(int(arguments.get("limit", 10)), 25)

        sources = _PRESETS.get(raw_sources)
        if sources is None:
            sources = tuple(s.strip() for s in raw_sources.split(",") if s.strip())

        all_items: list[dict[str, Any]] = []
        errors: list[str] = []

        for src in sources:
            try:
                items = self._fetch_source(src, section=section, limit=limit)
                all_items.extend(items)
            except Exception as exc:
                logger.warning("Live news fetch from %s failed: %s", src, exc)
                errors.append(f"{src}: {exc}")

        result: dict[str, Any] = {
            "sources_requested": list(sources),
            "total": len(all_items),
            "items": all_items,
        }
        if errors:
            result["errors"] = errors
        return result

    def _fetch_source(self, source: str, *, section: str, limit: int) -> list[dict[str, Any]]:
        if source == "investing":
            raw = InvestingNewsClient().fetch_news(category=section)[:limit]
        elif source == "forexfactory":
            raw = ForexFactoryNewsClient().fetch_news()[:limit]
        elif source == "tradingeconomics":
            raw = TradingEconomicsNewsClient().fetch_news(count=limit)
        elif source == "reuters":
            raw = ReutersNewsClient().fetch_news(section=section)[:limit]
        elif source == "bloomberg":
            with BloombergNewsClient() as client:
                raw = client.fetch_news(section=section)[:limit]
        elif source == "ft":
            with FTNewsClient() as client:
                raw = client.fetch_news(section=section)[:limit]
        elif source == "wsj":
            with WSJNewsClient() as client:
                raw = client.fetch_news(section=section)[:limit]
        else:
            return []

        return [
            {
                "source": item.source,
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at,
                "description": item.description[:200] if item.description else "",
                "category": item.category,
                "importance": item.importance,
            }
            for item in raw
        ]


def build_live_news_tool() -> AgentTool:
    """Factory: create a fetch_live_news AgentTool."""
    handler = LiveNewsHandler()
    return AgentTool(
        name="fetch_live_news",
        description=(
            "Fetch live news headlines from financial news sources. "
            "Aggregates up to 7 sources: investing, forexfactory, tradingeconomics, reuters, bloomberg, ft, wsj. "
            "Use presets 'all', 'premium' (bloomberg/ft/wsj/reuters), or 'free' (investing/ff/te), "
            "or pass a comma-separated list. Never fails completely — returns per-source errors."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "string",
                    "description": "Comma-separated source names or preset: 'all' (default), 'premium', 'free'",
                },
                "section": {
                    "type": "string",
                    "description": "News section/category, e.g. 'markets', 'economy', 'world' (default: markets)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max headlines per source (default 10, max 25)",
                },
            },
        },
        handler=handler,
    )
