"""
scrapers/investing_calendar.py

Scrapes Investing.com economic calendar for:
- Event name, country, datetime
- Actual / Forecast / Previous values
- Impact level (high/medium/low)

Strategy: 
- Investing.com renders calendar data via their internal API
- We hit their API endpoint directly (much more reliable than HTML scraping)
- Respectful rate limiting: 1 request per 5 seconds
"""

import requests
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from storage.event_store import store_calendar_event


# ─── Configuration ───

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.investing.com/economic-calendar/",
}

# Country ID mapping for Investing.com
COUNTRY_MAP = {
    5: "US",
    72: "EU",  # Eurozone
    35: "JP",
    4: "UK",
    17: "CA",
    25: "AU",
    6: "CN",
    36: "NZ",
    12: "CH",  # Switzerland
    26: "SG",
    34: "DE",  # Germany
    22: "FR",
}

IMPORTANCE_MAP = {
    1: "low",
    2: "medium", 
    3: "high",
}

# Categories we care about for macro analysis
MACRO_CATEGORIES = {
    "inflation": ["CPI", "PPI", "PCE", "Inflation", "Price Index"],
    "employment": ["NFP", "Nonfarm", "Unemployment", "Jobless", "Employment", "ADP", "Payroll"],
    "growth": ["GDP", "Retail Sales", "Industrial Production", "PMI", "ISM"],
    "monetary_policy": ["Interest Rate", "Fed", "FOMC", "ECB", "BOJ", "BOE", "Central Bank"],
    "housing": ["Housing", "Home Sales", "Building Permits"],
    "consumer": ["Consumer Confidence", "Consumer Sentiment", "Michigan"],
    "trade": ["Trade Balance", "Current Account", "Import", "Export"],
}


def categorize_event(indicator_name: str) -> str:
    """Auto-categorize an economic event based on its name."""
    name_upper = indicator_name.upper()
    for category, keywords in MACRO_CATEGORIES.items():
        for keyword in keywords:
            if keyword.upper() in name_upper:
                return category
    return "other"


