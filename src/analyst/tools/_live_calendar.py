"""Fetch economic calendar events live from Investing.com and ForexFactory."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.sources import ForexFactoryCalendarClient, InvestingCalendarClient
from analyst.storage import SQLiteEngineStore, StoredEventRecord

logger = logging.getLogger(__name__)


class LiveCalendarHandler:
    """Stateful callable that scrapes calendar sites live via curl_cffi."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source = (arguments.get("source") or "both").lower()
        importance_filter = arguments.get("importance")
        country_filter = arguments.get("country")

        all_events: list[StoredEventRecord] = []
        errors: list[str] = []

        if source in ("investing", "both"):
            try:
                all_events.extend(InvestingCalendarClient().fetch())
            except Exception as exc:
                logger.warning("Live fetch from Investing.com failed: %s", exc)
                errors.append(f"Investing.com: {exc}")

        if source in ("forexfactory", "both"):
            try:
                all_events.extend(ForexFactoryCalendarClient().fetch())
            except Exception as exc:
                logger.warning("Live fetch from ForexFactory failed: %s", exc)
                errors.append(f"ForexFactory: {exc}")

        for event in all_events:
            try:
                self._store.upsert_calendar_event(event)
            except Exception:
                pass

        filtered = all_events
        if importance_filter:
            filtered = [e for e in filtered if e.importance == importance_filter]
        if country_filter:
            filtered = [e for e in filtered if e.country == country_filter.upper()]

        result: dict[str, Any] = {
            "total_fetched": len(all_events),
            "returned": len(filtered),
            "events": [
                {
                    "source": e.source,
                    "event_id": e.event_id,
                    "datetime_utc": e.datetime_utc,
                    "country": e.country,
                    "indicator": e.indicator,
                    "category": e.category,
                    "importance": e.importance,
                    "actual": e.actual,
                    "forecast": e.forecast,
                    "previous": e.previous,
                    "surprise": e.surprise,
                }
                for e in filtered
            ],
        }
        if errors:
            result["errors"] = errors
        return result


def build_live_calendar_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a fetch_live_calendar AgentTool."""
    handler = LiveCalendarHandler(store)
    return AgentTool(
        name="fetch_live_calendar",
        description=(
            "Fetch economic calendar events live from Investing.com and/or ForexFactory right now. "
            "Use this to get the freshest calendar data when you need real-time event schedules, "
            "upcoming releases, or just-published actual values. Results are also persisted to the store."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Source to fetch from: 'investing', 'forexfactory', or 'both' (default)",
                },
                "importance": {
                    "type": "string",
                    "description": "Filter results by importance: high, medium, low",
                },
                "country": {
                    "type": "string",
                    "description": "Filter results by country code, e.g. US, JP, EU",
                },
            },
        },
        handler=handler,
    )
