"""Unit tests for portfolio volatility computations."""
from __future__ import annotations

import math
import unittest

import numpy as np

from analyst.portfolio.volatility import (
    annualize_vol,
    compute_log_returns,
    ewma_covariance,
    portfolio_volatility,
    risk_contributions,
)


class TestComputeLogReturns(unittest.TestCase):
    def test_basic(self):
        prices = np.array([[100.0, 200.0], [110.0, 190.0], [105.0, 195.0]])
        ret = compute_log_returns(prices)
        self.assertEqual(ret.shape, (2, 2))
        np.testing.assert_allclose(ret[0, 0], math.log(110 / 100), atol=1e-10)
        np.testing.assert_allclose(ret[0, 1], math.log(190 / 200), atol=1e-10)

    def test_single_asset(self):
        prices = np.array([[50.0], [55.0], [52.0]])
        ret = compute_log_returns(prices)
        self.assertEqual(ret.shape, (2, 1))


class TestEWMACovariance(unittest.TestCase):
    def test_shape(self):
        returns = np.random.randn(100, 3) * 0.01
        cov = ewma_covariance(returns, lam=0.94)
        self.assertEqual(cov.shape, (3, 3))

    def test_symmetric(self):
        returns = np.random.randn(50, 2) * 0.01
        cov = ewma_covariance(returns)
        np.testing.assert_allclose(cov, cov.T, atol=1e-14)

    def test_positive_semidefinite(self):
        returns = np.random.randn(100, 4) * 0.01
        cov = ewma_covariance(returns)
        eigenvalues = np.linalg.eigvalsh(cov)
        self.assertTrue(np.all(eigenvalues >= -1e-12))


class TestPortfolioVolatility(unittest.TestCase):
    def test_single_asset(self):
        cov = np.array([[0.0004]])  # daily var = 0.04%
        weights = np.array([1.0])
        vol = portfolio_volatility(weights, cov)
        self.assertAlmostEqual(vol, 0.02, places=6)

    def test_equal_weight_uncorrelated(self):
        # Two uncorrelated assets with same variance
        cov = np.array([[0.0004, 0.0], [0.0, 0.0004]])
        weights = np.array([0.5, 0.5])
        vol = portfolio_volatility(weights, cov)
        expected = math.sqrt(0.25 * 0.0004 + 0.25 * 0.0004)
        self.assertAlmostEqual(vol, expected, places=8)


class TestRiskContributions(unittest.TestCase):
    def test_sums_to_one(self):
        cov = np.array([[0.0004, 0.0001], [0.0001, 0.0009]])
        weights = np.array([0.6, 0.4])
        rc = risk_contributions(weights, cov)
        self.assertAlmostEqual(rc.sum(), 1.0, places=8)

    def test_single_asset(self):
        cov = np.array([[0.0004]])
        weights = np.array([1.0])
        rc = risk_contributions(weights, cov)
        self.assertAlmostEqual(rc[0], 1.0, places=8)

    def test_zero_weights(self):
        cov = np.array([[0.0004, 0.0001], [0.0001, 0.0009]])
        weights = np.array([0.0, 0.0])
        rc = risk_contributions(weights, cov)
        np.testing.assert_allclose(rc, [0.0, 0.0])


class TestAnnualizeVol(unittest.TestCase):
    def test_default(self):
        daily = 0.01
        ann = annualize_vol(daily)
        self.assertAlmostEqual(ann, 0.01 * math.sqrt(252), places=8)

    def test_custom_days(self):
        daily = 0.02
        ann = annualize_vol(daily, trading_days=365)
        self.assertAlmostEqual(ann, 0.02 * math.sqrt(365), places=8)


if __name__ == "__main__":
    unittest.main()
