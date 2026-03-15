"""Tests for the 13 analysis operators, registry, typed I/O, and run_analysis tool."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyst.analysis.operators import (
    OPERATOR_REGISTRY,
    TypeMismatchError,
    check_composability,
    is_compatible,
    run_operator,
    validate_chain,
    compute_trend,
    pct_change,
    rolling_stat,
    compare_series,
    compute_correlation,
    difference,
    regression,
    resample_series,
    align_series,
    combine_series,
    threshold_signal,
    fetch_series,
    fetch_dataset,
)
from analyst.storage import SQLiteEngineStore
from analyst.tools._analysis_operators import AnalysisOperatorHandler, build_analysis_operator_tool


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestOperatorRegistry(unittest.TestCase):
    def test_all_13_operators_registered(self):
        expected = {
            "trend", "pct_change", "rolling_stat", "compare", "correlation",
            "difference", "regression", "resample", "align", "combine",
            "threshold_signal", "fetch_series", "fetch_dataset",
        }
        self.assertEqual(set(OPERATOR_REGISTRY.keys()), expected)

    def test_run_unknown_operator_raises(self):
        with self.assertRaises(KeyError):
            run_operator("nonexistent", {})

    def test_every_operator_has_output_type(self):
        for name, spec in OPERATOR_REGISTRY.items():
            self.assertIn(spec.output_type, ("series", "dataset", "metric", "signal", "dict"),
                          f"Operator {name} has unexpected output_type: {spec.output_type}")


# ---------------------------------------------------------------------------
# Type System — composability and validation
# ---------------------------------------------------------------------------

class TestTypeSystem(unittest.TestCase):
    def test_series_compatible_with_series(self):
        self.assertTrue(is_compatible("series", "series"))

    def test_dataset_compatible_with_series(self):
        self.assertTrue(is_compatible("dataset", "series"))

    def test_metric_not_compatible_with_series(self):
        self.assertFalse(is_compatible("metric", "series"))

    def test_signal_not_compatible_with_series(self):
        self.assertFalse(is_compatible("signal", "series"))

    def test_check_composability_passes(self):
        check_composability("series", "series")  # should not raise

    def test_check_composability_raises(self):
        with self.assertRaises(TypeMismatchError):
            check_composability("metric", "series", upstream_name="trend", downstream_name="pct_change")

    def test_validate_chain_compatible(self):
        pct = OPERATOR_REGISTRY["pct_change"]
        trend = OPERATOR_REGISTRY["trend"]
        validate_chain(pct, trend, via_input="values")  # series → series: ok

    def test_validate_chain_incompatible(self):
        trend = OPERATOR_REGISTRY["trend"]
        corr = OPERATOR_REGISTRY["correlation"]
        with self.assertRaises(TypeMismatchError):
            validate_chain(trend, corr, via_input="series_a")  # metric → series: fail

    def test_every_operator_has_input_types_dict(self):
        for name, spec in OPERATOR_REGISTRY.items():
            self.assertIsInstance(spec.input_types, dict, f"{name} missing input_types")

    def test_all_input_types_are_valid(self):
        valid = {"series", "dataset", "metric", "signal", "text"}
        for name, spec in OPERATOR_REGISTRY.items():
            for input_name, input_type in spec.input_types.items():
                self.assertIn(input_type, valid, f"{name}.{input_name} has invalid type '{input_type}'")

    def test_run_operator_validates_typed_upstream_output(self):
        """When an input is an upstream operator output dict with result_type, validate it."""
        metric_output = {"result_type": "metric", "value": 42}
        with self.assertRaises(TypeMismatchError):
            # trend expects values: series, but we pass a metric output
            run_operator("trend", {"values": metric_output})

    def test_run_operator_accepts_compatible_typed_input(self):
        series_output = {"result_type": "series", "values": [1, 2, 3]}
        # This should NOT raise — series is compatible with series
        # But the actual operator expects a list, not a dict, so it will return an error
        # (operator-level validation, not type-level)
        r = run_operator("trend", {"values": series_output})
        # The type check passes, but operator gets a dict instead of list → error
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# Typed I/O — every operator result has result_type
# ---------------------------------------------------------------------------

class TestTypedIO(unittest.TestCase):
    def test_trend_returns_metric(self):
        r = compute_trend(inputs={"values": [1, 2, 3]}, parameters={})
        self.assertEqual(r["result_type"], "metric")

    def test_pct_change_returns_series(self):
        r = pct_change(inputs={"values": [100, 110, 121]}, parameters={})
        self.assertEqual(r["result_type"], "series")

    def test_rolling_returns_series(self):
        r = rolling_stat(inputs={"values": [1, 2, 3, 4]}, parameters={"window": 2})
        self.assertEqual(r["result_type"], "series")

    def test_compare_returns_metric(self):
        r = compare_series(inputs={"series_a": [1, 2, 3], "series_b": [2, 3, 4]}, parameters={})
        self.assertEqual(r["result_type"], "metric")

    def test_correlation_returns_metric(self):
        r = compute_correlation(inputs={"series_a": [1, 2, 3, 4], "series_b": [2, 4, 6, 8]}, parameters={})
        self.assertEqual(r["result_type"], "metric")

    def test_difference_returns_metric(self):
        r = difference(inputs={"series_a": [10, 11], "series_b": [5, 5]}, parameters={})
        self.assertEqual(r["result_type"], "metric")

    def test_regression_returns_metric(self):
        r = regression(inputs={"series_x": [1, 2, 3, 4], "series_y": [2, 4, 6, 8]}, parameters={})
        self.assertEqual(r["result_type"], "metric")

    def test_resample_returns_series(self):
        r = resample_series(inputs={"values": [1, 2, 3, 4, 5, 6]}, parameters={"factor": 3})
        self.assertEqual(r["result_type"], "series")

    def test_align_returns_dataset(self):
        r = align_series(inputs={"values_a": [1, 2, 3], "values_b": [4, 5]}, parameters={})
        self.assertEqual(r["result_type"], "dataset")

    def test_combine_returns_series(self):
        r = combine_series(inputs={"series_list": [[1, 2, 3], [4, 5, 6]]}, parameters={})
        self.assertEqual(r["result_type"], "series")

    def test_threshold_returns_signal(self):
        r = threshold_signal(inputs={"values": [1, 2, 3, 4]}, parameters={"threshold": 3})
        self.assertEqual(r["result_type"], "signal")


# ---------------------------------------------------------------------------
# compute_trend
# ---------------------------------------------------------------------------

class TestComputeTrend(unittest.TestCase):
    def test_rising(self):
        r = compute_trend(inputs={"values": [1, 2, 3, 4, 5]}, parameters={})
        self.assertEqual(r["direction"], "rising")

    def test_falling(self):
        r = compute_trend(inputs={"values": [5, 4, 3, 2, 1]}, parameters={})
        self.assertEqual(r["direction"], "falling")

    def test_missing_values(self):
        r = compute_trend(inputs={}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# pct_change (renamed from change)
# ---------------------------------------------------------------------------

class TestPctChange(unittest.TestCase):
    def test_basic(self):
        r = pct_change(inputs={"values": [100, 110, 121]}, parameters={})
        self.assertAlmostEqual(r["values"][0], 10.0, places=1)
        self.assertEqual(r["operator"], "pct_change")

    def test_period_2(self):
        r = pct_change(inputs={"values": [100, 110, 121, 133]}, parameters={"period": 2})
        self.assertEqual(r["n_points"], 2)


# ---------------------------------------------------------------------------
# difference (renamed from spread)
# ---------------------------------------------------------------------------

class TestDifference(unittest.TestCase):
    def test_basic(self):
        r = difference(inputs={"series_a": [10, 11, 12], "series_b": [5, 5, 5]}, parameters={})
        self.assertEqual(r["operator"], "difference")
        self.assertEqual(r["current"], 7.0)
        self.assertIn("z_score", r)


# ---------------------------------------------------------------------------
# regression
# ---------------------------------------------------------------------------

class TestRegression(unittest.TestCase):
    def test_perfect_fit(self):
        r = regression(inputs={"series_x": [1, 2, 3, 4, 5], "series_y": [2, 4, 6, 8, 10]}, parameters={})
        self.assertAlmostEqual(r["beta"], 2.0, places=3)
        self.assertAlmostEqual(r["r_squared"], 1.0, places=3)

    def test_too_few_points(self):
        r = regression(inputs={"series_x": [1, 2], "series_y": [3, 4]}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# resample
# ---------------------------------------------------------------------------

class TestResample(unittest.TestCase):
    def test_mean_resample(self):
        r = resample_series(inputs={"values": [1, 2, 3, 4, 5, 6]}, parameters={"factor": 3, "method": "mean"})
        self.assertEqual(r["n_points"], 2)
        self.assertAlmostEqual(r["values"][0], 2.0)
        self.assertAlmostEqual(r["values"][1], 5.0)

    def test_factor_too_large(self):
        r = resample_series(inputs={"values": [1, 2]}, parameters={"factor": 5})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# align
# ---------------------------------------------------------------------------

class TestAlign(unittest.TestCase):
    def test_label_based_alignment(self):
        r = align_series(inputs={
            "values_a": [1, 2, 3], "labels_a": ["jan", "feb", "mar"],
            "values_b": [10, 20], "labels_b": ["feb", "mar"],
        }, parameters={})
        self.assertEqual(r["n_points"], 2)
        self.assertEqual(r["series_a"], [2, 3])
        self.assertEqual(r["series_b"], [10, 20])

    def test_no_labels_tail_align(self):
        r = align_series(inputs={"values_a": [1, 2, 3, 4], "values_b": [10, 20]}, parameters={})
        self.assertEqual(r["n_points"], 2)


# ---------------------------------------------------------------------------
# combine
# ---------------------------------------------------------------------------

class TestCombine(unittest.TestCase):
    def test_mean_combine(self):
        r = combine_series(inputs={"series_list": [[10, 20, 30], [20, 40, 60]]}, parameters={"method": "mean"})
        self.assertEqual(r["values"], [15.0, 30.0, 45.0])

    def test_weighted_combine(self):
        r = combine_series(
            inputs={"series_list": [[10, 20], [30, 40]]},
            parameters={"method": "weighted", "weights": [0.75, 0.25]},
        )
        self.assertAlmostEqual(r["values"][0], 15.0)

    def test_too_few_series(self):
        r = combine_series(inputs={"series_list": [[1, 2]]}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# threshold_signal
# ---------------------------------------------------------------------------

class TestThresholdSignal(unittest.TestCase):
    def test_above(self):
        r = threshold_signal(inputs={"values": [1, 2, 3, 4]}, parameters={"threshold": 3})
        self.assertEqual(r["signal"], "high")

    def test_below(self):
        r = threshold_signal(inputs={"values": [1, 2, 3, 4]}, parameters={"threshold": 5})
        self.assertEqual(r["signal"], "low")

    def test_crossover_detected(self):
        r = threshold_signal(inputs={"values": [2.5, 3.5]}, parameters={"threshold": 3})
        self.assertIn("crossed_above", r["crossover"])

    def test_missing_threshold(self):
        r = threshold_signal(inputs={"values": [1, 2]}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# fetch_series / fetch_dataset (context-dependent)
# ---------------------------------------------------------------------------

class TestFetchOperators(unittest.TestCase):
    def test_fetch_series_without_store_returns_error(self):
        r = fetch_series(inputs={"series_id": "us_cpi"}, parameters={}, context={})
        self.assertIn("error", r)

    def test_fetch_dataset_without_store_returns_error(self):
        r = fetch_dataset(inputs={"dataset": "calendar"}, parameters={}, context={})
        self.assertIn("error", r)

    def test_fetch_series_missing_id(self):
        r = fetch_series(inputs={}, parameters={}, context={})
        self.assertIn("error", r)

    def test_fetch_dataset_unknown_source(self):
        r = fetch_dataset(inputs={"dataset": "unknown"}, parameters={}, context={"store": None})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

class TestAnalysisOperatorTool(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteEngineStore(db_path=Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_dispatches_trend(self):
        handler = AnalysisOperatorHandler(self.store)
        r = handler({"operator": "trend", "inputs": {"values": [1, 2, 3, 4, 5]}})
        self.assertEqual(r["direction"], "rising")

    def test_dispatches_pct_change(self):
        handler = AnalysisOperatorHandler(self.store)
        r = handler({"operator": "pct_change", "inputs": {"values": [100, 110]}})
        self.assertEqual(r["operator"], "pct_change")

    def test_dispatches_difference(self):
        handler = AnalysisOperatorHandler(self.store)
        r = handler({"operator": "difference", "inputs": {"series_a": [10, 11], "series_b": [5, 5]}})
        self.assertEqual(r["operator"], "difference")

    def test_auto_caches(self):
        handler = AnalysisOperatorHandler(self.store)
        handler({"operator": "trend", "inputs": {"values": [1, 2, 3, 4, 5]}})
        artifacts = self.store.list_artifacts_by_type("trend")
        self.assertEqual(len(artifacts), 1)

    def test_build_tool_lists_all_operators(self):
        tool = build_analysis_operator_tool(self.store)
        self.assertEqual(tool.name, "run_analysis")
        for op in ("trend", "pct_change", "correlation", "regression", "threshold_signal"):
            self.assertIn(op, tool.description)


if __name__ == "__main__":
    unittest.main()
