"""Agent tool wrapper for the RAG retrieval engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler

if TYPE_CHECKING:
    from analyst.rag.retriever import MacroRetriever


def build_rag_search_tool(
    retriever: MacroRetriever | None = None,
    *,
    data_client: MacroDataClient | None = None,
) -> AgentTool:
    handler = MacroDataOperationHandler(
        "search_knowledge_base",
        data_client=data_client,
        retriever=retriever,
    )
    return AgentTool(
        name="search_knowledge_base",
        description=(
            "Search the macro-economic knowledge base using hybrid dense+sparse retrieval. "
            "Returns semantically relevant evidence from news articles, Fed communications, "
            "and research notes. Use this for any question requiring narrative context or "
            "analysis beyond what structured data tools (indicators, calendar) provide."
        ),
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["RESEARCH", "BRIEFING", "QA", "REGIME"],
                    "description": "Retrieval mode. Default QA.",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country code (US, CN, EU, JP, etc.).",
                },
                "indicator_group": {
                    "type": "string",
                    "description": "Filter by indicator group (inflation, employment, growth, rates, etc.).",
                },
                "impact_level": {
                    "type": "string",
                    "description": "Filter by impact level (critical, high, medium, low).",
                },
                "content_type": {
                    "type": "string",
                    "description": "Filter by content type (article, speech, statement, minutes, research_note, etc.).",
                },
                "days": {
                    "type": "integer",
                    "description": "Only include content from the last N days.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of evidence chunks to return.",
                },
            },
        },
        handler=handler,
    )
