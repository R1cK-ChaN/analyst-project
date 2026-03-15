"""Analysis operators — deterministic compute functions for the research agent.

Each operator takes structured inputs (value arrays, parameters) and returns
a structured result dict.  Operators run in the host process using numpy/pandas
directly — no Docker overhead.
"""

from .change import compute_change
from .compare import compare_series
from .correlation import compute_correlation
from .registry import OPERATOR_REGISTRY, OperatorSpec, run_operator
from .rolling import rolling_stat
from .spread import compute_spread
from .trend import compute_trend

__all__ = [
    "OPERATOR_REGISTRY",
    "OperatorSpec",
    "compute_change",
    "compute_correlation",
    "compute_spread",
    "compute_trend",
    "compare_series",
    "rolling_stat",
    "run_operator",
]
