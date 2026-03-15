"""compare_series — compare two numeric series with summary statistics."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def compare_series(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    series_a = inputs.get("series_a")
    series_b = inputs.get("series_b")
    if not series_a or not series_b:
        return {"error": "inputs.series_a and inputs.series_b (numeric lists) are required"}

    a = np.array(series_a, dtype=float)
    b = np.array(series_b, dtype=float)

    min_len = min(len(a), len(b))
    a = a[-min_len:]
    b = b[-min_len:]

    label_a = str(parameters.get("label_a", "A"))
    label_b = str(parameters.get("label_b", "B"))

    diff = a - b
    ratio = np.where(b != 0, a / b, np.nan)

    return {
        "operator": "compare",
        "result_type": "metric",
        "n_points": min_len,
        "summary": {
            label_a: {
                "mean": round(float(np.nanmean(a)), 4),
                "latest": round(float(a[-1]), 4),
                "min": round(float(np.nanmin(a)), 4),
                "max": round(float(np.nanmax(a)), 4),
            },
            label_b: {
                "mean": round(float(np.nanmean(b)), 4),
                "latest": round(float(b[-1]), 4),
                "min": round(float(np.nanmin(b)), 4),
                "max": round(float(np.nanmax(b)), 4),
            },
        },
        "difference": {
            "latest": round(float(diff[-1]), 4),
            "mean": round(float(np.nanmean(diff)), 4),
            "widening": bool(len(diff) >= 2 and abs(diff[-1]) > abs(diff[-2])),
        },
        "ratio": {
            "latest": round(float(ratio[-1]), 4) if not np.isnan(ratio[-1]) else None,
            "mean": round(float(np.nanmean(ratio[~np.isnan(ratio)])), 4) if np.any(~np.isnan(ratio)) else None,
        },
    }


register_operator(OperatorSpec(
    name="compare",
    operator_type="relation",
    description="Compare two numeric series with difference, ratio, and summary statistics.",
    required_inputs=("series_a", "series_b"),
    optional_parameters=("label_a", "label_b"),
    output_type="metric",
    handler=compare_series,
))
