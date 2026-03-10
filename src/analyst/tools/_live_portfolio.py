from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.portfolio import compute_portfolio_snapshot, create_broker_adapter, load_portfolio_config, validate_holdings
from analyst.portfolio.brokers import BrokerAuthError, BrokerConnectionError
from analyst.portfolio.market_data import fetch_current_vix, fetch_vix_history
from analyst.portfolio.signals import scaling_signal, target_volatility, vix_percentile, vix_regime
from analyst.storage.sqlite import SQLiteEngineStore

logger = logging.getLogger(__name__)


def _regime_guidance(regime: str, vix_level: float, pct: float) -> str:
    """Return natural-language guidance the agent can relay or adapt."""
    if regime == "very_calm":
        return (
            f"VIX {vix_level:.0f} is at P{pct:.0f} — very calm. "
            "Market pricing in low volatility; room to carry more risk, "
            "but watch for complacency — low VIX can snap back fast."
        )
    if regime == "normal":
        return (
            f"VIX {vix_level:.0f} is at P{pct:.0f} — normal range. "
            "No urgency to adjust exposure either way. "
            "Standard risk budgets apply."
        )
    if regime == "elevated":
        return (
            f"VIX {vix_level:.0f} is at P{pct:.0f} — elevated. "
            "Market expects above-average moves. Consider trimming "
            "the most volatile positions or hedging tail risk. "
            "Not a crisis, but don't add aggressively."
        )
    return (
        f"VIX {vix_level:.0f} is at P{pct:.0f} — stress regime. "
        "Markets are pricing in significant risk. Reduce gross exposure, "
        "prioritize capital preservation, and wait for vol to mean-revert "
        "before rebuilding risk."
    )


def _build_suggestions(
    scale: float,
    regime: str,
    risk_contribs: list[dict[str, Any]],
    ann_vol: float,
    target_vol: float,
    alerts: list[dict[str, Any]],
) -> list[str]:
    """Generate prioritized, actionable suggestions for the agent."""
    suggestions: list[str] = []

    # Exposure sizing
    if scale < 0.80:
        suggestions.append(
            f"Reduce overall exposure to ~{scale:.0%} of current. "
            f"Portfolio vol ({ann_vol:.1%}) significantly exceeds target ({target_vol:.1%})."
        )
    elif scale < 0.95:
        suggestions.append(
            f"Modestly trim exposure to ~{scale:.0%}. "
            f"Portfolio vol ({ann_vol:.1%}) is running above target ({target_vol:.1%})."
        )
    elif scale > 1.20:
        suggestions.append(
            f"Room to add risk — portfolio vol ({ann_vol:.1%}) is well below "
            f"target ({target_vol:.1%}). Scale factor {scale:.2f}."
        )

    # Concentration — flag positions where risk_share >> weight
    for rc in risk_contribs:
        weight_f = float(rc["weight_raw"])
        risk_f = float(rc["risk_share_raw"])
        if risk_f > weight_f + 0.10 and risk_f > 0.20:
            suggestions.append(
                f"{rc['symbol']} carries {rc['risk_share']} of portfolio risk on only {rc['weight']} weight — "
                f"consider trimming or hedging to bring risk share closer to allocation."
            )

    # Regime-specific
    if regime == "stress" and scale > 0.60:
        suggestions.append(
            "Market in stress regime — even if scale factor allows current sizing, "
            "consider cutting proactively. Correlation spikes in stress make diversification less effective."
        )

    # Relay any alerts
    for a in alerts:
        if a["severity"] == "high":
            suggestions.append(f"Alert: {a['message']}")

    return suggestions


def _risk_summary(
    ann_vol: float,
    target_vol: float,
    scale: float,
    regime: str,
    n_holdings: int,
    top_risk_symbol: str,
    top_risk_pct: float,
) -> str:
    """One-paragraph summary the agent can use directly in conversation."""
    vol_status = "in line with" if abs(ann_vol - target_vol) / target_vol < 0.15 else (
        "above" if ann_vol > target_vol else "below"
    )
    return (
        f"Portfolio annualized vol is {ann_vol:.1%}, {vol_status} the {target_vol:.1%} target. "
        f"VIX regime is {regime}. Scale factor is {scale:.2f} "
        f"({'reduce' if scale < 0.95 else 'hold' if scale <= 1.05 else 'can add'}). "
        f"{n_holdings} positions; largest risk contributor is {top_risk_symbol} at {top_risk_pct:.0%} of total risk."
    )


