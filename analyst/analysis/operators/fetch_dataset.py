"""fetch_dataset — normalize store queries into a typed Dataset."""

from __future__ import annotations

from typing import Any

from .registry import OperatorSpec, register_operator

_DATASET_SOURCES = ("calendar", "news", "fed_comms", "market_prices")


def fetch_dataset(*, inputs: dict[str, Any], parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    dataset = str(inputs.get("dataset", "")).strip()
    if not dataset:
        return {"error": f"inputs.dataset is required. Available: {', '.join(_DATASET_SOURCES)}"}

    store = context.get("store")
    if store is None:
        return {"error": "fetch_dataset requires a store (not available in this context)"}

    limit = int(parameters.get("limit", 20))
    days = int(parameters.get("days", 7))

    try:
        if dataset == "calendar":
            events = store.list_recent_events(limit=limit, days=days, released_only=False)
            records = [
                {"date": e.timestamp, "country": e.country, "indicator": e.indicator,
                 "category": e.category, "importance": e.importance,
                 "actual": e.actual, "forecast": e.forecast, "previous": e.previous}
                for e in events
            ]
        elif dataset == "news":
            records = store.get_news_context(limit=limit, days=days)
        elif dataset == "fed_comms":
            comms = store.list_recent_central_bank_comms(limit=limit, days=days)
            records = [
                {"title": c.title, "speaker": c.speaker, "content_type": c.content_type,
                 "timestamp": c.timestamp, "summary": c.summary[:300]}
                for c in comms
            ]
        elif dataset == "market_prices":
            prices = store.latest_market_prices()
            records = [
                {"symbol": p.symbol, "name": p.name, "asset_class": p.asset_class,
                 "price": p.price, "change_pct": p.change_pct}
                for p in prices
            ]
        else:
            return {"error": f"Unknown dataset '{dataset}'. Available: {', '.join(_DATASET_SOURCES)}"}
    except Exception as exc:
        return {"error": f"Failed to fetch dataset '{dataset}': {exc}"}

    return {
        "operator": "fetch_dataset",
        "result_type": "dataset",
        "dataset": dataset,
        "records": records,
        "n_records": len(records),
    }


register_operator(OperatorSpec(
    name="fetch_dataset",
    operator_type="dataset",
    description="Fetch tabular data (calendar, news, fed_comms, market_prices) from store as typed Dataset.",
    input_types={},
    required_inputs=("dataset",),
    optional_parameters=("limit", "days"),
    output_type="dataset",
    needs_context=True,
    handler=fetch_dataset,
))
