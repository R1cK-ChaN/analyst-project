"""Operator registry — maps operator names to their specs and functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class OperatorSpec:
    """Metadata for a registered analysis operator."""

    name: str
    operator_type: str  # dataset, transform, metric, relation, model, signal
    description: str
    required_inputs: tuple[str, ...] = ()
    optional_parameters: tuple[str, ...] = ()
    output_type: str = "dict"
    needs_context: bool = False  # True if operator requires store/runtime context
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

    ``context`` is an optional dict containing runtime dependencies
    (e.g. ``{"store": store_instance}``).  Operators that declare
    ``needs_context=True`` receive it as a keyword argument.

    Raises ``KeyError`` if the operator is not registered.
    """
    spec = OPERATOR_REGISTRY.get(name)
    if spec is None:
        available = ", ".join(sorted(OPERATOR_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown operator '{name}'. Available: {available}")
    kwargs: dict[str, Any] = {"inputs": inputs, "parameters": parameters or {}}
    if spec.needs_context:
        kwargs["context"] = context or {}
    return spec.handler(**kwargs)
