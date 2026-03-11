"""Agent tool wrapper for the RAG retrieval engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from analyst.engine.live_types import AgentTool

if TYPE_CHECKING:
    from analyst.rag.retriever import MacroRetriever


def build_rag_search_tool(retriever: MacroRetriever) -> AgentTool:
    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        from analyst.rag.models import MacroMode

        query = str(arguments.get("query") or "")
        if not query.strip():
            return {"error": "query is required"}

        mode_str = str(arguments.get("mode") or "QA").upper()
        try:
            mode = MacroMode(mode_str)
        except ValueError:
            mode = MacroMode.QA

        filters: dict[str, Any] = {}
        for key in (
            "country",
            "indicator_group",
            "impact_level",
            "content_type",
            "source_type",
        ):
            val = arguments.get(key)
            if val:
                filters[key] = [val] if isinstance(val, str) else val

        days = arguments.get("days")
        if days:
            from datetime import datetime, timedelta, timezone

            cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
            filters["updated_after"] = cutoff.isoformat()

        limit = arguments.get("limit")
        limit_int = int(limit) if limit else None

        result = retriever.retrieve(query, mode, filters=filters, limit=limit_int)

        evidences = []
        for e in result.get("evidences", []):
            evidences.append({
                "chunk_id": e.chunk_id,
                "text": e.text,
                "source_type": e.source_type,
                "source_id": e.source_id,
                "section_path": e.section_path,
                "content_type": e.content_type,
                "country": e.country,
                "indicator_group": e.indicator_group,
                "impact_level": e.impact_level,
                "data_source": e.data_source,
                "updated_at": e.updated_at,
                "scores": e.scores,
            })

        return {
            "evidences": evidences,
            "stats": {
                "total_candidates": result.get("candidates_total", 0),
                "fused": result.get("deduped_total", 0),
                "final_k": result.get("final_k", 0),
                "coverage": result.get("coverage_counts", {}),
                "coverage_ok": result.get("coverage_ok", False),
                "timing_ms": result.get("timing_ms", 0),
            },
        }

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
