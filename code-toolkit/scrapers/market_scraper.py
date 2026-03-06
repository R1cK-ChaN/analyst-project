"""
scrapers/market_scraper.py

Fetches market prices across all asset classes using yfinance.
Free, no API key needed, covers everything a macro trader watches.

Note: yfinance data is delayed ~15min for most instruments.
For the Analyst agent this is fine — we need daily context, not HFT data.
"""

import time
from datetime import datetime, timezone
from typing import Dict, List

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from storage.event_store import store_market_price


# ─── Symbols to track ───

MACRO_WATCHLIST = {
    # ── US Equities ──
    "equity": {
        "^GSPC":    "S&P 500",
        "^IXIC":    "NASDAQ",
        "^DJI":     "Dow Jones",
        "^RUT":     "Russell 2000",
        "^VIX":     "VIX (Fear Index)",
    },
    
    # ── Global Equities ──
    "global_equity": {
        "^STOXX50E": "Euro Stoxx 50",
        "^N225":     "Nikkei 225",
        "^HSI":      "Hang Seng",
        "000001.SS":  "Shanghai Composite",
        "^STI":      "Straits Times Index (SG)",
    },
    
    # ── FX ──
    "fx": {
        "DX-Y.NYB":  "Dollar Index (DXY)",
        "EURUSD=X":  "EUR/USD",
        "USDJPY=X":  "USD/JPY",
        "GBPUSD=X":  "GBP/USD",
        "USDCNY=X":  "USD/CNY",
        "USDSGD=X":  "USD/SGD",
    },
    
    # ── Bonds (via ETFs as proxy) ──
    "bond": {
        "^TNX":      "10Y Treasury Yield",
        "^TYX":      "30Y Treasury Yield",
        "^FVX":      "5Y Treasury Yield",
        "^IRX":      "13W Treasury Bill",
        "TLT":       "20+ Year Treasury ETF",
        "SHY":       "1-3 Year Treasury ETF",
    },
    
    # ── Commodities ──
    "commodity": {
        "GC=F":      "Gold",
        "SI=F":      "Silver",
        "CL=F":      "WTI Crude Oil",
        "BZ=F":      "Brent Crude",
        "HG=F":      "Copper",
        "NG=F":      "Natural Gas",
    },
    
    # ── Crypto ──
    "crypto": {
        "BTC-USD":   "Bitcoin",
        "ETH-USD":   "Ethereum",
        "SOL-USD":   "Solana",
        "BNB-USD":   "BNB",
    },
}


class MarketScraper:
    """
    Fetches market prices using yfinance.
    Organized by asset class for the Analyst agent.
    """
    
    def __init__(self):
        try:
            import yfinance as yf
            self.yf = yf
        except ImportError:
            print("Install yfinance: pip install yfinance")
            raise
    
    def fetch_all_prices(self) -> Dict[str, List[Dict]]:
        """
        Fetch latest prices for all tracked symbols.
        Returns dict organized by asset class.
        """
        results = {}
        
        for asset_class, symbols in MACRO_WATCHLIST.items():
            results[asset_class] = []
            
            for symbol, name in symbols.items():
                try:
                    ticker = self.yf.Ticker(symbol)
                    info = ticker.fast_info
                    
                    price = info.get("lastPrice", info.get("previousClose", None))
                    prev_close = info.get("previousClose", None)
                    
                    if price is None:
                        # Fallback: get from history
                        hist = ticker.history(period="2d")
                        if not hist.empty:
                            price = hist["Close"].iloc[-1]
                            if len(hist) > 1:
                                prev_close = hist["Close"].iloc[-2]
                    
                    if price is not None:
                        change_pct = None
                        if prev_close and prev_close != 0:
                            change_pct = round((price - prev_close) / prev_close * 100, 2)
                        
                        entry = {
                            "symbol": symbol,
                            "name": name,
                            "price": round(price, 4),
                            "change_pct": change_pct,
                            "asset_class": asset_class,
                        }
                        
                        results[asset_class].append(entry)
                        
                        # Store in DB
                        store_market_price(symbol, asset_class, price, change_pct)
                        
                except Exception as e:
                    print(f"  ✗ {symbol} ({name}): {e}")
                
                time.sleep(0.3)  # gentle rate limiting
        
        return results
    
    def fetch_asset_class(self, asset_class: str) -> List[Dict]:
        """Fetch prices for a specific asset class only."""
        if asset_class not in MACRO_WATCHLIST:
            print(f"Unknown asset class: {asset_class}")
            return []
        
        results = []
        symbols = MACRO_WATCHLIST[asset_class]
        
        for symbol, name in symbols.items():
            try:
                ticker = self.yf.Ticker(symbol)
                hist = ticker.history(period="2d")
                
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
                    prev_close = hist["Close"].iloc[-2] if len(hist) > 1 else None
                    change_pct = None
                    if prev_close and prev_close != 0:
                        change_pct = round((price - prev_close) / prev_close * 100, 2)
                    
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "price": round(price, 4),
                        "change_pct": change_pct,
                    })
                    
                    store_market_price(symbol, asset_class, price, change_pct)
                    
            except Exception as e:
                print(f"  ✗ {symbol}: {e}")
            
            time.sleep(0.3)
        
        return results
    
    def get_cross_asset_summary(self) -> str:
        """
        Build a text summary of cross-asset moves.
        This is what goes into the Analyst agent's daily context.
        """
        all_prices = self.fetch_all_prices()
        
        lines = []
        lines.append("=== CROSS-ASSET MARKET SNAPSHOT ===")
        lines.append(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        
        for asset_class, prices in all_prices.items():
            lines.append(f"\n--- {asset_class.upper().replace('_', ' ')} ---")
            for p in prices:
                change_str = f" ({p['change_pct']:+.2f}%)" if p.get('change_pct') is not None else ""
                lines.append(f"  {p['name']}: {p['price']}{change_str}")
        
        return "\n".join(lines)


if __name__ == "__main__":
    from storage.event_store import init_db
    init_db()
    
    scraper = MarketScraper()
    print(scraper.get_cross_asset_summary())
