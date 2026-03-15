"""Typed I/O definitions for the operator algebra.

Every operator output must include a ``result_type`` field set to one of
the canonical types.  Input types are declared per-operator via
``OperatorSpec.input_types`` and validated by ``check_composability()``.

Type hierarchy::

    Dataset  — tabular records (list of dicts)
    Series   — time-indexed numeric values
    Metric   — single value or small dict of computed values
    Signal   — categorical classification (high/low/rising/etc.)
    Text     — LLM-generated prose (terminal type, not composable)
"""

from __future__ import annotations

# Canonical types — used in OperatorSpec.input_types and output_type.
SERIES = "series"
DATASET = "dataset"
METRIC = "metric"
SIGNAL = "signal"
TEXT = "text"

VALID_RESULT_TYPES = frozenset({SERIES, DATASET, METRIC, SIGNAL, TEXT})

# Implicit coercion rules: a value of type A can be used where type B is
# expected.  This keeps the system flexible while catching real errors.
# e.g. a Dataset can be used where a Series is expected (extract column).
_COERCIBLE: dict[str, frozenset[str]] = {
    SERIES: frozenset({SERIES}),
    DATASET: frozenset({DATASET, SERIES}),   # dataset can downcast to series
    METRIC: frozenset({METRIC}),
    SIGNAL: frozenset({SIGNAL}),
    TEXT: frozenset({TEXT}),
}


class TypeMismatchError(TypeError):
    """Raised when an operator receives an input of unexpected type."""


def is_compatible(actual_type: str, expected_type: str) -> bool:
    """Check if ``actual_type`` can satisfy ``expected_type``."""
    if actual_type == expected_type:
        return True
    coercible = _COERCIBLE.get(actual_type, frozenset())
    return expected_type in coercible


def check_composability(
    upstream_output_type: str,
    downstream_input_type: str,
    *,
    upstream_name: str = "",
    downstream_name: str = "",
) -> None:
    """Validate that an upstream output type can feed a downstream input.

    Raises ``TypeMismatchError`` with a clear message if incompatible.
    """
    if is_compatible(upstream_output_type, downstream_input_type):
        return
    up = f" (from '{upstream_name}')" if upstream_name else ""
    down = f" (for '{downstream_name}')" if downstream_name else ""
    raise TypeMismatchError(
        f"Type mismatch: got '{upstream_output_type}'{up}, "
        f"expected '{downstream_input_type}'{down}"
    )
