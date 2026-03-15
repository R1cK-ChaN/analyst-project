"""rolling_stat — rolling window statistics for a value series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def rolling_stat(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = inputs.get("values")
    if not values or not isinstance(values, list):
        return {"error": "inputs.values (numeric list) is required"}

    arr = np.array(values, dtype=float)
    window = int(parameters.get("window", 3))
    stat = parameters.get("stat", "mean")  # mean, std, min, max, median

    if window < 1:
        return {"error": "window must be >= 1"}
    if window > len(arr):
        return {"error": f"window ({window}) exceeds series length ({len(arr)})"}

    stat_fn = {
        "mean": np.nanmean,
        "std": np.nanstd,
        "min": np.nanmin,
        "max": np.nanmax,
        "median": np.nanmedian,
    }.get(stat)

    if stat_fn is None:
        return {"error": f"Unknown stat '{stat}'. Use: mean, std, min, max, median"}

    rolling = []
    for i in range(len(arr) - window + 1):
        rolling.append(round(float(stat_fn(arr[i:i + window])), 4))

    return {
        "operator": "rolling_stat",
        "result_type": "series",
        "stat": stat,
        "window": window,
        "values": rolling,
        "latest": rolling[-1] if rolling else None,
        "n_points": len(rolling),
    }


register_operator(OperatorSpec(
    name="rolling_stat",
    operator_type="transform",
    description="Compute rolling window statistics (mean, std, min, max, median) over a numeric series.",
    required_inputs=("values",),
    optional_parameters=("window", "stat"),
    output_type="series",
    handler=rolling_stat,
))
