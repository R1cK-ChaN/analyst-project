"""Fetch economic calendar events live from Investing.com, ForexFactory, and TradingEconomics."""

from __future__ import annotations

import logging
from typing import Any

from analyst.contracts import format_epoch_iso
from analyst.engine.live_types import AgentTool
from analyst.ingestion.sources import (
    ForexFactoryCalendarClient,
    InvestingCalendarClient,
    TradingEconomicsCalendarClient,
)
from analyst.macro_data import MacroDataClient
from analyst.storage import SQLiteEngineStore, StoredEventRecord

from ._macro_data import MacroDataOperationHandler

logger = logging.getLogger(__name__)

_ALL_SOURCES = ("investing", "forexfactory", "tradingeconomics")


class LiveCalendarHandler:
    """Stateful callable that scrapes calendar sites live via curl_cffi."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        source = (arguments.get("source") or "all").lower()
        importance_filter = arguments.get("importance")
        country_filter = arguments.get("country")

        sources = _ALL_SOURCES if source == "all" else (source,)

        all_events: list[StoredEventRecord] = []
        errors: list[str] = []

        for src in sources:
            try:
                if src == "investing":
                    all_events.extend(InvestingCalendarClient().fetch())
                elif src == "forexfactory":
                    all_events.extend(ForexFactoryCalendarClient().fetch())
                elif src == "tradingeconomics":
                    all_events.extend(TradingEconomicsCalendarClient().fetch())
            except Exception as exc:
                logger.warning("Live fetch from %s failed: %s", src, exc)
                errors.append(f"{src}: {exc}")

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
                    "timestamp": e.timestamp,
                    "datetime_utc": format_epoch_iso(e.timestamp),
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
