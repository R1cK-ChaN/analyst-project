from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from analyst.contracts import format_epoch_iso

logger = logging.getLogger(__name__)

_REMOTE_ONLY_ERROR = "This operation requires the macro-data-service (set ANALYST_MACRO_DATA_BASE_URL)."


class LocalMacroDataService:
    """In-process fallback for store-based operations only.

    Live-fetch operations (scrapers, ingestion) are handled exclusively by the
    standalone macro-data-service over HTTP.  If ``ANALYST_MACRO_DATA_BASE_URL``
    is set, ``coerce_macro_data_client`` will return an ``HttpMacroDataClient``
    and these stubs will never be reached.
    """

    def __init__(
        self,
        *,
        store: Any,
        retriever: Any | None = None,
    ) -> None:
        self._store = store
        self._retriever = retriever

    def invoke(self, operation: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        handler = getattr(self, f"_op_{operation}", None)
        if handler is None:
            raise KeyError(f"unknown macro-data operation: {operation}")
        return handler(arguments or {})

    # ------------------------------------------------------------------
    # Store-based operations (no ingestion required)
    # ------------------------------------------------------------------

    def _op_get_recent_releases(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = self._store.list_recent_events(
            limit=int(arguments.get("limit", 10)),
            days=int(arguments.get("days", 7)),
            released_only=True,
            importance=arguments.get("importance"),
            country=arguments.get("country"),
            category=arguments.get("category"),
        )
        return {"events": [self._event_to_dict(event) for event in events]}

    def _op_get_latest_released_event(self, arguments: dict[str, Any]) -> dict[str, Any]:
        event = self._store.latest_released_event(
            indicator_keyword=arguments.get("indicator_keyword"),
        )
        return {"event": self._event_to_dict(event) if event is not None else None}

    def _op_get_upcoming_calendar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = self._store.list_upcoming_events(limit=int(arguments.get("limit", 10)))
        return {"events": [self._event_to_dict(event) for event in events]}

    def _op_get_market_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        prices = self._store.latest_market_prices()
        return {"prices": [self._price_to_dict(price) for price in prices]}

    def _op_get_recent_fed_comms(self, arguments: dict[str, Any]) -> dict[str, Any]:
        communications = self._store.list_recent_central_bank_comms(
            days=int(arguments.get("days", 14)),
            limit=int(arguments.get("limit", 5)),
        )
        return {"communications": [self._comm_to_dict(item) for item in communications]}

    def _op_get_fed_communications(self, arguments: dict[str, Any]) -> dict[str, Any]:
        speaker = (arguments.get("speaker") or "").strip() or None
        content_type = (arguments.get("content_type") or "").strip() or None
        days = min(int(arguments.get("days", 14)), 60)
        limit = min(int(arguments.get("limit", 5)), 15)
        comms = self._store.list_recent_central_bank_comms(
            source="fed",
            limit=limit,
            days=days,
            speaker=speaker,
            content_type=content_type,
        )
        return {
            "total": len(comms),
            "days": days,
            "communications": [self._comm_to_dict(item) for item in comms],
        }

    def _op_get_indicator_history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        series_id = (arguments.get("series_id") or "").strip()
        if not series_id:
            return {"error": "series_id is required", "observations": []}
        limit = min(int(arguments.get("limit", 12)), 36)
        observations = self._store.get_indicator_history(series_id, limit=limit)
        items = [
            {
                "series_id": observation.series_id,
                "date": observation.date,
                "value": observation.value,
                "source": observation.source,
                "metadata": getattr(observation, "metadata", {}),
            }
            for observation in observations
        ]
        return {"series_id": series_id, "total": len(items), "observations": items}

    def _op_get_today_calendar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        events = self._store.list_today_events(
            importance=arguments.get("importance"),
            country=arguments.get("country"),
            category=arguments.get("category"),
        )
        return {"events": [self._event_to_dict(event) for event in events]}

    def _op_get_indicator_trend(self, arguments: dict[str, Any]) -> dict[str, Any]:
        keyword = str(arguments["indicator_keyword"])
        limit = int(arguments.get("limit", 12))
        events = self._store.list_indicator_releases(indicator_keyword=keyword, limit=limit)
        return {
            "indicator_keyword": keyword,
            "releases": [self._event_to_dict(event) for event in events],
        }

    def _op_get_surprise_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        days = int(arguments.get("days", 14))
        events = self._store.list_recent_events(limit=200, days=days, released_only=True)
        by_category: dict[str, list[float]] = {}
        for event in events:
            if event.surprise is not None:
                by_category.setdefault(event.category, []).append(float(event.surprise))
        summary = []
        for category, surprises in sorted(by_category.items()):
            beats = sum(1 for item in surprises if item > 0)
            misses = sum(1 for item in surprises if item < 0)
            avg = round(sum(surprises) / len(surprises), 4) if surprises else 0.0
            summary.append({
                "category": category,
                "count": len(surprises),
                "beats": beats,
                "misses": misses,
                "avg_surprise": avg,
            })
        return {"summary": summary}

    def _op_get_recent_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        articles = self._store.get_news_context(
            days=int(arguments.get("days", 3)),
            limit=int(arguments.get("limit", 15)),
            impact_level=arguments.get("impact_level"),
            feed_category=arguments.get("feed_category"),
            finance_category=arguments.get("finance_category"),
            country=arguments.get("country"),
            asset_class=arguments.get("asset_class"),
            display_timezone=arguments.get("timezone"),
        )
        return {"articles": articles}

    def _op_search_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = (arguments.get("query") or "").strip() or None
        days = min(int(arguments.get("days", 7)), 30)
        limit = min(int(arguments.get("limit", 10)), 25)
        articles = self._store.get_news_context(
            query=query,
            days=days,
            limit=limit,
            impact_level=(arguments.get("impact_level") or "").strip() or None,
            feed_category=(arguments.get("feed_category") or "").strip() or None,
            finance_category=(arguments.get("finance_category") or "").strip() or None,
            country=(arguments.get("country") or "").strip() or None,
            asset_class=(arguments.get("asset_class") or "").strip() or None,
            display_timezone=(arguments.get("timezone") or "").strip() or None,
        )
        return {"total": len(articles), "days": days, "articles": articles}

    def _op_search_knowledge_base(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._retriever is None:
            return {
                "error": "knowledge base unavailable",
                "evidences": [],
                "stats": {"total_candidates": 0, "fused": 0, "final_k": 0, "coverage": {}, "coverage_ok": False, "timing_ms": 0},
            }
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
        for key in ("country", "indicator_group", "impact_level", "content_type", "source_type"):
            value = arguments.get(key)
            if value:
                filters[key] = [value] if isinstance(value, str) else value
        days = arguments.get("days")
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
            filters["updated_after"] = cutoff.isoformat()
        limit = arguments.get("limit")
        result = self._retriever.retrieve(
            query,
            mode,
            filters=filters,
            limit=int(limit) if limit else None,
        )
        evidences = []
        for evidence in result.get("evidences", []):
            evidences.append({
                "chunk_id": evidence.chunk_id,
                "text": evidence.text,
                "source_type": evidence.source_type,
                "source_id": evidence.source_id,
                "section_path": evidence.section_path,
                "content_type": evidence.content_type,
                "country": evidence.country,
                "indicator_group": evidence.indicator_group,
                "impact_level": evidence.impact_level,
                "data_source": evidence.data_source,
                "updated_at": evidence.updated_at,
                "scores": evidence.scores,
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

    # ------------------------------------------------------------------
    # Remote-only operations (require macro-data-service)
    # ------------------------------------------------------------------

    def _op_refresh_all_sources(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_run_schedule(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_refresh_calendar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_refresh_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_live_calendar(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_live_news(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_live_markets(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_country_indicators(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_reference_rates(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_rate_expectations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_fetch_article(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    def _op_web_fetch_page(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"error": _REMOTE_ONLY_ERROR}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _event_to_dict(self, event: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": event.source,
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "datetime_utc": format_epoch_iso(event.timestamp),
            "country": event.country,
            "indicator": event.indicator,
            "category": event.category,
            "importance": event.importance,
            "actual": event.actual,
            "forecast": event.forecast,
            "previous": event.previous,
            "surprise": event.surprise,
        }
        indicator_id = getattr(event, "indicator_id", "")
        if indicator_id:
            payload["indicator_id"] = indicator_id
        return payload

    def _price_to_dict(self, price: Any) -> dict[str, Any]:
        return {
            "symbol": price.symbol,
            "name": price.name,
            "asset_class": price.asset_class,
            "price": price.price,
            "change_pct": price.change_pct,
            "timestamp": price.timestamp,
            "datetime_utc": format_epoch_iso(price.timestamp),
        }

    def _comm_to_dict(self, communication: Any) -> dict[str, Any]:
        summary = communication.summary
        if len(summary) > 800:
            summary = summary[:800] + "..."
        return {
            "title": communication.title,
            "url": communication.url,
            "timestamp": communication.timestamp,
            "published_at": format_epoch_iso(communication.timestamp),
            "speaker": communication.speaker,
            "content_type": communication.content_type,
            "summary": summary,
        }