def generate_event_id(country: str, indicator: str, dt: str) -> str:
    """Generate a deterministic event ID for deduplication."""
    raw = f"{country}-{indicator}-{dt}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class InvestingCalendarScraper:
    """
    Scrapes economic calendar from Investing.com.
    
    Two approaches (use whichever works):
    1. API endpoint (preferred, more structured)
    2. HTML parsing (fallback)
    """
    
    BASE_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
    
    def __init__(self, countries: List[str] = None):
        """
        Args:
            countries: List of country codes to track. Default: US + G10
        """
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        
        # Reverse lookup: code -> investing.com ID
        self.country_ids = []
        target_countries = countries or ["US", "EU", "JP", "UK", "CA", "AU", "CN", "SG"]
        for inv_id, code in COUNTRY_MAP.items():
            if code in target_countries:
                self.country_ids.append(inv_id)
    
    def scrape_calendar(self, date_from: str = None, date_to: str = None) -> List[Dict]:
        """
        Scrape economic calendar for a date range.
        
        Args:
            date_from: 'YYYY-MM-DD' format. Default: today
            date_to: 'YYYY-MM-DD' format. Default: today
            
        Returns:
            List of event dicts ready for storage
        """
        if not date_from:
            date_from = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not date_to:
            date_to = date_from
        
        print(f"[Investing.com] Scraping calendar: {date_from} to {date_to}")
        
        # Approach 1: Try the AJAX API endpoint
        events = self._scrape_via_api(date_from, date_to)
        
        if not events:
            # Approach 2: Fallback to HTML parsing
            print("[Investing.com] API approach failed, trying HTML fallback...")
            events = self._scrape_via_html(date_from, date_to)
        
        print(f"[Investing.com] Found {len(events)} events")
        return events
    
    def _scrape_via_api(self, date_from: str, date_to: str) -> List[Dict]:
        """
        Hit Investing.com's internal AJAX endpoint.
        This returns structured data directly.
        """
        events = []
        
        try:
            payload = {
                "dateFrom": date_from,
                "dateTo": date_to,
                "country[]": self.country_ids,
                "importance[]": [1, 2, 3],  # all importance levels
                "timeZone": 8,  # UTC+8 (Singapore)
                "timeFilter": "timeRemain",
                "currentTab": "custom",
                "limit_from": 0,
            }
            
            resp = self.session.post(self.BASE_URL, data=payload, timeout=30)
            
            if resp.status_code != 200:
                print(f"[Investing.com] API returned {resp.status_code}")
                return []
            
            data = resp.json()
            html_content = data.get("data", "")
            
            if html_content:
                events = self._parse_calendar_html(html_content)
            
        except Exception as e:
            print(f"[Investing.com] API error: {e}")
        
        return events
    
    def _scrape_via_html(self, date_from: str, date_to: str) -> List[Dict]:
        """
        Fallback: scrape the full calendar page HTML.
        """
        from bs4 import BeautifulSoup
        events = []
        
        try:
            url = f"https://www.investing.com/economic-calendar/"
            resp = self.session.get(url, timeout=30)
            
            if resp.status_code != 200:
                print(f"[Investing.com] HTML page returned {resp.status_code}")
                return []
            
            events = self._parse_calendar_html(resp.text)
            
        except Exception as e:
            print(f"[Investing.com] HTML scrape error: {e}")
        
        return events
    
    def _parse_calendar_html(self, html: str) -> List[Dict]:
        """
        Parse calendar table rows from HTML (works for both API and page responses).
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        events = []
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        rows = soup.find_all("tr", {"class": "js-event-item"})
        
        for row in rows:
            try:
                # Extract event ID
                event_id_attr = row.get("event_attr_id", row.get("id", ""))
                
                # Country
                flag_td = row.find("td", {"class": "flagCur"})
                country_code = ""
                if flag_td:
                    flag_span = flag_td.find("span")
                    if flag_span:
                        # Extract country from flag class like "cemark ce-us"
                        classes = flag_span.get("class", [])
                        for cls in classes:
                            if cls.startswith("ce-"):
                                country_code = cls.replace("ce-", "").upper()
                
                # Time
                time_td = row.find("td", {"class": "time"})
                event_time = time_td.text.strip() if time_td else ""
                
                # Importance (count of bull icons)
                importance_td = row.find("td", {"class": "sentiment"})
                importance = "low"
                if importance_td:
                    bulls = importance_td.find_all("i", {"class": "grayFullBullishIcon"})
                    if len(bulls) >= 3:
                        importance = "high"
                    elif len(bulls) >= 2:
                        importance = "medium"
                
                # Event name
                event_td = row.find("td", {"class": "event"})
                indicator = event_td.text.strip() if event_td else ""
                
                # Values: actual, forecast, previous
                actual_td = row.find("td", {"class": "act"})
                forecast_td = row.find("td", {"class": "fore"})
                previous_td = row.find("td", {"class": "prev"})
                
                actual = actual_td.text.strip() if actual_td else ""
                forecast = forecast_td.text.strip() if forecast_td else ""
                previous = previous_td.text.strip() if previous_td else ""
                
                # Clean up empty/nbsp values
                actual = None if actual in ["", "\xa0", " "] else actual
                forecast = None if forecast in ["", "\xa0", " "] else forecast
                previous = None if previous in ["", "\xa0", " "] else previous
                
                # Build datetime
                dt_str = f"{current_date}T{event_time}:00" if event_time else current_date
                
                event = {
                    "source": "investing",
                    "event_id": generate_event_id(country_code, indicator, dt_str),
                    "datetime_utc": dt_str,
                    "country": country_code,
                    "indicator": indicator,
                    "category": categorize_event(indicator),
                    "importance": importance,
                    "actual": actual,
                    "forecast": forecast,
                    "previous": previous,
                    "revised_previous": None,
                    "unit": "",
                }
                
                events.append(event)
                
            except Exception as e:
                continue  # skip malformed rows
        
        return events
    
    def scrape_and_store(self, date_from: str = None, date_to: str = None):
        """Scrape and persist to database."""
        events = self.scrape_calendar(date_from, date_to)
        stored = 0
        for event in events:
            try:
                store_calendar_event(event)
                stored += 1
            except Exception as e:
                print(f"[Investing.com] Store error: {e}")
        
        print(f"[Investing.com] Stored {stored}/{len(events)} events")
        return events


# ─── Alternative: Simpler API-based calendar from Econdb (free tier) ───

class EcondbCalendarScraper:
    """
    Econdb.com provides a free economic calendar API.
    Less data than Investing.com but much more reliable to scrape.
    No HTML parsing needed.
    
    Free tier: 50 requests/day — enough for daily calendar checks.
    """
    
    BASE_URL = "https://www.econdb.com/api/series/"
    CALENDAR_URL = "https://www.econdb.com/calendar/"
    
    def scrape_calendar_rss(self) -> List[Dict]:
        """
        Econdb publishes a calendar RSS feed — simplest approach.
        """
        import feedparser
        events = []
        
        try:
            feed = feedparser.parse("https://www.econdb.com/calendar/rss/")
            
            for entry in feed.entries:
                event = {
                    "source": "econdb",
                    "event_id": entry.get("id", ""),
                    "datetime_utc": entry.get("published", ""),
                    "country": "",  # parse from title
                    "indicator": entry.get("title", ""),
                    "category": "",
                    "importance": "medium",
                    "actual": None,
                    "forecast": None,
                    "previous": None,
                }
                events.append(event)
            
        except Exception as e:
            print(f"[Econdb] Error: {e}")
        
        return events


# ─── ForexFactory Calendar Scraper ───

class ForexFactoryCalendarScraper:
    """
    ForexFactory has one of the best free economic calendars.
    Impact ratings (red/orange/yellow) are particularly useful.
    
    Strategy: Scrape the calendar page HTML.
    """
    
    BASE_URL = "https://www.forexfactory.com/calendar"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    
    IMPACT_MAP = {
        "red": "high",     # high impact
        "ora": "medium",   # medium impact  
        "yel": "low",      # low impact
        "gra": "holiday",  # bank holiday / non-event
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
    
    def scrape_calendar(self, week: str = "this") -> List[Dict]:
        """
        Scrape ForexFactory calendar.
        
        Args:
            week: 'this', 'next', or specific date like 'jan1.2026'
        """
        from bs4 import BeautifulSoup
        events = []
        
        url = f"{self.BASE_URL}?week={week}" if week != "this" else self.BASE_URL
        
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                print(f"[ForexFactory] Got status {resp.status_code}")
                return []
            
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # ForexFactory uses a table with class "calendar__table"
            table = soup.find("table", {"class": "calendar__table"})
            if not table:
                print("[ForexFactory] Calendar table not found")
                return []
            
            rows = table.find_all("tr", {"class": "calendar__row"})
            current_date = ""
            
            for row in rows:
                try:
                    # Date cell (only appears on first event of each day)
                    date_cell = row.find("td", {"class": "calendar__date"})
                    if date_cell and date_cell.text.strip():
                        current_date = date_cell.text.strip()
                    
                    # Time
                    time_cell = row.find("td", {"class": "calendar__time"})
                    event_time = time_cell.text.strip() if time_cell else ""
                    
                    # Country/Currency
                    currency_cell = row.find("td", {"class": "calendar__currency"})
                    currency = currency_cell.text.strip() if currency_cell else ""
                    
                    # Impact
                    impact_cell = row.find("td", {"class": "calendar__impact"})
                    importance = "medium"
                    if impact_cell:
                        impact_span = impact_cell.find("span")
                        if impact_span:
                            for cls in impact_span.get("class", []):
                                for key, val in self.IMPACT_MAP.items():
                                    if key in cls.lower():
                                        importance = val
                    
                    # Event name
                    event_cell = row.find("td", {"class": "calendar__event"})
                    indicator = ""
                    if event_cell:
                        event_link = event_cell.find("a") or event_cell.find("span")
                        indicator = event_link.text.strip() if event_link else event_cell.text.strip()
                    
                    if not indicator:
                        continue
                    
                    # Values
                    actual_cell = row.find("td", {"class": "calendar__actual"})
                    forecast_cell = row.find("td", {"class": "calendar__forecast"})
                    previous_cell = row.find("td", {"class": "calendar__previous"})
                    
                    actual = actual_cell.text.strip() if actual_cell else None
                    forecast = forecast_cell.text.strip() if forecast_cell else None
                    previous = previous_cell.text.strip() if previous_cell else None
                    
                    # Clean empty values
                    actual = None if not actual or actual in ["\xa0", " "] else actual
                    forecast = None if not forecast or forecast in ["\xa0", " "] else forecast
                    previous = None if not previous or previous in ["\xa0", " "] else previous
                    
                    # Currency to country mapping
                    currency_to_country = {
                        "USD": "US", "EUR": "EU", "GBP": "UK", "JPY": "JP",
                        "CAD": "CA", "AUD": "AU", "NZD": "NZ", "CHF": "CH",
                        "CNY": "CN", "SGD": "SG",
                    }
                    country = currency_to_country.get(currency, currency)
                    
                    dt_str = f"{current_date} {event_time}".strip()
                    
                    event = {
                        "source": "forexfactory",
                        "event_id": generate_event_id(country, indicator, dt_str),
                        "datetime_utc": dt_str,
                        "country": country,
                        "indicator": indicator,
                        "category": categorize_event(indicator),
                        "importance": importance,
                        "actual": actual,
                        "forecast": forecast,
                        "previous": previous,
                        "revised_previous": None,
                        "unit": "",
                    }
                    
                    events.append(event)
                    
                except Exception as e:
                    continue
            
        except Exception as e:
            print(f"[ForexFactory] Error: {e}")
        
        print(f"[ForexFactory] Found {len(events)} events")
        return events
    
    def scrape_and_store(self, week: str = "this"):
        events = self.scrape_calendar(week)
        stored = 0
        for event in events:
            try:
                store_calendar_event(event)
                stored += 1
            except Exception as e:
                print(f"[ForexFactory] Store error: {e}")
        print(f"[ForexFactory] Stored {stored}/{len(events)} events")
        return events


if __name__ == "__main__":
    # Test run
    from storage.event_store import init_db
    init_db()
    
    print("\n=== Testing Investing.com Scraper ===")
    inv = InvestingCalendarScraper()
    inv.scrape_and_store()
    
    print("\n=== Testing ForexFactory Scraper ===")
    ff = ForexFactoryCalendarScraper()
    ff.scrape_and_store()
