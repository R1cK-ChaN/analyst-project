"""compute_change — period-over-period changes for a value series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def compute_change(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = inputs.get("values")
    if not values or not isinstance(values, list):
        return {"error": "inputs.values (numeric list) is required"}

    labels = inputs.get("labels")  # optional date/period labels
    arr = np.array(values, dtype=float)

    period = int(parameters.get("period", 1))
    mode = parameters.get("mode", "absolute")  # absolute or percent

    if period >= len(arr):
        return {"error": f"period ({period}) must be less than series length ({len(arr)})"}

    if mode == "percent":
        prev = arr[:-period]
        curr = arr[period:]
        with np.errstate(divide="ignore", invalid="ignore"):
            changes = np.where(prev != 0, (curr - prev) / np.abs(prev) * 100, 0.0)
    else:
        changes = np.diff(arr, n=period).astype(float)

    latest_change = float(changes[-1]) if len(changes) > 0 else 0.0
    avg_change = float(np.nanmean(changes)) if len(changes) > 0 else 0.0

    result: dict[str, Any] = {
        "operator": "change",
        "mode": mode,
        "period": period,
        "latest_change": round(latest_change, 4),
        "avg_change": round(avg_change, 4),
        "max_change": round(float(np.nanmax(changes)), 4) if len(changes) > 0 else 0.0,
        "min_change": round(float(np.nanmin(changes)), 4) if len(changes) > 0 else 0.0,
        "n_changes": len(changes),
        "changes": [round(float(c), 4) for c in changes],
    }

    if labels and len(labels) > period:
        result["labels"] = labels[period:]

    return result


register_operator(OperatorSpec(
    name="change",
    operator_type="metric",
    description="Compute period-over-period changes (absolute or percent) for a numeric series.",
    required_inputs=("values",),
    optional_parameters=("period", "mode"),
    output_type="change_result",
    handler=compute_change,
))