# ---------------------------------------------------------------------------
# Tool 1: get_portfolio_risk
# ---------------------------------------------------------------------------

class PortfolioRiskHandler:
    """Stateful callable that computes a full portfolio risk snapshot."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self.store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        portfolio_id = str(arguments.get("portfolio_id", "default")).strip()
        config = load_portfolio_config()
        try:
            snapshot = compute_portfolio_snapshot(self.store, portfolio_id, config)
        except Exception as exc:
            logger.warning("Portfolio risk computation failed: %s", exc)
            return {"error": str(exc)}

        # Format for LLM consumption
        scale = snapshot.scale_factor

        risk_contribs = [
            {
                "symbol": rc.symbol,
                "name": rc.name,
                "weight": f"{rc.weight:.0%}",
                "weight_raw": rc.weight,
                "risk_share": f"{rc.marginal_contribution:.0%}",
                "risk_share_raw": rc.marginal_contribution,
                "risk_vs_weight": f"{rc.marginal_contribution - rc.weight:+.0%}",
                "standalone_vol": f"{rc.standalone_vol:.1%}",
                "overweight_risk": rc.marginal_contribution > rc.weight + 0.05,
            }
            for rc in snapshot.risk_contributions
        ]

        alerts = [
            {
                "type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
            }
            for a in snapshot.alerts
        ]

        top_rc = max(risk_contribs, key=lambda x: x["risk_share_raw"]) if risk_contribs else None

        suggestions = _build_suggestions(
            scale, snapshot.vix_regime, risk_contribs,
            snapshot.portfolio_vol_annualized, snapshot.target_vol, alerts,
        )

        summary = _risk_summary(
            snapshot.portfolio_vol_annualized,
            snapshot.target_vol,
            scale,
            snapshot.vix_regime,
            len(risk_contribs),
            top_rc["symbol"] if top_rc else "N/A",
            top_rc["risk_share_raw"] if top_rc else 0.0,
        )

        return {
            "summary": summary,
            "suggestions": suggestions,
            "as_of": snapshot.as_of.isoformat(),
            "portfolio_volatility": {
                "daily": round(snapshot.portfolio_vol_daily, 4),
                "annualized": round(snapshot.portfolio_vol_annualized, 4),
                "annualized_pct": f"{snapshot.portfolio_vol_annualized:.1%}",
            },
            "target_volatility": {
                "value": round(snapshot.target_vol, 4),
                "pct": f"{snapshot.target_vol:.1%}",
            },
            "scale_factor": round(scale, 2),
            "signal": (
                f"reduce exposure to {scale:.0%}" if scale < 0.95
                else f"increase exposure to {scale:.0%}" if scale > 1.05
                else "maintain current exposure"
            ),
            "vix": {
                "level": round(snapshot.vix_level, 1),
                "percentile": round(snapshot.vix_percentile, 1),
                "regime": snapshot.vix_regime,
                "guidance": _regime_guidance(
                    snapshot.vix_regime, snapshot.vix_level, snapshot.vix_percentile,
                ),
            },
            "risk_contributions": risk_contribs,
            "alerts": alerts,
        }


def build_portfolio_risk_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a get_portfolio_risk AgentTool."""
    handler = PortfolioRiskHandler(store)
    return AgentTool(
        name="get_portfolio_risk",
        description=(
            "Compute a full portfolio risk snapshot with actionable suggestions. "
            "Returns portfolio volatility vs target, VIX regime with guidance, "
            "exposure scaling signal, per-asset risk contributions (with risk-vs-weight flags), "
            "and prioritized suggestions. Use when the client asks about portfolio risk, "
            "position sizing, exposure management, whether to add or reduce, or general risk check-in."
        ),
        parameters={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "string",
                    "description": "Portfolio identifier (default: 'default')",
                },
            },
        },
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Tool 2: get_portfolio_holdings
# ---------------------------------------------------------------------------

