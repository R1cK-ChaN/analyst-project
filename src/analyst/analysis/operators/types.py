"""Typed I/O definitions for the operator algebra.

Every operator output must include a ``result_type`` field set to one of
these four canonical types.  This constraint enables artifact caching,
operator composability, and future planner validation.
"""

from __future__ import annotations

# Canonical result types — every operator output must declare one.
SERIES = "series"       # Time series: values + labels + metadata
DATASET = "dataset"     # Tabular data: list of record dicts
METRIC = "metric"       # Single value or small dict of computed values
SIGNAL = "signal"       # Categorical classification (high/low/rising/etc.)

VALID_RESULT_TYPES = frozenset({SERIES, DATASET, METRIC, SIGNAL})
