from __future__ import annotations

import math

import numpy as np


def compute_log_returns(prices: np.ndarray) -> np.ndarray:
    """T×N prices → (T-1)×N log returns."""
    return np.diff(np.log(prices), axis=0)


def ewma_covariance(returns: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """Exponentially weighted moving average covariance matrix (N×N).

    Uses RiskMetrics-style EWMA: Σ_t = λ Σ_{t-1} + (1-λ) r_t r_t^T
    """
    t, n = returns.shape
    cov = np.zeros((n, n))
    for i in range(t):
        r = returns[i : i + 1]  # 1×N
        cov = lam * cov + (1 - lam) * (r.T @ r)
    return cov


def portfolio_volatility(weights: np.ndarray, cov: np.ndarray) -> float:
    """Portfolio daily volatility: σ_p = √(w^T Σ w)."""
    variance = float(weights @ cov @ weights)
    return math.sqrt(max(variance, 0.0))


def risk_contributions(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Fractional risk contributions: RC_i = w_i (Σ w)_i / σ_p^2.

    Returns array of length N summing to ~1.0.
    """
    sigma_w = cov @ weights  # N-vector
    port_var = float(weights @ sigma_w)
    if port_var < 1e-14:
        return np.zeros_like(weights)
    rc = (weights * sigma_w) / port_var
    return rc


def annualize_vol(daily_vol: float, trading_days: int = 252) -> float:
    """Annualize daily volatility."""
    return daily_vol * math.sqrt(trading_days)
