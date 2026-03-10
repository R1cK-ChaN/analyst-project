from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .types import Alert

if TYPE_CHECKING:
    from .types import PortfolioConfig, VolatilitySnapshot


def vix_percentile(current_vix: float, vix_history: list[float]) -> float:
    """0–100 percentile rank of current VIX within historical distribution."""
    if not vix_history:
        return 50.0
    count_below = sum(1 for v in vix_history if v <= current_vix)
    return (count_below / len(vix_history)) * 100.0


def vix_regime(percentile: float) -> str:
    """Classify VIX percentile into regime buckets."""
    if percentile <= 20:
        return "very_calm"
    if percentile <= 60:
        return "normal"
    if percentile <= 80:
        return "elevated"
    return "stress"


def target_volatility(vix_pct: float, vol_min: float, vol_max: float) -> float:
    """Inverse linear mapping: higher VIX percentile → lower target vol.

    At vix_pct=0 → vol_max, at vix_pct=100 → vol_min.
    """
    t = max(0.0, min(vix_pct, 100.0)) / 100.0
    return vol_max - t * (vol_max - vol_min)


def scaling_signal(
    target_vol: float,
    forecast_vol: float,
    scale_min: float,
    scale_max: float,
) -> float:
    """Clamped ratio of target to forecast volatility."""
    if forecast_vol < 1e-10:
        return scale_max
    raw = target_vol / forecast_vol
    return max(scale_min, min(raw, scale_max))


def generate_alerts(
    snapshot: VolatilitySnapshot,
    prev_snapshot: VolatilitySnapshot | None,
    config: PortfolioConfig,
) -> list[Alert]:
    """Generate alerts based on current snapshot and config thresholds."""
    alerts: list[Alert] = []
    now = datetime.now(timezone.utc)

    # Concentration alert: any single asset contributes too much risk
    for rc in snapshot.risk_contributions:
        if rc.marginal_contribution >= config.concentration_threshold:
            alerts.append(Alert(
                alert_type="concentration",
                severity="warning",
                message=(
                    f"{rc.symbol} contributes {rc.marginal_contribution:.0%} of portfolio risk "
                    f"(threshold: {config.concentration_threshold:.0%})"
                ),
                timestamp=now,
            ))

    # Portfolio vol exceeds target
    if snapshot.portfolio_vol_annualized > snapshot.target_vol * 1.2:
        alerts.append(Alert(
            alert_type="vol_breach",
            severity="high",
            message=(
                f"Portfolio volatility {snapshot.portfolio_vol_annualized:.1%} exceeds "
                f"target {snapshot.target_vol:.1%} by more than 20%"
            ),
            timestamp=now,
        ))

    # VIX regime stress
    if snapshot.vix_regime == "stress":
        alerts.append(Alert(
            alert_type="vix_stress",
            severity="high",
            message=f"VIX at {snapshot.vix_level:.1f} (percentile {snapshot.vix_percentile:.0f}) — stress regime",
            timestamp=now,
        ))

    # Vol spike: annualized vol jumped >25% vs previous snapshot
    if prev_snapshot and prev_snapshot.portfolio_vol_annualized > 0:
        vol_change = (
            (snapshot.portfolio_vol_annualized - prev_snapshot.portfolio_vol_annualized)
            / prev_snapshot.portfolio_vol_annualized
        )
        if vol_change > 0.25:
            alerts.append(Alert(
                alert_type="vol_spike",
                severity="warning",
                message=(
                    f"Portfolio volatility spiked {vol_change:.0%} "
                    f"from {prev_snapshot.portfolio_vol_annualized:.1%} to {snapshot.portfolio_vol_annualized:.1%}"
                ),
                timestamp=now,
            ))

    return alerts
