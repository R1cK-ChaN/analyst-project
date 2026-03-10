from __future__ import annotations

import csv
from pathlib import Path

from .types import PortfolioHolding


def load_holdings_from_csv(path: str | Path) -> list[PortfolioHolding]:
    """Load portfolio holdings from a CSV file.

    Expected columns: symbol, name, asset_class, weight, notional
    """
    path = Path(path)
    holdings: list[PortfolioHolding] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            holdings.append(PortfolioHolding(
                symbol=row["symbol"].strip().upper(),
                name=row["name"].strip(),
                asset_class=row["asset_class"].strip().lower(),
                weight=float(row["weight"]),
                notional=float(row["notional"]),
            ))
    return holdings


def validate_holdings(holdings: list[PortfolioHolding]) -> list[str]:
    """Validate holdings. Returns list of warning messages (empty = OK)."""
    warnings: list[str] = []
    if not holdings:
        warnings.append("No holdings provided.")
        return warnings

    total_weight = sum(h.weight for h in holdings)
    if abs(total_weight - 1.0) > 0.02:
        warnings.append(f"Weights sum to {total_weight:.4f}, expected ~1.0.")

    symbols = [h.symbol for h in holdings]
    if len(symbols) != len(set(symbols)):
        warnings.append("Duplicate symbols found.")

    for h in holdings:
        if h.weight < 0:
            warnings.append(f"{h.symbol}: negative weight {h.weight}.")
        if h.notional < 0:
            warnings.append(f"{h.symbol}: negative notional {h.notional}.")

    return warnings
