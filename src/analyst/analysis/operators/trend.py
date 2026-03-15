"""compute_trend — linear trend direction and slope over a value series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def compute_trend(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = inputs.get("values")
    if not values or not isinstance(values, list):
        return {"error": "inputs.values (numeric list) is required"}

    arr = np.array(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return {"error": "Need at least 2 non-NaN values for trend"}

    window = int(parameters.get("window", len(arr)))
    arr = arr[-window:]

    x = np.arange(len(arr))
    coeffs = np.polyfit(x, arr, 1)
    slope = float(coeffs[0])
    intercept = float(coeffs[1])

    if abs(slope) < 1e-10:
        direction = "flat"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"

    total_change = float(arr[-1] - arr[0])
    pct_change = float(total_change / arr[0] * 100) if arr[0] != 0 else 0.0

    return {
        "operator": "trend",
        "direction": direction,
        "slope": round(slope, 6),
        "intercept": round(intercept, 4),
        "start_value": float(arr[0]),
        "end_value": float(arr[-1]),
        "total_change": round(total_change, 4),
        "pct_change": round(pct_change, 2),
        "n_points": len(arr),
    }


register_operator(OperatorSpec(
    name="trend",
    operator_type="metric",
    description="Compute linear trend direction and slope over a numeric series.",
    required_inputs=("values",),
    optional_parameters=("window",),
    output_type="trend_result",
    handler=compute_trend,
))
