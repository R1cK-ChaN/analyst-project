"""Analysis operators — deterministic compute functions for the research agent.

13 operators across 6 categories, all with typed I/O (Series/Dataset/Metric/Signal).
Operators run in the host process using numpy — no Docker overhead.
"""

from .align import align_series
from .combine import combine_series
from .compare import compare_series
from .correlation import compute_correlation
from .difference import difference
from .fetch_dataset import fetch_dataset
from .fetch_series import fetch_series
from .pct_change import pct_change
from .registry import OPERATOR_REGISTRY, OperatorSpec, run_operator
from .regression import regression
from .resample import resample_series
from .rolling import rolling_stat
from .threshold import threshold_signal
from .trend import compute_trend
from .types import DATASET, METRIC, SERIES, SIGNAL

__all__ = [
    "DATASET",
    "METRIC",
    "OPERATOR_REGISTRY",
    "OperatorSpec",
    "SERIES",
    "SIGNAL",
    "align_series",
    "combine_series",
    "compare_series",
    "compute_correlation",
    "compute_trend",
    "difference",
    "fetch_dataset",
    "fetch_series",
    "pct_change",
    "regression",
    "resample_series",
    "rolling_stat",
    "run_operator",
    "threshold_signal",
]
