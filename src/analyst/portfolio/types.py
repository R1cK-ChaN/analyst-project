from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from analyst.contracts import Serializable


@dataclass(frozen=True)
class PortfolioHolding(Serializable):
    symbol: str
    name: str
    asset_class: str
    weight: float
    notional: float


@dataclass(frozen=True)
class PortfolioConfig(Serializable):
    vol_min: float = 0.08
    vol_max: float = 0.20
    ewma_lambda: float = 0.94
    lookback_days: int = 252
    vix_lookback_years: int = 5
    scale_min: float = 0.25
    scale_max: float = 2.0
    concentration_threshold: float = 0.40


@dataclass(frozen=True)
class RiskContribution(Serializable):
    symbol: str
    name: str
    weight: float
    marginal_contribution: float
    standalone_vol: float


@dataclass(frozen=True)
class Alert(Serializable):
    alert_type: str
    severity: str
    message: str
    timestamp: datetime


@dataclass(frozen=True)
class VolatilitySnapshot(Serializable):
    as_of: datetime
    portfolio_vol_annualized: float
    portfolio_vol_daily: float
    target_vol: float
    scale_factor: float
    vix_level: float
    vix_percentile: float
    vix_regime: str
    risk_contributions: list[RiskContribution] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
