"""Operator registry — maps operator names to their specs and functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .types import check_composability


@dataclass(frozen=True)
class OperatorSpec:
    """Metadata for a registered analysis operator.

    ``input_types`` declares the expected type of each named input.
    For example, ``{"values": "series"}`` means the ``values`` input
    should come from an upstream operator that outputs a ``series``.
    """

    name: str
    operator_type: str  # dataset, transform, metric, relation, signal
    description: str
    input_types: dict[str, str] = field(default_factory=dict)
    required_inputs: tuple[str, ...] = ()
    optional_parameters: tuple[str, ...] = ()
    output_type: str = "dict"
    needs_context: bool = False
    handler: Callable[..., dict[str, Any]] = field(repr=False, default=lambda **kw: {})


OPERATOR_REGISTRY: dict[str, OperatorSpec] = {}


def register_operator(spec: OperatorSpec) -> None:
    """Register an operator spec in the global registry."""
    OPERATOR_REGISTRY[spec.name] = spec


def run_operator(
    name: str,
    inputs: dict[str, Any],
    parameters: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Look up and execute a registered operator.

    If any input value is a dict with a ``result_type`` field (i.e. an
    upstream operator output), the type is validated against the operator's
    ``input_types`` declaration before execution.

    Raises ``KeyError`` if the operator is not registered.
    Raises ``TypeMismatchError`` if input types do not match.
    """
    spec = OPERATOR_REGISTRY.get(name)
    if spec is None:
        available = ", ".join(sorted(OPERATOR_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown operator '{name}'. Available: {available}")

    # Type-check any typed inputs (upstream operator outputs)
    if spec.input_types:
        _validate_input_types(spec, inputs)

    kwargs: dict[str, Any] = {"inputs": inputs, "parameters": parameters or {}}
    if spec.needs_context:
        kwargs["context"] = context or {}
    return spec.handler(**kwargs)


def validate_chain(upstream_spec: OperatorSpec, downstream_spec: OperatorSpec, via_input: str) -> None:
    """Validate that upstream.output_type is compatible with downstream's expected input type.

    ``via_input`` is the input name on the downstream operator that will
    receive the upstream output (e.g. ``"values"``).

    Raises ``TypeMismatchError`` if incompatible.
    """
    expected = downstream_spec.input_types.get(via_input)
    if expected is None:
        return  # input not typed, no constraint
    check_composability(
        upstream_spec.output_type,
        expected,
        upstream_name=upstream_spec.name,
        downstream_name=downstream_spec.name,
    )


def _validate_input_types(spec: OperatorSpec, inputs: dict[str, Any]) -> None:
    """Check typed inputs that carry a result_type field from upstream."""
    for input_name, expected_type in spec.input_types.items():
        value = inputs.get(input_name)
        if isinstance(value, dict) and "result_type" in value:
            check_composability(
                value["result_type"],
                expected_type,
                upstream_name=f"input.{input_name}",
                downstream_name=spec.name,
            )
