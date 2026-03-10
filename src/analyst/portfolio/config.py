from __future__ import annotations

import os

from .types import PortfolioConfig


def load_portfolio_config() -> PortfolioConfig:
    """Load PortfolioConfig from env vars with sensible defaults."""
    return PortfolioConfig(
        vol_min=float(os.environ.get("ANALYST_PORTFOLIO_VOL_MIN", "0.08")),
        vol_max=float(os.environ.get("ANALYST_PORTFOLIO_VOL_MAX", "0.20")),
        ewma_lambda=float(os.environ.get("ANALYST_PORTFOLIO_EWMA_LAMBDA", "0.94")),
        lookback_days=int(os.environ.get("ANALYST_PORTFOLIO_LOOKBACK_DAYS", "252")),
        vix_lookback_years=int(os.environ.get("ANALYST_PORTFOLIO_VIX_LOOKBACK_YEARS", "5")),
        scale_min=float(os.environ.get("ANALYST_PORTFOLIO_SCALE_MIN", "0.25")),
        scale_max=float(os.environ.get("ANALYST_PORTFOLIO_SCALE_MAX", "2.0")),
        concentration_threshold=float(os.environ.get("ANALYST_PORTFOLIO_CONCENTRATION_THRESHOLD", "0.40")),
    )
