"""Query stored Fed communications (speeches, statements, minutes, testimony)."""

from __future__ import annotations

import logging
from typing import Any

from analyst.contracts import format_epoch_iso
from analyst.engine.live_types import AgentTool
from analyst.storage import SQLiteEngineStore

logger = logging.getLogger(__name__)


class FedCommsHandler:
    """Callable that queries central_bank_comms with speaker/content_type filters."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        speaker = (arguments.get("speaker") or "").strip() or None
        content_type = (arguments.get("content_type") or "").strip() or None
        days = min(int(arguments.get("days", 14)), 60)
        limit = min(int(arguments.get("limit", 5)), 15)

        try:
            comms = self._store.list_recent_central_bank_comms(
                source="fed",
                limit=limit,
                days=days,
                speaker=speaker,
                content_type=content_type,
            )
        except Exception as exc:
            logger.warning("get_fed_communications failed: %s", exc)
            return {"error": str(exc), "communications": []}

        items = []
        for c in comms:
            summary = c.summary
            if len(summary) > 800:
                summary = summary[:800] + "..."
            items.append({
                "title": c.title,
                "url": c.url,
                "timestamp": c.timestamp,
                "published_at": format_epoch_iso(c.timestamp),
                "speaker": c.speaker,
                "content_type": c.content_type,
                "summary": summary,
            })

        return {
            "total": len(items),
            "days": days,
            "communications": items,
        }


def build_fed_comms_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a get_fed_communications AgentTool."""
    handler = FedCommsHandler(store)
    return AgentTool(
        name="get_fed_communications",
        description=(
            "Query stored Fed communications: speeches, FOMC statements, minutes, testimony, Beige Book. "
            "Filter by speaker (Powell, Waller, Williams, etc.) and content type "
            "(speech/statement/minutes/testimony/beige_book). "
            "Returns title, speaker, date, summary, and URL."
        ),
        parameters={
            "type": "object",
            "properties": {
                "speaker": {
                    "type": "string",
                    "description": "Filter by speaker name (e.g. Powell, Waller, Williams, Bowman)",
                },
                "content_type": {
                    "type": "string",
                    "description": "Filter by type: speech, statement, minutes, testimony, beige_book",
                },
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (default 14, max 60)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5, max 15)",
                },
            },
        },
        handler=handler,
    )
