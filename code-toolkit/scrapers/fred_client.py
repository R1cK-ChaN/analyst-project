"""
scrapers/fred_client.py

FRED (Federal Reserve Economic Data) - FREE API
The most reliable source for US economic data.
Get your free key at: https://fred.stlouisfed.org/docs/api/api_key.html

Covers:
- All major US economic indicators (GDP, CPI, NFP, unemployment, etc.)
- Treasury yields (2Y, 5Y, 10Y, 30Y)
- Fed Funds rate, SOFR
- Fed balance sheet (WALCL)
- M2 money supply
- Breakeven inflation (T5YIE, T10YIE)
- Dollar index proxy (DTWEXBGS)
- Reverse repo (RRPONTSYD)
- Treasury General Account (WTREGEN)
- Credit spreads (BAMLH0A0HYM2)
- And 800,000+ other series

Rate limit: 120 requests per minute (very generous)
"""

import requests
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from storage.event_store import store_indicator


# ─── Get your free key at https://fred.stlouisfed.org/docs/api/api_key.html ───
FRED_API_KEY = os.environ.get("FRED_API_KEY", "YOUR_FRED_API_KEY_HERE")

BASE_URL = "https://api.stlouisfed.org/fred"


# ─── Key series for macro analysis ───

MACRO_SERIES = {
    # ── Inflation ──
    "CPIAUCSL":   {"name": "CPI All Urban (Monthly)", "category": "inflation", "freq": "monthly"},
    "CPILFESL":   {"name": "Core CPI (ex Food & Energy)", "category": "inflation", "freq": "monthly"},
    "PCEPILFE":   {"name": "Core PCE Price Index", "category": "inflation", "freq": "monthly"},
    "T5YIE":      {"name": "5Y Breakeven Inflation", "category": "inflation", "freq": "daily"},
    "T10YIE":     {"name": "10Y Breakeven Inflation", "category": "inflation", "freq": "daily"},
    
    # ── Employment ──
    "UNRATE":     {"name": "Unemployment Rate", "category": "employment", "freq": "monthly"},
    "PAYEMS":     {"name": "Total Nonfarm Payrolls", "category": "employment", "freq": "monthly"},
    "ICSA":       {"name": "Initial Jobless Claims", "category": "employment", "freq": "weekly"},
    "CCSA":       {"name": "Continuing Jobless Claims", "category": "employment", "freq": "weekly"},
    "CES0500000003": {"name": "Average Hourly Earnings", "category": "employment", "freq": "monthly"},
    
    # ── Growth ──
    "GDP":        {"name": "GDP (Nominal)", "category": "growth", "freq": "quarterly"},
    "GDPC1":      {"name": "Real GDP", "category": "growth", "freq": "quarterly"},
    "RSAFS":      {"name": "Retail Sales", "category": "growth", "freq": "monthly"},
    "INDPRO":     {"name": "Industrial Production", "category": "growth", "freq": "monthly"},
    
    # ── Interest Rates & Yields ──
    "DFF":        {"name": "Fed Funds Rate (Effective)", "category": "rates", "freq": "daily"},
    "DGS2":       {"name": "2Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS5":       {"name": "5Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS10":      {"name": "10Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS30":      {"name": "30Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DFII10":     {"name": "10Y Real Yield (TIPS)", "category": "rates", "freq": "daily"},
    "T10Y2Y":     {"name": "10Y-2Y Spread (Yield Curve)", "category": "rates", "freq": "daily"},
    
    # ── Liquidity & Money ──
    "WALCL":      {"name": "Fed Balance Sheet (Total Assets)", "category": "liquidity", "freq": "weekly"},
    "M2SL":       {"name": "M2 Money Supply", "category": "liquidity", "freq": "monthly"},
    "RRPONTSYD":  {"name": "Reverse Repo (ON RRP)", "category": "liquidity", "freq": "daily"},
    "WTREGEN":    {"name": "Treasury General Account", "category": "liquidity", "freq": "weekly"},
    
    # ── Dollar & FX ──
    "DTWEXBGS":   {"name": "Trade Weighted Dollar Index (Broad)", "category": "fx", "freq": "daily"},
    "DEXUSEU":    {"name": "USD/EUR Exchange Rate", "category": "fx", "freq": "daily"},
    "DEXJPUS":    {"name": "JPY/USD Exchange Rate", "category": "fx", "freq": "daily"},
    "DEXCHUS":    {"name": "CNY/USD Exchange Rate", "category": "fx", "freq": "daily"},
    
    # ── Credit & Risk ──
    "BAMLH0A0HYM2": {"name": "High Yield OAS (Credit Spread)", "category": "credit", "freq": "daily"},
    "BAMLC0A0CM":    {"name": "IG Corporate Bond Spread", "category": "credit", "freq": "daily"},
    
    # ── Housing ──
    "HOUST":      {"name": "Housing Starts", "category": "housing", "freq": "monthly"},
    "CSUSHPINSA": {"name": "Case-Shiller Home Price Index", "category": "housing", "freq": "monthly"},
    
    # ── Consumer ──
    "UMCSENT":    {"name": "UMich Consumer Sentiment", "category": "consumer", "freq": "monthly"},
    "PSAVERT":    {"name": "Personal Savings Rate", "category": "consumer", "freq": "monthly"},
}


class FREDClient:
    """
    Client for the FRED API. 
    Free, reliable, and covers most US macro data you'll ever need.
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or FRED_API_KEY
        self.session = requests.Session()
        self._request_count = 0
    
    def _get(self, endpoint: str, params: dict) -> dict:
        """Make a FRED API request with rate limiting."""
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        
        url = f"{BASE_URL}/{endpoint}"
        
        self._request_count += 1
        if self._request_count % 100 == 0:
            time.sleep(1)  # gentle rate limiting
        
        resp = self.session.get(url, params=params, timeout=30)
        
        if resp.status_code != 200:
            print(f"[FRED] Error {resp.status_code}: {resp.text[:200]}")
            return {}
        
        return resp.json()
    
    def get_series(self, series_id: str, start_date: str = None, limit: int = 100) -> List[Dict]:
        """
        Fetch observations for a FRED series.
        
        Args:
            series_id: FRED series ID (e.g., 'CPIAUCSL')
            start_date: 'YYYY-MM-DD'. Default: 1 year ago
            limit: max observations to return
            
        Returns:
            List of {date, value} dicts
        """
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        
        data = self._get("series/observations", {
            "series_id": series_id,
            "observation_start": start_date,
            "sort_order": "desc",
            "limit": limit,
        })
        
        observations = []
        for obs in data.get("observations", []):
            if obs["value"] != ".":  # FRED uses "." for missing values
                observations.append({
                    "date": obs["date"],
                    "value": float(obs["value"]),
                })
        
        return observations
    
    def get_latest_value(self, series_id: str) -> Optional[Dict]:
        """Get the most recent observation for a series."""
        obs = self.get_series(series_id, limit=1)
        return obs[0] if obs else None
    
    def get_series_info(self, series_id: str) -> Dict:
        """Get metadata about a series."""
        return self._get("series", {"series_id": series_id})
    
    def fetch_all_macro_series(self, lookback_days: int = 365):
        """
        Fetch all key macro series and store them.
        This is your main daily data refresh function.
        """
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        
        print(f"[FRED] Fetching {len(MACRO_SERIES)} macro series...")
        
        for series_id, meta in MACRO_SERIES.items():
            try:
                observations = self.get_series(series_id, start_date=start_date)
                
                for obs in observations:
                    store_indicator(series_id, "fred", obs["date"], obs["value"])
                
                print(f"  ✓ {series_id} ({meta['name']}): {len(observations)} observations")
                time.sleep(0.5)  # be respectful
                
            except Exception as e:
                print(f"  ✗ {series_id}: {e}")
        
        print("[FRED] Done fetching all macro series.")
    
    def fetch_daily_updates(self):
        """
        Fetch only the daily-frequency series. 
        Run this every day for yields, credit spreads, dollar, etc.
        """
        daily_series = {k: v for k, v in MACRO_SERIES.items() if v["freq"] == "daily"}
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        
        print(f"[FRED] Fetching {len(daily_series)} daily series...")
        
        for series_id, meta in daily_series.items():
            try:
                observations = self.get_series(series_id, start_date=start_date, limit=5)
                
                for obs in observations:
                    store_indicator(series_id, "fred", obs["date"], obs["value"])
                
                latest = observations[0] if observations else {"value": "N/A"}
                print(f"  ✓ {series_id}: {latest.get('value', 'N/A')}")
                time.sleep(0.3)
                
            except Exception as e:
                print(f"  ✗ {series_id}: {e}")
    
    def get_yield_curve_snapshot(self) -> Dict:
        """
        Get current yield curve — critical for macro analysis.
        Returns dict with all key tenors.
        """
        tenors = ["DGS2", "DGS5", "DGS10", "DGS30", "DFII10", "T10Y2Y"]
        curve = {}
        
        for series_id in tenors:
            latest = self.get_latest_value(series_id)
            if latest:
                name = MACRO_SERIES[series_id]["name"]
                curve[series_id] = {
                    "name": name,
                    "value": latest["value"],
                    "date": latest["date"],
                }
            time.sleep(0.3)
        
        return curve
    
    def get_liquidity_snapshot(self) -> Dict:
        """
        Get current liquidity conditions — Fed balance sheet, M2, RRP, TGA.
        This drives crypto more than most people realize.
        """
        liquidity_series = ["WALCL", "M2SL", "RRPONTSYD", "WTREGEN"]
        snapshot = {}
        
        for series_id in liquidity_series:
            latest = self.get_latest_value(series_id)
            if latest:
                name = MACRO_SERIES[series_id]["name"]
                snapshot[series_id] = {
                    "name": name,
                    "value": latest["value"],
                    "date": latest["date"],
                }
            time.sleep(0.3)
        
        return snapshot


# ─── Helper: Build analyst context from FRED data ───

def build_macro_context(fred: FREDClient) -> str:
    """
    Build a text summary of current macro conditions from FRED data.
    This gets injected into the Analyst agent's context window.
    """
    context_parts = []
    
    # Yield curve
    curve = fred.get_yield_curve_snapshot()
    if curve:
        context_parts.append("=== YIELD CURVE ===")
        for series_id, data in curve.items():
            context_parts.append(f"{data['name']}: {data['value']}% (as of {data['date']})")
    
    # Liquidity
    liquidity = fred.get_liquidity_snapshot()
    if liquidity:
        context_parts.append("\n=== LIQUIDITY CONDITIONS ===")
        for series_id, data in liquidity.items():
            context_parts.append(f"{data['name']}: {data['value']:,.0f} (as of {data['date']})")
    
    # Latest inflation
    cpi = fred.get_latest_value("CPIAUCSL")
    core_cpi = fred.get_latest_value("CPILFESL")
    if cpi:
        context_parts.append(f"\n=== INFLATION ===")
        context_parts.append(f"CPI: {cpi['value']} (as of {cpi['date']})")
        if core_cpi:
            context_parts.append(f"Core CPI: {core_cpi['value']} (as of {core_cpi['date']})")
    
    return "\n".join(context_parts)


if __name__ == "__main__":
    from storage.event_store import init_db
    init_db()
    
    fred = FREDClient()
    
    if FRED_API_KEY == "YOUR_FRED_API_KEY_HERE":
        print("⚠️  Set your FRED API key!")
        print("   Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html")
        print("   Then: export FRED_API_KEY=your_key_here")
    else:
        print("=== Yield Curve ===")
        curve = fred.get_yield_curve_snapshot()
        for k, v in curve.items():
            print(f"  {v['name']}: {v['value']}%")
        
        print("\n=== Liquidity ===")
        liq = fred.get_liquidity_snapshot()
        for k, v in liq.items():
            print(f"  {v['name']}: {v['value']:,.0f}")
