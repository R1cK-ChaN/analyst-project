"""
main.py

Main orchestrator for the Macro Analyst Agent data pipeline.
Runs all scrapers on schedule and triggers the Analyst agent when needed.

Usage:
    python main.py --once          # Run all scrapers once
    python main.py --schedule      # Run on cron schedule (for deployment)
    python main.py --flash CPI     # Generate flash commentary for a specific event
    python main.py --briefing      # Generate daily briefing
"""

import argparse
import time
import json
from datetime import datetime, timezone

# Storage
from storage.event_store import init_db, get_today_events, save_regime_state

# Scrapers
from scrapers.investing_calendar import InvestingCalendarScraper, ForexFactoryCalendarScraper
from scrapers.fred_client import FREDClient
from scrapers.fed_scraper import FedScraper
from scrapers.market_scraper import MarketScraper

# Context builder
from utils.analyst_context import (
    build_flash_commentary_context,
    build_daily_briefing_context,
    build_deep_analysis_context,
    ANALYST_SYSTEM_PROMPT,
    FLASH_COMMENTARY_PROMPT,
    DAILY_BRIEFING_PROMPT,
)


def run_all_scrapers():
    """Run all data scrapers once."""
    print(f"\n{'='*60}")
    print(f"Running all scrapers at {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}\n")
    
    # 1. Economic Calendar
    print("─── Economic Calendar ───")
    try:
        investing = InvestingCalendarScraper()
        investing.scrape_and_store()
    except Exception as e:
        print(f"Investing.com scraper failed: {e}")
    
    try:
        ff = ForexFactoryCalendarScraper()
        ff.scrape_and_store()
    except Exception as e:
        print(f"ForexFactory scraper failed: {e}")
    
    # 2. FRED Data (daily series only for routine updates)
    print("\n─── FRED Data ───")
    try:
        fred = FREDClient()
        fred.fetch_daily_updates()
    except Exception as e:
        print(f"FRED client failed: {e}")
    
    # 3. Fed Communications
    print("\n─── Fed Communications ───")
    try:
        fed = FedScraper()
        fed.scrape_and_store(fetch_full_text=False)
    except Exception as e:
        print(f"Fed scraper failed: {e}")
    
    # 4. Market Prices
    print("\n─── Market Prices ───")
    try:
        market = MarketScraper()
        market.fetch_all_prices()
    except Exception as e:
        print(f"Market scraper failed: {e}")
    
    print(f"\n{'='*60}")
    print(f"All scrapers completed.")
    print(f"{'='*60}\n")


def generate_flash_commentary(indicator_keyword: str = None):
    """
    Generate flash commentary for the most recent high-impact event.
    
    This is where the Analyst agent actually runs:
    1. Get the event
    2. Build context
    3. Call LLM
    4. Store regime state update
    """
    events = get_today_events()
    
    if indicator_keyword:
        events = [e for e in events if indicator_keyword.lower() in e.get("indicator", "").lower()]
    
    # Filter to events that have actual values (already released)
    released = [e for e in events if e.get("actual")]
    
    if not released:
        print("No released events found. Run scrapers first or check calendar.")
        return
    
    # Take the most important one
    importance_order = {"high": 3, "medium": 2, "low": 1}
    released.sort(key=lambda x: importance_order.get(x.get("importance", ""), 0), reverse=True)
    event = released[0]
    
    print(f"\n─── Flash Commentary for: {event['indicator']} ({event['country']}) ───")
    print(f"Actual: {event['actual']} | Forecast: {event['forecast']} | Previous: {event['previous']}")
    print(f"Surprise: {event.get('surprise', 'N/A')}\n")
    
    # Build context
    context = build_flash_commentary_context(event)
    
    # ─── Call your LLM here ───
    # Replace this with your actual LLM call (Anthropic, OpenAI, etc.)
    
    print("=== CONTEXT FOR LLM (paste into your LLM of choice) ===")
    print(f"\nSYSTEM PROMPT:\n{ANALYST_SYSTEM_PROMPT}")
    print(f"\nUSER PROMPT:\n{FLASH_COMMENTARY_PROMPT}")
    print(f"\nCONTEXT:\n{context}")
    
    # Example of how to call Anthropic API:
    """
    import anthropic
    
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    message = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=2000,
        system=ANALYST_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user", 
                "content": f"{FLASH_COMMENTARY_PROMPT}\n\n{context}"
            }
        ]
    )
    
    commentary = message.content[0].text
    print(commentary)
    
    # Extract regime state JSON from response and save it
    # (you'd parse the JSON block from the LLM response)
    """


