"""fetch_series — normalize indicator history into a typed Series."""

from __future__ import annotations

from typing import Any

from .registry import OperatorSpec, register_operator


def fetch_series(*, inputs: dict[str, Any], parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    series_id = str(inputs.get("series_id", "")).strip()
    if not series_id:
        return {"error": "inputs.series_id is required"}

    store = context.get("store")
    if store is None:
        return {"error": "fetch_series requires a store (not available in this context)"}

    limit = int(parameters.get("limit", 24))

    try:
        observations = store.get_indicator_history(series_id, limit=limit)
    except Exception as exc:
        return {"error": f"Failed to fetch '{series_id}': {exc}"}

    if not observations:
        return {"error": f"No data found for series '{series_id}'"}

    values = [float(obs.value) for obs in observations if obs.value is not None]
    labels = [obs.date for obs in observations if obs.value is not None]

    return {
        "operator": "fetch_series",
        "result_type": "series",
        "series_id": series_id,
        "values": values,
        "labels": labels,
        "n_points": len(values),
        "source": observations[0].source if observations else "",
    }


register_operator(OperatorSpec(
    name="fetch_series",
    operator_type="dataset",
    description="Fetch indicator time series from store and normalize to typed Series output.",
    required_inputs=("series_id",),
    optional_parameters=("limit",),
    output_type="series",
    needs_context=True,
    handler=fetch_series,
))
