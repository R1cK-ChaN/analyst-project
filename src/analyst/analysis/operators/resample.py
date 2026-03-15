"""resample_series — change frequency of a time series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator

_VALID_METHODS = ("mean", "sum", "last", "first", "max", "min")


def resample_series(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values = inputs.get("values")
    if not values or not isinstance(values, list):
        return {"error": "inputs.values (numeric list) is required"}

    factor = int(parameters.get("factor", 3))
    method = parameters.get("method", "mean")

    if factor < 1:
        return {"error": "factor must be >= 1"}
    if method not in _VALID_METHODS:
        return {"error": f"Unknown method '{method}'. Use: {', '.join(_VALID_METHODS)}"}

    arr = np.array(values, dtype=float)
    n_buckets = len(arr) // factor
    if n_buckets < 1:
        return {"error": f"factor ({factor}) too large for series length ({len(arr)})"}

    trimmed = arr[:n_buckets * factor]
    reshaped = trimmed.reshape(n_buckets, factor)

    agg_fn = {"mean": np.nanmean, "sum": np.nansum, "last": lambda x, axis: x[:, -1],
              "first": lambda x, axis: x[:, 0], "max": np.nanmax, "min": np.nanmin}[method]
    resampled = agg_fn(reshaped, axis=1)

    labels = inputs.get("labels")
    new_labels = None
    if labels and len(labels) >= n_buckets * factor:
        new_labels = [labels[(i + 1) * factor - 1] for i in range(n_buckets)]

    result: dict[str, Any] = {
        "operator": "resample",
        "result_type": "series",
        "method": method,
        "factor": factor,
        "values": [round(float(v), 4) for v in resampled],
        "n_points": n_buckets,
    }
    if new_labels:
        result["labels"] = new_labels
    return result


register_operator(OperatorSpec(
    name="resample",
    operator_type="transform",
    description="Resample a series by aggregating every N points (e.g. daily→monthly with factor=21, method=mean).",
    input_types={"values": "series"},
    required_inputs=("values",),
    optional_parameters=("factor", "method"),
    output_type="series",
    handler=resample_series,
))