class PortfolioHoldingsHandler:
    """Stateful callable that returns current portfolio holdings with context."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self.store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        portfolio_id = str(arguments.get("portfolio_id", "default")).strip()
        try:
            rows = self.store.list_portfolio_holdings(portfolio_id=portfolio_id)
        except Exception as exc:
            logger.warning("Portfolio holdings fetch failed: %s", exc)
            return {"error": str(exc)}

        if not rows:
            return {"error": f"No holdings found for portfolio '{portfolio_id}'."}

        total_notional = sum(r["notional"] for r in rows)

        holdings = [
            {
                "symbol": r["symbol"],
                "name": r["name"],
                "asset_class": r["asset_class"],
                "weight": f"{r['weight']:.0%}",
                "weight_raw": r["weight"],
                "notional": r["notional"],
            }
            for r in rows
        ]

        # Diversification context
        asset_class_counts = Counter(r["asset_class"] for r in rows)
        top_holding = max(rows, key=lambda r: r["weight"])
        top3_weight = sum(
            r["weight"] for r in sorted(rows, key=lambda r: r["weight"], reverse=True)[:3]
        )

        if top3_weight > 0.80:
            concentration_note = (
                f"Top 3 holdings make up {top3_weight:.0%} of the portfolio — highly concentrated. "
                "A single position move could drive most of the P&L."
            )
        elif top3_weight > 0.60:
            concentration_note = (
                f"Top 3 holdings make up {top3_weight:.0%} — moderately concentrated."
            )
        else:
            concentration_note = (
                f"Top 3 holdings make up {top3_weight:.0%} — reasonably diversified by weight."
            )

        return {
            "portfolio_id": portfolio_id,
            "holdings_count": len(rows),
            "total_notional": total_notional,
            "diversification": {
                "asset_classes": dict(asset_class_counts),
                "top_holding": f"{top_holding['symbol']} at {top_holding['weight']:.0%}",
                "top_3_weight": f"{top3_weight:.0%}",
                "note": concentration_note,
            },
            "holdings": holdings,
        }


def build_portfolio_holdings_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a get_portfolio_holdings AgentTool."""
    handler = PortfolioHoldingsHandler(store)
    return AgentTool(
        name="get_portfolio_holdings",
        description=(
            "Retrieve current portfolio holdings with diversification context. "
            "Returns symbols, weights, notional values, asset class breakdown, "
            "and concentration analysis. Use when the client asks what's in the portfolio, "
            "allocation, or diversification."
        ),
        parameters={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "string",
                    "description": "Portfolio identifier (default: 'default')",
                },
            },
        },
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Tool 3: get_vix_regime
# ---------------------------------------------------------------------------

class VixRegimeHandler:
    """Stateful callable that returns VIX level, percentile, regime, and guidance."""

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            current = fetch_current_vix()
            vix_hist = fetch_vix_history(lookback_years=5)
            vix_values = [v for _, v in vix_hist]
            pct = vix_percentile(current, vix_values)
            regime = vix_regime(pct)
        except Exception as exc:
            logger.warning("VIX regime fetch failed: %s", exc)
            return {"error": str(exc)}

        # Compute what target vol would be under default config
        config = load_portfolio_config()
        tgt = target_volatility(pct, config.vol_min, config.vol_max)

        guidance = _regime_guidance(regime, current, pct)

        # Recent VIX direction (last value in history vs current)
        direction = ""
        if len(vix_values) >= 5:
            recent_avg = sum(vix_values[-5:]) / 5
            if current > recent_avg * 1.10:
                direction = "rising — VIX is above its 5-day average"
            elif current < recent_avg * 0.90:
                direction = "falling — VIX is below its 5-day average"
            else:
                direction = "stable — VIX near its recent average"

        return {
            "vix_level": round(current, 1),
            "vix_percentile": round(pct, 1),
            "regime": regime,
            "direction": direction,
            "regime_description": f"VIX is higher than {pct:.0f}% of readings over the past 5 years",
            "guidance": guidance,
            "implied_target_vol": f"{tgt:.1%}",
            "positioning_hint": (
                "This is a good environment to carry risk." if regime == "very_calm"
                else "Normal positioning appropriate." if regime == "normal"
                else "Consider reducing gross exposure or adding hedges." if regime == "elevated"
                else "Defensive posture. Cut risk, raise cash, wait for vol to subside."
            ),
        }


