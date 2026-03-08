# Scrapers – Data Reference

Each scraper module targets one financial site and exposes clients for every
scrapable data section. All clients use `curl_cffi` (via `create_cf_session`)
for TLS-fingerprint bypass of Cloudflare protection.

---

## Shared Data Types (`_common.py`)

| Dataclass | Purpose |
|-----------|---------|
| `ScrapedNewsItem` | A news/article headline from any site |
| `ScrapedIndicator` | A macro-economic indicator snapshot |
| `ScrapedMarketQuote` | A market price quote |

Calendar data uses the existing `StoredEventRecord` from `analyst.storage`.

---

## 1. Investing.com (`investing.py`)

### InvestingCalendarClient

Scrapes the **economic calendar** via Investing.com's internal JSON API.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch(date_from, date_to)` | `list[StoredEventRecord]` | Events for a single date range |
| `fetch_range(days_back, days_forward)` | `list[StoredEventRecord]` | Multi-day sweep with 1.5 s delay between days |

**Fields per event:** source, event_id, datetime_utc, country, indicator,
category, importance (low/medium/high), actual, forecast, previous,
revised_previous, surprise, currency, raw_json.

**Anti-bot:** POST to `/Service/getCalendarFilteredData` with
`X-Requested-With: XMLHttpRequest`. Retries 3 times with exponential backoff.

### InvestingNewsClient

Scrapes **news articles** from the `/news/<category>` HTML pages.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(category)` | `list[ScrapedNewsItem]` | Articles for one category |

**Supported categories:** `latest-news`, `economy-news`,
`commodities-news`, `cryptocurrency-news`, `forex-news`,
`stock-market-news`, `economic-indicators`, `world-news`,
`most-popular-news`.

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Oil at $100 could lift U.S. inflation…" |
| `url` | Full article URL |
| `published_at` | `2026-03-08 08:14:56` (server local time) |
| `description` | First-paragraph snippet |
| `author` | "Reuters", "Investing.com" |
| `category` | Extracted from URL path (e.g. `economy-news`) |

**Typical yield:** ~20 articles per category page.

---

## 2. ForexFactory (`forexfactory.py`)

### ForexFactoryCalendarClient

Scrapes the **economic calendar** table from the ForexFactory calendar page.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch(week)` | `list[StoredEventRecord]` | Events for `"this"` week or a specific week string |

**Fields per event:** source, event_id, datetime_utc, country, indicator,
category, importance (low/medium/high from colour), actual, forecast,
previous, surprise, raw_json.

### ForexFactoryNewsClient

Scrapes the **news feed** from the ForexFactory `/news` page.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news()` | `list[ScrapedNewsItem]` | Latest news articles |

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Week Ahead: War and More War" |
| `url` | `https://www.forexfactory.com/news/1387525-…` |
| `description` | Article preview / first paragraph |
| `author` | Source site: "reuters.com", "zerohedge.com", "@realDonaldTrump" |
| `importance` | `high` / `medium` / `low` (from colour badge, if present) |
| `raw_json.time_ago` | "3 hr ago" |
| `raw_json.comments` | Comment count (int) |

**Typical yield:** ~20-35 news items per fetch.

**Note:** Impact badges only appear on breaking-news items. Regular articles
have `importance=""`.

---

## 3. TradingEconomics (`tradingeconomics.py`)

### TradingEconomicsCalendarClient

Scrapes the **economic calendar** with per-event importance (3 requests,
one per importance level).

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch()` | `list[StoredEventRecord]` | Today's calendar events at all importance levels |

### TradingEconomicsNewsClient

Fetches the **news stream** from TE's internal JSON API (`/ws/stream.ashx`).

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(count=20)` | `list[ScrapedNewsItem]` | Latest *count* news items |

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "China FX Reserves Highest in Over 10 Years" |
| `url` | `https://tradingeconomics.com/china/foreign-exchange-reserves` |
| `published_at` | `2026-03-07T04:19:00.057` (UTC) |
| `description` | Full article body text |
| `author` | "Farida Husna", or "CALCULATOR" for auto-generated summaries |
| `category` | Indicator name: "Foreign Exchange Reserves", "Inflation Rate", "Crypto" |
| `importance` | `high` / `medium` / `low` (numeric 3/2/1 mapped) |
| `raw_json.country` | "China", "United States", "Crypto" |
| `raw_json.id` | Numeric stream item ID |
| `raw_json.expiration` | When the item expires from the stream |

**Typical yield:** 20 items (configurable via `count`).

### TradingEconomicsIndicatorsClient

Scrapes **macro-economic indicator tables** from the country indicators page.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_indicators(country)` | `list[ScrapedIndicator]` | All indicators for a country |

**Country parameter:** URL slug, e.g. `"united-states"`, `"japan"`,
`"euro-area"`, `"china"`.

**Fields per indicator:**

| Field | Example |
|-------|---------|
| `name` | "Unemployment Rate" |
| `last` | "4.4" |
| `previous` | "4.3" |
| `highest` | "14.8" |
| `lowest` | "2.5" |
| `unit` | "percent", "Thousand", "USD Billion" |
| `date` | "Feb/26" |
| `country` | "US" (ISO 2-letter code) |
| `category` | Auto-detected: "employment", "inflation", "growth", etc. |
| `url` | Detail page link |

**Typical yield:** ~400 indicators for the US.

### TradingEconomicsMarketsClient

Scrapes the **market overview tables** from the TE news page sidebar.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_markets()` | `list[ScrapedMarketQuote]` | Current market snapshot |

**Fields per quote:**

| Field | Example |
|-------|---------|
| `name` | "Crude Oil", "Bitcoin", "US500" |
| `asset_class` | `commodity` / `fx` / `index` / `stock` / `bond` / `crypto` |
| `price` | "90.900" |
| `change` | "9.89" |
| `change_pct` | "12.21%" |
| `url` | Detail page link |

**Asset classes returned (6):**

| Class | Items | Examples |
|-------|-------|---------|
| `commodity` | 15 | Crude Oil, Brent, Gold, Natural Gas, Copper |
| `fx` | 15 | EURUSD, GBPUSD, USDJPY, USDCNY |
| `index` | 15 | US500, US30, DAX, FTSE 100, Nikkei 225 |
| `stock` | 15 | Apple, Tesla, Microsoft, Amazon, Nvidia |
| `bond` | 15 | US 10Y, UK 10Y, Japan 10Y, Germany 10Y |
| `crypto` | 15 | Bitcoin, Ether, Binance, Solana, XRP |

**Typical yield:** ~90 quotes total.

---

## Summary Matrix

| Site | Calendar | News | Indicators | Markets |
|------|:--------:|:----:|:----------:|:-------:|
| **Investing.com** | `InvestingCalendarClient` | `InvestingNewsClient` | — | — |
| **ForexFactory** | `ForexFactoryCalendarClient` | `ForexFactoryNewsClient` | — | — |
| **TradingEconomics** | `TradingEconomicsCalendarClient` | `TradingEconomicsNewsClient` | `TradingEconomicsIndicatorsClient` | `TradingEconomicsMarketsClient` |

## Running Tests

```bash
# Unit tests only (no network, fast)
pytest tests/test_scrapers.py -m "not live" -v

# Live integration tests (hits real endpoints)
pytest tests/test_scrapers.py -m live -v

# All scraper tests
pytest tests/test_scrapers.py -v
```
