from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from analyst.storage.sqlite import SQLiteEngineStore

from .config import load_portfolio_config
from .holdings import load_holdings_from_csv, validate_holdings
from .market_data import fetch_current_vix, fetch_price_history, fetch_vix_history
from .signals import generate_alerts, scaling_signal, target_volatility, vix_percentile, vix_regime
from .types import Alert, PortfolioConfig, PortfolioHolding, RiskContribution, VolatilitySnapshot
from .volatility import annualize_vol, compute_log_returns, ewma_covariance, portfolio_volatility, risk_contributions

logger = logging.getLogger(__name__)

__all__ = [
    "Alert",
    "PortfolioConfig",
    "PortfolioHolding",
    "RiskContribution",
    "VolatilitySnapshot",
    "compute_portfolio_snapshot",
    "load_holdings_from_csv",
    "load_portfolio_config",
    "validate_holdings",
]


def compute_portfolio_snapshot(
    store: SQLiteEngineStore,
    portfolio_id: str = "default",
    config: PortfolioConfig | None = None,
) -> VolatilitySnapshot:
    """Orchestrate the full portfolio risk pipeline.

    1. Load holdings from DB
    2. Fetch price history via yfinance
    3. Compute EWMA covariance and portfolio volatility
    4. Fetch VIX, compute regime and target vol
    5. Compute risk contributions and alerts
    """
    cfg = config or load_portfolio_config()

    # 1. Load holdings
    rows = store.list_portfolio_holdings(portfolio_id=portfolio_id)
    if not rows:
        raise RuntimeError(f"No holdings found for portfolio '{portfolio_id}'. Import holdings first.")

    holdings = [
        PortfolioHolding(
            symbol=r["symbol"],
            name=r["name"],
            asset_class=r["asset_class"],
            weight=r["weight"],
            notional=r["notional"],
        )
        for r in rows
    ]
    symbols = [h.symbol for h in holdings]
    weights = np.array([h.weight for h in holdings])

    # 2. Fetch price history
    price_data = fetch_price_history(symbols, lookback_days=cfg.lookback_days)
    if not price_data or any(sym not in price_data for sym in symbols):
        missing = [s for s in symbols if s not in price_data]
        raise RuntimeError(f"Missing price data for: {missing}")

    # Build aligned price matrix
    n_obs = min(len(price_data[sym]) for sym in symbols)
    prices = np.column_stack([
        np.array([price_data[sym][i][1] for i in range(n_obs)])
        for sym in symbols
    ])

    # 3. EWMA covariance and portfolio vol
    returns = compute_log_returns(prices)
    cov = ewma_covariance(returns, lam=cfg.ewma_lambda)
    daily_vol = portfolio_volatility(weights, cov)
    ann_vol = annualize_vol(daily_vol)

    # 4. VIX and regime
    current_vix = fetch_current_vix()
    vix_hist = fetch_vix_history(lookback_years=cfg.vix_lookback_years)
    vix_values = [v for _, v in vix_hist]
    vix_pct = vix_percentile(current_vix, vix_values)
    regime = vix_regime(vix_pct)
    tgt_vol = target_volatility(vix_pct, cfg.vol_min, cfg.vol_max)
    scale = scaling_signal(tgt_vol, ann_vol, cfg.scale_min, cfg.scale_max)

    # 5. Risk contributions
    rc_fractions = risk_contributions(weights, cov)
    standalone_vols = np.sqrt(np.diag(cov)) * np.sqrt(252)
    risk_contribs = [
        RiskContribution(
            symbol=holdings[i].symbol,
            name=holdings[i].name,
            weight=holdings[i].weight,
            marginal_contribution=float(rc_fractions[i]),
            standalone_vol=float(standalone_vols[i]),
        )
        for i in range(len(holdings))
    ]

    now = datetime.now(timezone.utc)
    snapshot = VolatilitySnapshot(
        as_of=now,
        portfolio_vol_annualized=ann_vol,
        portfolio_vol_daily=daily_vol,
        target_vol=tgt_vol,
        scale_factor=scale,
        vix_level=current_vix,
        vix_percentile=vix_pct,
        vix_regime=regime,
        risk_contributions=risk_contribs,
        alerts=[],
    )

    # Get previous snapshot for spike detection
    prev_raw = store.latest_vol_snapshot(portfolio_id=portfolio_id)
    prev_snapshot: VolatilitySnapshot | None = None
    if prev_raw:
        prev_snapshot = VolatilitySnapshot(
            as_of=datetime.fromisoformat(prev_raw["as_of"]),
            portfolio_vol_annualized=prev_raw["portfolio_vol_annualized"],
            portfolio_vol_daily=prev_raw["portfolio_vol_daily"],
            target_vol=prev_raw["target_vol"],
            scale_factor=prev_raw["scale_factor"],
            vix_level=prev_raw["vix_level"],
            vix_percentile=prev_raw["vix_percentile"],
            vix_regime=prev_raw["vix_regime"],
        )

    alerts = generate_alerts(snapshot, prev_snapshot, cfg)

    # Reconstruct with alerts
    snapshot = VolatilitySnapshot(
        as_of=now,
        portfolio_vol_annualized=ann_vol,
        portfolio_vol_daily=daily_vol,
        target_vol=tgt_vol,
        scale_factor=scale,
        vix_level=current_vix,
        vix_percentile=vix_pct,
        vix_regime=regime,
        risk_contributions=risk_contribs,
        alerts=alerts,
    )

    # Persist snapshot and alerts
    store.save_vol_snapshot(
        portfolio_id=portfolio_id,
        snapshot_json=snapshot.to_dict(),
    )
    for alert in alerts:
        store.save_portfolio_alert(
            portfolio_id=portfolio_id,
            alert_type=alert.alert_type,
            severity=alert.severity,
            message=alert.message,
        )

    return snapshot
