"""difference — spread/difference between two series with z-score and signal."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def difference(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    series_a = inputs.get("series_a")
    series_b = inputs.get("series_b")
    if not series_a or not series_b:
        return {"error": "inputs.series_a and inputs.series_b (numeric lists) are required"}

    a = np.array(series_a, dtype=float)
    b = np.array(series_b, dtype=float)

    min_len = min(len(a), len(b))
    a = a[-min_len:]
    b = b[-min_len:]

    spread = a - b
    current = float(spread[-1])
    mean = float(np.nanmean(spread))
    std = float(np.nanstd(spread))
    z_score = float((current - mean) / std) if std > 1e-10 else 0.0

    if abs(z_score) >= 2.0:
        signal = "extreme"
    elif abs(z_score) >= 1.0:
        signal = "elevated"
    else:
        signal = "normal"

    label_a = str(parameters.get("label_a", "A"))
    label_b = str(parameters.get("label_b", "B"))

    return {
        "operator": "difference",
        "result_type": "metric",
        "current": round(current, 4),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "z_score": round(z_score, 2),
        "signal": signal,
        "direction": "widening" if len(spread) >= 2 and abs(spread[-1]) > abs(spread[-2]) else "narrowing",
        "min": round(float(np.nanmin(spread)), 4),
        "max": round(float(np.nanmax(spread)), 4),
        "n_points": min_len,
        "label_a": label_a,
        "label_b": label_b,
    }


register_operator(OperatorSpec(
    name="difference",
    operator_type="relation",
    description="Compute spread/difference between two series with z-score and signal classification.",
    required_inputs=("series_a", "series_b"),
    optional_parameters=("label_a", "label_b"),
    output_type="metric",
    handler=difference,
))
