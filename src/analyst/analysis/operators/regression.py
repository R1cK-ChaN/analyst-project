"""regression — linear regression between two series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def regression(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    series_x = inputs.get("series_x")
    series_y = inputs.get("series_y")
    if not series_x or not series_y:
        return {"error": "inputs.series_x and inputs.series_y (numeric lists) are required"}

    x = np.array(series_x, dtype=float)
    y = np.array(series_y, dtype=float)

    min_len = min(len(x), len(y))
    if min_len < 3:
        return {"error": "Need at least 3 overlapping data points for regression"}
    x = x[-min_len:]
    y = y[-min_len:]

    mask = ~(np.isnan(x) | np.isnan(y))
    x_clean = x[mask]
    y_clean = y[mask]
    if len(x_clean) < 3:
        return {"error": "Need at least 3 non-NaN overlapping points"}

    coeffs = np.polyfit(x_clean, y_clean, 1)
    beta = float(coeffs[0])
    alpha = float(coeffs[1])

    y_pred = alpha + beta * x_clean
    ss_res = float(np.sum((y_clean - y_pred) ** 2))
    ss_tot = float(np.sum((y_clean - np.mean(y_clean)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 0.0

    residuals = y_clean - y_pred

    label_x = str(parameters.get("label_x", "X"))
    label_y = str(parameters.get("label_y", "Y"))

    return {
        "operator": "regression",
        "result_type": "metric",
        "beta": round(beta, 6),
        "alpha": round(alpha, 4),
        "r_squared": round(r_squared, 4),
        "n_points": len(x_clean),
        "residual_std": round(float(np.std(residuals)), 4),
        "label_x": label_x,
        "label_y": label_y,
    }


register_operator(OperatorSpec(
    name="regression",
    operator_type="relation",
    description="Linear regression (Y = alpha + beta*X) with R², residuals, and coefficient estimates.",
    input_types={"series_x": "series", "series_y": "series"},
    required_inputs=("series_x", "series_y"),
    optional_parameters=("label_x", "label_y"),
    output_type="metric",
    handler=regression,
))
