"""Search stored research artifacts (flash commentaries, deep dives, etc.)."""

from __future__ import annotations

import logging
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.storage import SQLiteEngineStore

logger = logging.getLogger(__name__)


class ResearchSearchHandler:
    """Callable that searches research_artifacts by keyword."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = (arguments.get("query") or "").strip()
        if not query:
            return {"error": "query is required", "artifacts": []}
        artifact_type = (arguments.get("artifact_type") or "").strip() or None
        limit = min(int(arguments.get("limit", 5)), 10)

        artifact_types = (artifact_type,) if artifact_type else ()

        try:
            artifacts = self._store.search_research_artifacts(
                query=query,
                limit=limit,
                artifact_types=artifact_types,
            )
        except Exception as exc:
            logger.warning("search_research_notes failed: %s", exc)
            return {"error": str(exc), "artifacts": []}

        items = []
        for a in artifacts:
            summary = a.summary
            if len(summary) > 600:
                summary = summary[:600] + "..."
            items.append({
                "artifact_id": a.artifact_id,
                "artifact_type": a.artifact_type,
                "title": a.title,
                "summary": summary,
                "created_at": a.created_at,
                "tags": a.tags,
            })

        return {
            "total": len(items),
            "artifacts": items,
        }


def build_research_search_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a search_research_notes AgentTool."""
    handler = ResearchSearchHandler(store)
    return AgentTool(
        name="search_research_notes",
        description=(
            "Search previously generated research artifacts: flash commentaries, deep dives, "
            "and other research notes. Keyword search over titles, summaries, and content. "
            "Use to find past analysis on a topic."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword search (e.g. 'CPI', 'rates', 'China trade')",
                },
                "artifact_type": {
                    "type": "string",
                    "description": "Filter by type: flash_commentary, deep_dive, etc.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 5, max 10)",
                },
            },
            "required": ["query"],
        },
        handler=handler,
    )
