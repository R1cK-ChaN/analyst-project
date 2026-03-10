from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_price_history(
    symbols: list[str],
    lookback_days: int = 252,
) -> dict[str, list[tuple[str, float]]]:
    """Fetch adjusted close prices for *symbols* over *lookback_days*.

    Returns {symbol: [(date_str, price), ...]} with inner-join on dates
    (only dates where all symbols have data).
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(lookback_days * 1.6))  # extra margin for weekends/holidays

    try:
        data = yf.download(
            symbols,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        logger.warning("yfinance download failed: %s", exc)
        return {}

    if data.empty:
        return {}

    # yf.download returns multi-level columns for multiple tickers
    if len(symbols) == 1:
        close = data[["Close"]].copy()
        close.columns = symbols
    else:
        close = data["Close"][symbols].copy()

    # Inner join: drop rows with any NaN
    close = close.dropna()

    # Trim to requested lookback
    close = close.iloc[-lookback_days:]

    result: dict[str, list[tuple[str, float]]] = {}
    for sym in symbols:
        result[sym] = [
            (idx.strftime("%Y-%m-%d"), float(row[sym]))
            for idx, row in close.iterrows()
        ]
    return result


def fetch_vix_history(lookback_years: int = 5) -> list[tuple[str, float]]:
    """Fetch VIX close history over *lookback_years*."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_years * 365)

    try:
        data = yf.download(
            "^VIX",
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )
    except Exception as exc:
        logger.warning("yfinance VIX fetch failed: %s", exc)
        return []

    if data.empty:
        return []

    close = data["Close"].dropna()
    return [(idx.strftime("%Y-%m-%d"), float(val)) for idx, val in close.items()]


def fetch_current_vix() -> float:
    """Fetch the most recent VIX close."""
    try:
        ticker = yf.Ticker("^VIX")
        hist = ticker.history(period="5d")
        if hist.empty:
            raise RuntimeError("No VIX data returned")
        return float(hist["Close"].iloc[-1])
    except Exception as exc:
        logger.warning("yfinance current VIX fetch failed: %s", exc)
        raise
