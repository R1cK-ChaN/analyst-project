"""Unit tests for portfolio signal computations."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from analyst.portfolio.signals import (
    generate_alerts,
    scaling_signal,
    target_volatility,
    vix_percentile,
    vix_regime,
)
from analyst.portfolio.types import (
    Alert,
    PortfolioConfig,
    RiskContribution,
    VolatilitySnapshot,
)


class TestVixPercentile(unittest.TestCase):
    def test_at_maximum(self):
        history = [10.0, 15.0, 20.0, 25.0, 30.0]
        pct = vix_percentile(30.0, history)
        self.assertAlmostEqual(pct, 100.0)

    def test_at_minimum(self):
        history = [10.0, 15.0, 20.0, 25.0, 30.0]
        pct = vix_percentile(5.0, history)
        self.assertAlmostEqual(pct, 0.0)

    def test_median(self):
        history = list(range(1, 101))
        pct = vix_percentile(50, history)
        self.assertAlmostEqual(pct, 50.0)

    def test_empty_history(self):
        pct = vix_percentile(20.0, [])
        self.assertAlmostEqual(pct, 50.0)


class TestVixRegime(unittest.TestCase):
    def test_very_calm(self):
        self.assertEqual(vix_regime(10), "very_calm")
        self.assertEqual(vix_regime(20), "very_calm")

    def test_normal(self):
        self.assertEqual(vix_regime(40), "normal")
        self.assertEqual(vix_regime(60), "normal")

    def test_elevated(self):
        self.assertEqual(vix_regime(70), "elevated")
        self.assertEqual(vix_regime(80), "elevated")

    def test_stress(self):
        self.assertEqual(vix_regime(81), "stress")
        self.assertEqual(vix_regime(100), "stress")


class TestTargetVolatility(unittest.TestCase):
    def test_zero_percentile(self):
        tv = target_volatility(0.0, 0.08, 0.20)
        self.assertAlmostEqual(tv, 0.20)

    def test_hundred_percentile(self):
        tv = target_volatility(100.0, 0.08, 0.20)
        self.assertAlmostEqual(tv, 0.08)

    def test_fifty_percentile(self):
        tv = target_volatility(50.0, 0.08, 0.20)
        self.assertAlmostEqual(tv, 0.14)

    def test_clamped(self):
        tv = target_volatility(150.0, 0.08, 0.20)
        self.assertAlmostEqual(tv, 0.08)


class TestScalingSignal(unittest.TestCase):
    def test_equal_vols(self):
        s = scaling_signal(0.14, 0.14, 0.25, 2.0)
        self.assertAlmostEqual(s, 1.0)

    def test_high_forecast(self):
        s = scaling_signal(0.10, 0.20, 0.25, 2.0)
        self.assertAlmostEqual(s, 0.5)

    def test_low_forecast(self):
        s = scaling_signal(0.20, 0.05, 0.25, 2.0)
        # 0.20/0.05 = 4.0, clamped to 2.0
        self.assertAlmostEqual(s, 2.0)

    def test_near_zero_forecast(self):
        s = scaling_signal(0.10, 0.0, 0.25, 2.0)
        self.assertAlmostEqual(s, 2.0)

    def test_floor(self):
        s = scaling_signal(0.01, 0.50, 0.25, 2.0)
        # 0.01/0.50 = 0.02, clamped to 0.25
        self.assertAlmostEqual(s, 0.25)


class TestGenerateAlerts(unittest.TestCase):
    def _make_snapshot(self, **overrides) -> VolatilitySnapshot:
        defaults = dict(
            as_of=datetime.now(timezone.utc),
            portfolio_vol_annualized=0.14,
            portfolio_vol_daily=0.0088,
            target_vol=0.14,
            scale_factor=1.0,
            vix_level=18.0,
            vix_percentile=45.0,
            vix_regime="normal",
            risk_contributions=[],
            alerts=[],
        )
        defaults.update(overrides)
        return VolatilitySnapshot(**defaults)

    def test_no_alerts_normal(self):
        snap = self._make_snapshot()
        config = PortfolioConfig()
        alerts = generate_alerts(snap, None, config)
        self.assertEqual(len(alerts), 0)

    def test_concentration_alert(self):
        rc = RiskContribution(
            symbol="NVDA", name="NVIDIA", weight=0.30,
            marginal_contribution=0.45, standalone_vol=0.50,
        )
        snap = self._make_snapshot(risk_contributions=[rc])
        config = PortfolioConfig(concentration_threshold=0.40)
        alerts = generate_alerts(snap, None, config)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, "concentration")

    def test_vol_breach_alert(self):
        snap = self._make_snapshot(
            portfolio_vol_annualized=0.25,
            target_vol=0.14,
        )
        config = PortfolioConfig()
        alerts = generate_alerts(snap, None, config)
        types = [a.alert_type for a in alerts]
        self.assertIn("vol_breach", types)

    def test_stress_alert(self):
        snap = self._make_snapshot(
            vix_level=35.0,
            vix_percentile=92.0,
            vix_regime="stress",
        )
        config = PortfolioConfig()
        alerts = generate_alerts(snap, None, config)
        types = [a.alert_type for a in alerts]
        self.assertIn("vix_stress", types)

    def test_vol_spike_alert(self):
        prev = self._make_snapshot(portfolio_vol_annualized=0.10)
        snap = self._make_snapshot(portfolio_vol_annualized=0.15)
        config = PortfolioConfig()
        alerts = generate_alerts(snap, prev, config)
        types = [a.alert_type for a in alerts]
        self.assertIn("vol_spike", types)


if __name__ == "__main__":
    unittest.main()