def generate_daily_briefing():
    """Generate the daily morning macro briefing."""
    context = build_daily_briefing_context()
    
    print("=== DAILY BRIEFING CONTEXT ===")
    print(f"\nSYSTEM PROMPT:\n{ANALYST_SYSTEM_PROMPT}")
    print(f"\nUSER PROMPT:\n{DAILY_BRIEFING_PROMPT}")
    print(f"\nCONTEXT:\n{context}")


def run_scheduled():
    """
    Run scrapers on a schedule suitable for deployment on Contabo VPS.
    
    Schedule:
    - Every 30 min: market prices
    - Every 1 hour: economic calendar (check for new releases)
    - Every 4 hours: Fed RSS feeds
    - Once daily at 6am UTC: FRED daily series, full calendar refresh
    - Once weekly (Sunday): FRED full historical refresh
    """
    import schedule
    
    print("Starting scheduled data collection...")
    print("Press Ctrl+C to stop.\n")
    
    # Quick market snapshot
    def job_market_prices():
        try:
            market = MarketScraper()
            market.fetch_all_prices()
            print(f"[{datetime.now(timezone.utc).strftime('%H:%M')}] Market prices updated")
        except Exception as e:
            print(f"Market price job failed: {e}")
    
    # Calendar check
    def job_calendar():
        try:
            inv = InvestingCalendarScraper()
            events = inv.scrape_and_store()
            
            # Check for new releases with surprises
            new_releases = [e for e in events if e.get("actual") and e.get("importance") == "high"]
            if new_releases:
                print(f"⚡ {len(new_releases)} new high-importance releases detected!")
                for e in new_releases:
                    print(f"   → {e['country']} {e['indicator']}: {e['actual']} (forecast: {e['forecast']})")
                # TODO: trigger flash commentary generation here
                
        except Exception as e:
            print(f"Calendar job failed: {e}")
    
    # Fed communications
    def job_fed():
        try:
            fed = FedScraper()
            fed.scrape_and_store()
        except Exception as e:
            print(f"Fed job failed: {e}")
    
    # FRED daily refresh
    def job_fred_daily():
        try:
            fred = FREDClient()
            fred.fetch_daily_updates()
        except Exception as e:
            print(f"FRED daily job failed: {e}")
    
    # FRED full refresh
    def job_fred_full():
        try:
            fred = FREDClient()
            fred.fetch_all_macro_series()
        except Exception as e:
            print(f"FRED full refresh failed: {e}")
    
    # Set up schedule
    schedule.every(30).minutes.do(job_market_prices)
    schedule.every(1).hours.do(job_calendar)
    schedule.every(4).hours.do(job_fed)
    schedule.every().day.at("06:00").do(job_fred_daily)
    schedule.every().sunday.at("02:00").do(job_fred_full)
    
    # Run initial fetch
    print("Running initial data fetch...")
    run_all_scrapers()
    
    # Enter schedule loop
    while True:
        schedule.run_pending()
        time.sleep(60)


def main():
    parser = argparse.ArgumentParser(description="Macro Analyst Agent - Data Pipeline")
    parser.add_argument("--once", action="store_true", help="Run all scrapers once")
    parser.add_argument("--schedule", action="store_true", help="Run on automated schedule")
    parser.add_argument("--flash", type=str, nargs="?", const="", help="Generate flash commentary (optionally filter by indicator name)")
    parser.add_argument("--briefing", action="store_true", help="Generate daily briefing")
    parser.add_argument("--deep", type=str, help="Generate deep analysis on a topic")
    parser.add_argument("--init-db", action="store_true", help="Initialize database only")
    
    args = parser.parse_args()
    
    # Always ensure DB exists
    init_db()
    
    if args.init_db:
        print("Database initialized.")
    elif args.once:
        run_all_scrapers()
    elif args.schedule:
        run_scheduled()
    elif args.flash is not None:
        generate_flash_commentary(args.flash if args.flash else None)
    elif args.briefing:
        generate_daily_briefing()
    elif args.deep:
        context = build_deep_analysis_context(args.deep)
        print(context)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
