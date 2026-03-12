"""Query FRED / macro indicator time series from the stored indicators table."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient
from analyst.storage import SQLiteEngineStore

from ._macro_data import MacroDataOperationHandler

logger = logging.getLogger(__name__)


class IndicatorHistoryHandler:
    """Callable that queries stored indicator observations by series_id."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        series_id = (arguments.get("series_id") or "").strip()
        if not series_id:
            return {"error": "series_id is required", "observations": []}
        limit = min(int(arguments.get("limit", 12)), 36)

        try:
            observations = self._store.get_indicator_history(series_id, limit=limit)
        except Exception as exc:
            logger.warning("get_indicator_history failed: %s", exc)
            return {"error": str(exc), "observations": []}

        items = [
            {
                "series_id": o.series_id,
                "date": o.date,
                "value": o.value,
                "source": o.source,
            }
            for o in observations
        ]

        return {
            "series_id": series_id,
            "total": len(items),
            "observations": items,
        }


def build_indicator_history_tool(
    store: SQLiteEngineStore | None = None,
    *,
    data_client: MacroDataClient | None = None,
) -> AgentTool:
    """Factory: create a get_indicator_history AgentTool."""
    handler = MacroDataOperationHandler(
        "get_indicator_history",
        data_client=data_client,
        store=store,
    )
    return AgentTool(
        name="get_indicator_history",
        description=(
            "Query stored FRED macro indicator time series. Supports 27 FRED series "
            "(CPIAUCSL, UNRATE, GDP, DGS10, DGS2, FEDFUNDS, etc.), NY Fed rates (NYFED_SOFR), "
            "and rate probability data (FEDPROB_*). Returns recent observations in reverse chronological order."
        ),
        parameters={
            "type": "object",
            "properties": {
                "series_id": {
                    "type": "string",
                    "description": "FRED series ID (e.g. CPIAUCSL, UNRATE, DGS10) or stored series (NYFED_SOFR, FEDPROB_*)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of observations to return (default 12, max 36)",
                },
            },
            "required": ["series_id"],
        },
        handler=handler,
    )
