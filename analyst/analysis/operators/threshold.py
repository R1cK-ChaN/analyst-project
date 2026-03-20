"""threshold_signal — classify series values against a threshold."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def threshold_signal(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = inputs.get("values")
    if not values or not isinstance(values, list):
        return {"error": "inputs.values (numeric list) is required"}

    threshold = parameters.get("threshold")
    if threshold is None:
        return {"error": "parameters.threshold (numeric) is required"}
    threshold = float(threshold)

    above_label = str(parameters.get("above_label", "high"))
    below_label = str(parameters.get("below_label", "low"))

    arr = np.array(values, dtype=float)
    current = float(arr[-1])
    current_signal = above_label if current >= threshold else below_label

    above_count = int(np.sum(arr >= threshold))
    below_count = int(np.sum(arr < threshold))
    above_pct = round(above_count / len(arr) * 100, 1) if len(arr) > 0 else 0.0

    # Detect recent crossover
    crossover = "none"
    if len(arr) >= 2:
        prev = float(arr[-2])
        if prev < threshold <= current:
            crossover = f"crossed_above_{threshold}"
        elif prev >= threshold > current:
            crossover = f"crossed_below_{threshold}"

    return {
        "operator": "threshold_signal",
        "result_type": "signal",
        "current_value": round(current, 4),
        "threshold": threshold,
        "signal": current_signal,
        "crossover": crossover,
        "above_count": above_count,
        "below_count": below_count,
        "above_pct": above_pct,
        "n_points": len(arr),
    }


register_operator(OperatorSpec(
    name="threshold_signal",
    operator_type="signal",
    description="Classify the latest value against a threshold (e.g. inflation > 3% → 'high'). Detects crossovers.",
    input_types={"values": "series"},
    required_inputs=("values",),
    optional_parameters=("threshold", "above_label", "below_label"),
    output_type="signal",
    handler=threshold_signal,
))
