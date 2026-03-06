# Macro Analyst Agent - Data Scraper Toolkit

## Architecture

```
FREE Data Sources          Scrapers              Storage           Analyst Agent
─────────────────         ─────────            ──────────         ─────────────
Investing.com  ──→  calendar_scraper.py  ──→                 
ForexFactory   ──→  forexfactory_scraper.py ──→  SQLite DB   ──→  LLM Context
FRED API       ──→  fred_client.py       ──→   (event_store)      Builder
Fed RSS        ──→  fed_scraper.py       ──→                 
Yahoo Finance  ──→  market_scraper.py    ──→                 
```

## Data Sources (all FREE)

| Source | Data | Method | Rate Limit |
|--------|------|--------|------------|
| FRED API | US economic indicators, yields, M2 | Official API (free key) | 120/min |
| Investing.com | Economic calendar (actual/forecast/prev) | Web scrape | Be respectful |
| ForexFactory | Economic calendar + impact rating | Web scrape | Be respectful |
| Yahoo Finance | Market prices (FX, indices, commodities) | yfinance lib | Reasonable |
| Fed RSS | FOMC statements, speeches, minutes | RSS feed | No limit |
| ECB | European data | Official API | Reasonable |

## Setup

```bash
pip install requests beautifulsoup4 feedparser yfinance pandas sqlite-utils schedule
```

## Usage

```bash
# Run all scrapers once
python main.py --once

# Run on schedule (for deployment)
python main.py --schedule

# Query stored data for analyst agent
python query_data.py --today-events
python query_data.py --latest-fed
python query_data.py --market-snapshot
```
