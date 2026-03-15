"""compute_correlation — Pearson correlation between two numeric series."""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import OperatorSpec, register_operator


def compute_correlation(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    series_a = inputs.get("series_a")
    series_b = inputs.get("series_b")
    if not series_a or not series_b:
        return {"error": "inputs.series_a and inputs.series_b (numeric lists) are required"}

    a = np.array(series_a, dtype=float)
    b = np.array(series_b, dtype=float)

    min_len = min(len(a), len(b))
    if min_len < 3:
        return {"error": "Need at least 3 overlapping data points for correlation"}
    a = a[-min_len:]
    b = b[-min_len:]

    mask = ~(np.isnan(a) | np.isnan(b))
    a_clean = a[mask]
    b_clean = b[mask]

    if len(a_clean) < 3:
        return {"error": "Need at least 3 non-NaN overlapping points"}

    corr = float(np.corrcoef(a_clean, b_clean)[0, 1])

    if abs(corr) >= 0.7:
        strength = "strong"
    elif abs(corr) >= 0.4:
        strength = "moderate"
    else:
        strength = "weak"

    label_a = str(parameters.get("label_a", "A"))
    label_b = str(parameters.get("label_b", "B"))

    return {
        "operator": "correlation",
        "correlation": round(corr, 4),
        "strength": strength,
        "direction": "positive" if corr > 0 else "negative" if corr < 0 else "none",
        "n_points": len(a_clean),
        "label_a": label_a,
        "label_b": label_b,
    }


register_operator(OperatorSpec(
    name="correlation",
    operator_type="relation",
    description="Compute Pearson correlation between two numeric series with strength classification.",
    required_inputs=("series_a", "series_b"),
    optional_parameters=("label_a", "label_b"),
    output_type="correlation_result",
    handler=compute_correlation,
))
