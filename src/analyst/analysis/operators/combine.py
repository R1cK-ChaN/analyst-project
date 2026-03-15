"""combine_series — combine multiple series into one via aggregation."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator

_VALID_METHODS = ("mean", "sum", "min", "max", "median")


def combine_series(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    series_list = inputs.get("series_list")
    if not series_list or not isinstance(series_list, list) or len(series_list) < 2:
        return {"error": "inputs.series_list (list of numeric lists, >= 2) is required"}

    method = parameters.get("method", "mean")
    weights = parameters.get("weights")

    if method not in _VALID_METHODS and method != "weighted":
        return {"error": f"Unknown method '{method}'. Use: {', '.join(_VALID_METHODS)}, weighted"}

    min_len = min(len(s) for s in series_list)
    if min_len < 1:
        return {"error": "All series must have at least 1 value"}

    # Tail-align all series
    aligned = np.array([s[-min_len:] for s in series_list], dtype=float)

    if method == "weighted":
        if not weights or len(weights) != len(series_list):
            return {"error": f"weights must have {len(series_list)} elements for weighted method"}
        w = np.array(weights, dtype=float)
        w = w / w.sum()
        combined = np.sum(aligned * w[:, np.newaxis], axis=0)
    else:
        fn = {"mean": np.nanmean, "sum": np.nansum, "min": np.nanmin,
              "max": np.nanmax, "median": np.nanmedian}[method]
        combined = fn(aligned, axis=0)

    return {
        "operator": "combine",
        "result_type": "series",
        "method": method,
        "n_series": len(series_list),
        "n_points": min_len,
        "values": [round(float(v), 4) for v in combined],
    }


register_operator(OperatorSpec(
    name="combine",
    operator_type="transform",
    description="Combine multiple series into one via aggregation (mean, sum, weighted, min, max, median).",
    required_inputs=("series_list",),
    optional_parameters=("method", "weights"),
    output_type="series",
    handler=combine_series,
))
