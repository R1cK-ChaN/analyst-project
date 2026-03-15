"""pct_change — period-over-period percentage changes for a value series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def pct_change(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = inputs.get("values")
    if not values or not isinstance(values, list):
        return {"error": "inputs.values (numeric list) is required"}

    labels = inputs.get("labels")
    arr = np.array(values, dtype=float)
    period = int(parameters.get("period", 1))

    if period >= len(arr):
        return {"error": f"period ({period}) must be less than series length ({len(arr)})"}

    prev = arr[:-period]
    curr = arr[period:]
    with np.errstate(divide="ignore", invalid="ignore"):
        changes = np.where(prev != 0, (curr - prev) / np.abs(prev) * 100, 0.0)

    result: dict[str, Any] = {
        "operator": "pct_change",
        "result_type": "series",
        "period": period,
        "latest_change": round(float(changes[-1]), 4) if len(changes) > 0 else 0.0,
        "avg_change": round(float(np.nanmean(changes)), 4) if len(changes) > 0 else 0.0,
        "n_points": len(changes),
        "values": [round(float(c), 4) for c in changes],
    }

    if labels and len(labels) > period:
        result["labels"] = labels[period:]

    return result


register_operator(OperatorSpec(
    name="pct_change",
    operator_type="transform",
    description="Compute period-over-period percentage changes (MoM, QoQ, YoY).",
    input_types={"values": "series"},
    required_inputs=("values",),
    optional_parameters=("period",),
    output_type="series",
    handler=pct_change,
))