def build_vix_regime_tool() -> AgentTool:
    """Factory: create a get_vix_regime AgentTool."""
    handler = VixRegimeHandler()
    return AgentTool(
        name="get_vix_regime",
        description=(
            "Fetch the current VIX level, percentile rank, volatility regime, "
            "and actionable guidance for positioning. Lightweight — does not require "
            "portfolio holdings. Use when the client asks about market fear, volatility, "
            "whether it's safe to add risk, or general market conditions."
        ),
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Tool 4: sync_portfolio_from_broker
# ---------------------------------------------------------------------------

class PortfolioSyncHandler:
    """Stateful callable that syncs positions from a broker into the store."""

    def __init__(self, store: SQLiteEngineStore) -> None:
        self.store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        broker = str(arguments.get("broker", "ibkr")).strip().lower()
        account_id = str(arguments.get("account_id", "")).strip()
        portfolio_id = str(arguments.get("portfolio_id", "default")).strip()

        try:
            adapter = create_broker_adapter(broker, account_id=account_id)
            result = adapter.fetch_positions(account_id=account_id)
        except BrokerAuthError as exc:
            logger.warning("Broker auth failed: %s", exc)
            return {"error": str(exc), "error_type": "auth"}
        except BrokerConnectionError as exc:
            logger.warning("Broker connection failed: %s", exc)
            return {"error": str(exc), "error_type": "connection"}
        except ValueError as exc:
            return {"error": str(exc), "error_type": "config"}

        if not result.holdings:
            return {
                "status": "empty",
                "message": f"No positions found in {broker} account {result.account_id}.",
                "skipped": result.skipped,
                "warnings": result.warnings,
            }

        warnings = validate_holdings(result.holdings)
        warnings.extend(result.warnings)

        self.store.replace_portfolio_holdings(
            [
                {
                    "symbol": h.symbol,
                    "name": h.name,
                    "asset_class": h.asset_class,
                    "weight": h.weight,
                    "notional": h.notional,
                }
                for h in result.holdings
            ],
            portfolio_id=portfolio_id,
        )

        holdings_summary = [
            {
                "symbol": h.symbol,
                "name": h.name,
                "asset_class": h.asset_class,
                "weight": f"{h.weight:.1%}",
                "notional": h.notional,
            }
            for h in result.holdings
        ]

        return {
            "status": "synced",
            "broker": result.broker,
            "account_id": result.account_id,
            "portfolio_id": portfolio_id,
            "holdings_count": len(result.holdings),
            "raw_position_count": result.raw_position_count,
            "holdings": holdings_summary,
            "skipped": result.skipped,
            "warnings": warnings,
        }


def build_portfolio_sync_tool(store: SQLiteEngineStore) -> AgentTool:
    """Factory: create a sync_portfolio_from_broker AgentTool."""
    handler = PortfolioSyncHandler(store)
    return AgentTool(
        name="sync_portfolio_from_broker",
        description=(
            "Sync portfolio positions from a broker account (currently supports IBKR). "
            "Fetches live positions from the broker gateway and imports them into the portfolio store. "
            "Requires the IBKR Client Portal Gateway to be running and authenticated. "
            "Use when the client says 'sync my IB positions', 'refresh positions', "
            "'import from broker', or similar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "broker": {
                    "type": "string",
                    "description": "Broker identifier (default: 'ibkr')",
                },
                "account_id": {
                    "type": "string",
                    "description": "Broker account ID (auto-detected if omitted)",
                },
                "portfolio_id": {
                    "type": "string",
                    "description": "Portfolio identifier to save into (default: 'default')",
                },
            },
        },
        handler=handler,
    )
