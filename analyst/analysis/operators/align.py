"""align_series — align two series to their common time axis."""

from __future__ import annotations

from typing import Any

from .registry import OperatorSpec, register_operator


def align_series(*, inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    values_a = inputs.get("values_a")
    values_b = inputs.get("values_b")
    labels_a = inputs.get("labels_a")
    labels_b = inputs.get("labels_b")

    if not values_a or not values_b:
        return {"error": "inputs.values_a and inputs.values_b are required"}

    # If labels provided, align by common labels (inner join)
    if labels_a and labels_b:
        set_b = set(labels_b)
        b_map = dict(zip(labels_b, values_b))

        aligned_labels = []
        aligned_a = []
        aligned_b = []

        for label, val in zip(labels_a, values_a):
            if label in set_b:
                aligned_labels.append(label)
                aligned_a.append(val)
                aligned_b.append(b_map[label])

        if not aligned_labels:
            return {"error": "No overlapping labels between the two series"}

        return {
            "operator": "align",
            "result_type": "dataset",
            "labels": aligned_labels,
            "series_a": aligned_a,
            "series_b": aligned_b,
            "n_points": len(aligned_labels),
            "dropped_a": len(values_a) - len(aligned_a),
            "dropped_b": len(values_b) - len(aligned_b),
        }

    # No labels — truncate to shorter length (tail-aligned)
    min_len = min(len(values_a), len(values_b))
    return {
        "operator": "align",
        "result_type": "dataset",
        "series_a": list(values_a[-min_len:]),
        "series_b": list(values_b[-min_len:]),
        "n_points": min_len,
        "dropped_a": len(values_a) - min_len,
        "dropped_b": len(values_b) - min_len,
    }


register_operator(OperatorSpec(
    name="align",
    operator_type="transform",
    description="Align two series to a common time axis (inner join by labels, or tail-truncate if no labels).",
    input_types={"values_a": "series", "values_b": "series"},
    required_inputs=("values_a", "values_b"),
    optional_parameters=(),
    output_type="dataset",
    handler=align_series,
))
