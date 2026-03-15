"""Tests for analysis operators and the run_analysis tool."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyst.analysis.operators import (
    OPERATOR_REGISTRY,
    compute_change,
    compute_correlation,
    compute_spread,
    compute_trend,
    compare_series,
    rolling_stat,
    run_operator,
)
from analyst.storage import SQLiteEngineStore
from analyst.tools._analysis_operators import AnalysisOperatorHandler, build_analysis_operator_tool


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestOperatorRegistry(unittest.TestCase):
    def test_all_6_operators_registered(self):
        expected = {"trend", "change", "rolling_stat", "compare", "correlation", "spread"}
        self.assertEqual(set(OPERATOR_REGISTRY.keys()), expected)

    def test_run_unknown_operator_raises(self):
        with self.assertRaises(KeyError):
            run_operator("nonexistent", {})


# ---------------------------------------------------------------------------
# compute_trend
# ---------------------------------------------------------------------------

class TestComputeTrend(unittest.TestCase):
    def test_rising_trend(self):
        r = compute_trend(inputs={"values": [1, 2, 3, 4, 5]}, parameters={})
        self.assertEqual(r["direction"], "rising")
        self.assertGreater(r["slope"], 0)
        self.assertEqual(r["n_points"], 5)

    def test_falling_trend(self):
        r = compute_trend(inputs={"values": [5, 4, 3, 2, 1]}, parameters={})
        self.assertEqual(r["direction"], "falling")

    def test_flat_trend(self):
        r = compute_trend(inputs={"values": [3, 3, 3, 3]}, parameters={})
        self.assertEqual(r["direction"], "flat")

    def test_window_parameter(self):
        r = compute_trend(inputs={"values": [1, 2, 3, 10, 20, 30]}, parameters={"window": 3})
        self.assertEqual(r["n_points"], 3)

    def test_missing_values_returns_error(self):
        r = compute_trend(inputs={}, parameters={})
        self.assertIn("error", r)

    def test_single_value_returns_error(self):
        r = compute_trend(inputs={"values": [5]}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# compute_change
# ---------------------------------------------------------------------------

class TestComputeChange(unittest.TestCase):
    def test_absolute_change(self):
        r = compute_change(inputs={"values": [10, 12, 15, 13]}, parameters={})
        self.assertEqual(r["mode"], "absolute")
        self.assertEqual(len(r["changes"]), 3)

    def test_percent_change(self):
        r = compute_change(inputs={"values": [100, 110, 121]}, parameters={"mode": "percent"})
        self.assertEqual(r["mode"], "percent")
        self.assertAlmostEqual(r["changes"][0], 10.0, places=1)

    def test_period_parameter(self):
        r = compute_change(inputs={"values": [10, 20, 30, 40]}, parameters={"period": 2})
        self.assertEqual(len(r["changes"]), 2)

    def test_missing_values(self):
        r = compute_change(inputs={}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# rolling_stat
# ---------------------------------------------------------------------------

class TestRollingStat(unittest.TestCase):
    def test_rolling_mean(self):
        r = rolling_stat(inputs={"values": [1, 2, 3, 4, 5]}, parameters={"window": 3, "stat": "mean"})
        self.assertEqual(r["n_points"], 3)
        self.assertAlmostEqual(r["values"][0], 2.0)

    def test_rolling_std(self):
        r = rolling_stat(inputs={"values": [1, 1, 1, 1]}, parameters={"window": 2, "stat": "std"})
        self.assertAlmostEqual(r["latest"], 0.0)

    def test_invalid_stat(self):
        r = rolling_stat(inputs={"values": [1, 2, 3]}, parameters={"stat": "invalid"})
        self.assertIn("error", r)

    def test_window_too_large(self):
        r = rolling_stat(inputs={"values": [1, 2]}, parameters={"window": 5})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# compare_series
# ---------------------------------------------------------------------------

class TestCompareSeries(unittest.TestCase):
    def test_basic_compare(self):
        r = compare_series(
            inputs={"series_a": [10, 20, 30], "series_b": [5, 15, 25]},
            parameters={"label_a": "CPI", "label_b": "Wages"},
        )
        self.assertIn("CPI", r["summary"])
        self.assertIn("Wages", r["summary"])
        self.assertEqual(r["difference"]["latest"], 5.0)

    def test_missing_series(self):
        r = compare_series(inputs={"series_a": [1, 2]}, parameters={})
        self.assertIn("error", r)

    def test_unequal_lengths_aligned(self):
        r = compare_series(
            inputs={"series_a": [1, 2, 3, 4], "series_b": [10, 20]},
            parameters={},
        )
        self.assertEqual(r["n_points"], 2)


# ---------------------------------------------------------------------------
# compute_correlation
# ---------------------------------------------------------------------------

class TestComputeCorrelation(unittest.TestCase):
    def test_perfect_positive(self):
        r = compute_correlation(
            inputs={"series_a": [1, 2, 3, 4, 5], "series_b": [2, 4, 6, 8, 10]},
            parameters={},
        )
        self.assertAlmostEqual(r["correlation"], 1.0, places=3)
        self.assertEqual(r["strength"], "strong")
        self.assertEqual(r["direction"], "positive")

    def test_perfect_negative(self):
        r = compute_correlation(
            inputs={"series_a": [1, 2, 3, 4, 5], "series_b": [10, 8, 6, 4, 2]},
            parameters={},
        )
        self.assertAlmostEqual(r["correlation"], -1.0, places=3)
        self.assertEqual(r["direction"], "negative")

    def test_too_few_points(self):
        r = compute_correlation(
            inputs={"series_a": [1, 2], "series_b": [3, 4]},
            parameters={},
        )
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# compute_spread
# ---------------------------------------------------------------------------

class TestComputeSpread(unittest.TestCase):
    def test_basic_spread(self):
        r = compute_spread(
            inputs={"series_a": [10, 11, 12, 13], "series_b": [5, 5, 5, 5]},
            parameters={"label_a": "10Y", "label_b": "2Y"},
        )
        self.assertEqual(r["current_spread"], 8.0)
        self.assertIn("z_score", r)
        self.assertIn("signal", r)

    def test_missing_series(self):
        r = compute_spread(inputs={"series_a": [1]}, parameters={})
        self.assertIn("error", r)


# ---------------------------------------------------------------------------
# Tool handler + builder
# ---------------------------------------------------------------------------

class TestAnalysisOperatorTool(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteEngineStore(db_path=Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_handler_dispatches_to_operator(self):
        handler = AnalysisOperatorHandler(self.store)
        r = handler({
            "operator": "trend",
            "inputs": {"values": [1, 2, 3, 4, 5]},
        })
        self.assertEqual(r["direction"], "rising")

    def test_handler_unknown_operator(self):
        handler = AnalysisOperatorHandler(self.store)
        r = handler({"operator": "nonexistent", "inputs": {}})
        self.assertIn("error", r)

    def test_handler_empty_operator(self):
        handler = AnalysisOperatorHandler(self.store)
        r = handler({"operator": "", "inputs": {}})
        self.assertIn("error", r)

    def test_handler_auto_caches_result(self):
        handler = AnalysisOperatorHandler(self.store)
        handler({
            "operator": "trend",
            "inputs": {"values": [1, 2, 3, 4, 5]},
        })
        artifacts = self.store.list_artifacts_by_type("trend")
        self.assertEqual(len(artifacts), 1)

    def test_build_tool_schema(self):
        tool = build_analysis_operator_tool(self.store)
        self.assertEqual(tool.name, "run_analysis")
        self.assertIn("operator", tool.parameters["required"])
        self.assertIn("inputs", tool.parameters["required"])
        self.assertIn("trend", tool.description)

    def test_handler_without_store_still_works(self):
        handler = AnalysisOperatorHandler(store=None)
        r = handler({
            "operator": "change",
            "inputs": {"values": [10, 20, 30]},
        })
        self.assertEqual(r["operator"], "change")


if __name__ == "__main__":
    unittest.main()
