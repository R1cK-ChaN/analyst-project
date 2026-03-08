# Scrapers – Data Reference

Each scraper module targets one financial site and exposes clients for every
scrapable data section. All clients use `curl_cffi` (via `create_cf_session`)
for TLS-fingerprint bypass of Cloudflare protection.

All news clients support **pagination** — single-page fetches for polling,
plus `fetch_all_news()` convenience methods for backfill.

---

## Shared Data Types (`_common.py`)

| Dataclass | Purpose |
|-----------|---------|
| `ScrapedNewsItem` | A news/article headline from any site (`image_url`, `raw_json` included) |
| `ScrapedIndicator` | A macro-economic indicator snapshot |
| `ScrapedMarketQuote` | A market price quote (`symbol`, `raw_json` included) |

Calendar data uses the existing `StoredEventRecord` from `analyst.storage`.

---

## 1. Investing.com (`investing.py`)

### InvestingCalendarClient

Scrapes the **economic calendar** via Investing.com's internal JSON API.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch(date_from, date_to)` | `list[StoredEventRecord]` | Events for a single date range |
| `fetch_range(days_back, days_forward)` | `list[StoredEventRecord]` | Multi-day sweep with 1.5 s delay between days |

**Fields per event:** source, event_id, timestamp (epoch seconds), country,
indicator, category, importance (low/medium/high), actual, forecast, previous,
revised_previous, surprise, currency, raw_json.

**Anti-bot:** POST to `/Service/getCalendarFilteredData` with
`X-Requested-With: XMLHttpRequest`. Retries 3 times with exponential backoff.

### InvestingNewsClient

Scrapes **news articles** from the `/news/<category>` HTML pages.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(category, page=1)` | `list[ScrapedNewsItem]` | Articles for one category page |
| `fetch_all_news(category, max_pages=3)` | `list[ScrapedNewsItem]` | Paginate through multiple pages with 1.5 s delay |

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
| `raw_json.comments` | Comment count (int, when visible on the page) |

**Typical yield:** ~20 articles per category page.

---

## 2. ForexFactory (`forexfactory.py`)

### ForexFactoryCalendarClient

Scrapes the **economic calendar** table from the ForexFactory calendar page.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch(week)` | `list[StoredEventRecord]` | Events for `"this"` week or a specific week string |

**Fields per event:** source, event_id, timestamp (epoch seconds), country,
indicator, category, importance (low/medium/high from colour), actual,
forecast, previous, surprise, raw_json.

### ForexFactoryNewsClient

Scrapes the **news feed** from the ForexFactory `/news` page.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(page=1)` | `list[ScrapedNewsItem]` | News articles for one page |
| `fetch_all_news(max_pages=3)` | `list[ScrapedNewsItem]` | Paginate through multiple pages with 1.5 s delay |

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Week Ahead: War and More War" |
| `url` | `https://www.forexfactory.com/news/1387525-…` |
| `description` | Article preview / first paragraph |
| `author` | Source site: "reuters.com", "zerohedge.com", "@realDonaldTrump" |
| `importance` | `high` / `medium` / `low` (from colour badge, if present) |
| `image_url` | Article thumbnail (when rendered on the page) |
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
| `fetch_news(start=0, count=20)` | `list[ScrapedNewsItem]` | *count* news items from offset *start* |
| `fetch_all_news(max_items=100, batch_size=20)` | `list[ScrapedNewsItem]` | Paginate through the stream with 1 s delay between batches |

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
| `image_url` | Article image or thumbnail URL (whichever is non-empty) |
| `raw_json.country` | "China", "United States", "Crypto" |
| `raw_json.id` | Numeric stream item ID |
| `raw_json.expiration` | When the item expires from the stream |
| `raw_json.html` | Rich HTML body with embedded symbol links (if present) |
| `raw_json.type` | Item type, e.g. "indicator" (if present) |

**Typical yield:** 20 items per batch (configurable via `count`).

### TradingEconomicsIndicatorsClient

Scrapes **macro-economic indicator tables** from the country indicators page.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_indicators(country)` | `list[ScrapedIndicator]` | All indicators for a country |

**Country parameter:** URL slug, e.g. `"united-states"`, `"japan"`,
`"euro-area"`, `"china"`.

**Category detection:** Uses the site's native tab-pane taxonomy (e.g.
`gdp`, `labour`, `prices`, `money`, `trade`, `government`, `business`,
`consumer`, `housing`) when available. Falls back to preceding section
headings, then to a keyword-based heuristic (`categorize_event`) as
last resort.

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
| `category` | Native section id (e.g. "labour") or auto-detected fallback |
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
| `symbol` | Row identifier, e.g. "CL1:COM", "XAUUSD:CUR", "BTCUSD:CUR" |
| `raw_json.decimals` | Display precision from `data-decimals` (when present) |

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

## 4. Reuters (`reuters.py`)

### ReutersNewsClient

Scrapes **article listings** from Reuters section pages by parsing three card
types (`HeroCard`, `BasicCard`, `MediaStoryCard`) via stable `data-testid`
attributes.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(section="markets")` | `list[ScrapedNewsItem]` | Articles for a single section page |
| `fetch_all_news(sections, sleep_between=1.5)` | `list[ScrapedNewsItem]` | Multiple sections with 1.5 s delay between requests |

**Supported sections:** `markets`, `business`, `world`, `sustainability`,
`legal`, `technology`.

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Iran war threatens prolonged hit to global energy markets" |
| `url` | `https://www.reuters.com/business/energy/iran-war-…` |
| `published_at` | `2026-03-07T18:21:43.709Z` (ISO 8601 UTC) |
| `description` | Body snippet (when present on `MediaStoryCard`) |
| `category` | Kicker label: "Business", "Energy", "Sustainability" |
| `image_url` | Card thumbnail URL |
| `raw_json.card_type` | `HeroCard` / `BasicCard` / `MediaStoryCard` |

**Typical yield:** ~10-15 articles per section, ~25-30 across 3 sections
(deduplicated).

### ReutersArticleClient

Fetches and parses **full Reuters articles** with structured metadata.
Uses `curl_cffi` and Reuters-specific selectors for cleaner extraction than
the generic `ArticleFetcher`.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_article(url)` | `ReutersArticle` | Single article with full text and metadata |
| `fetch_articles(urls, sleep_between=1.0)` | `list[ReutersArticle]` | Batch fetch with 1.0 s delay |

**Metadata sources:**

- **JSON-LD** (`@type: "NewsArticle"`): `articleSection`, `keywords`,
  `datePublished`, `image`.
- **HTML**: `<h1 data-testid="Heading">` for headline,
  `<a data-testid="AuthorNameLink">` for authors, `<time>` for date.
- **Body**: paragraph `<div>` elements matched by CSS-module class prefix
  `article-body-module__paragraph__*`.  Boilerplate lines (sign-up prompts,
  trust badges) are filtered out.

**`ReutersArticle` fields:**

| Field | Type | Example |
|-------|------|---------|
| `url` | `str` | Article URL |
| `title` | `str` | "Iran war threatens prolonged hit to global energy markets" |
| `content` | `str` | Full body as plain text (paragraphs joined by `\n\n`) |
| `authors` | `list[str]` | `["Timour Azhari", "Marwa Rashad"]` |
| `published_at` | `str` | `2026-03-07T11:14:35.637Z` |
| `section` | `str` | "Energy" |
| `keywords` | `list[str]` | `["markets commodities energy", "energy oil gas"]` |
| `image_url` | `str` | Lead image URL |
| `fetched` | `bool` | `True` on success |
| `error` | `str \| None` | Error message on failure |

**Keywords cleaning:** Internal Reuters tag codes (`COM`, `ENER`,
`REPI:OPEC`) are stripped.  `TOPIC:*` tags are cleaned and kept (e.g.
`TOPIC:ENERGY-OIL-GAS` → `"energy oil gas"`).

---

## 5. Bloomberg (`bloomberg.py`)

> **Transport:** `curl_cffi` with TLS fingerprint impersonation. Cookies
> are exported from a real Chrome session via `browser_cookie3`.

### Setup

```bash
pip install browser-cookie3
```

**Cookie export** — log in to bloomberg.com in your regular Chrome browser,
then export cookies:

```python
import browser_cookie3, json
from pathlib import Path

cj = list(browser_cookie3.chrome(domain_name=".bloomberg.com"))
cookies = [{"name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "expires": c.expires or -1,
            "secure": bool(c.secure), "httpOnly": False, "sameSite": "Lax"}
           for c in cj]
out = Path.home() / ".analyst" / "bloomberg_cookies.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(cookies, indent=2))
```

### BloombergNewsClient

Scrapes **article listings** from Bloomberg section pages by navigating
with Playwright, then parsing the rendered HTML via three strategies:
`__NEXT_DATA__` JSON → JSON-LD → DOM `<article>` elements.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(section="markets")` | `list[ScrapedNewsItem]` | Articles for a single section page |
| `fetch_all_news(sections, sleep_between=1.5)` | `list[ScrapedNewsItem]` | Multiple sections with 1.5 s delay, dedup by URL |

**Supported sections:** `markets`, `economics`, `technology`, `politics`,
`wealth`, `opinion`, `green`.

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Fed Signals Further Rate Cuts Amid Slowdown" |
| `url` | `https://www.bloomberg.com/news/articles/2026-03-…` |
| `published_at` | `2026-03-08T14:30:00Z` |
| `description` | Article summary / abstract |
| `category` | Section or primary category from JSON |
| `image_url` | Lead image URL |

### BloombergArticleClient

Fetches and parses **full Bloomberg articles** with structured metadata.
Requires an authenticated session (cookies from `login()`).

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_article(url)` | `BloombergArticle` | Single article with full text and metadata |
| `fetch_articles(urls, sleep_between=1.5)` | `list[BloombergArticle]` | Batch fetch with 1.5 s delay |

**Metadata sources (3-tier):**

1. **JSON-LD** (`@type: "Article"`): `headline`, `datePublished`, `author`,
   `articleSection`, `keywords`, `image`.
2. **OpenGraph meta tags**: `og:title`, `og:image`, `article:published_time`,
   `article:author`, `article:section`.
3. **DOM selectors**: `<h1>` for headline, `<a href="/authors/…">` for byline,
   `<time>` for date, `<p>` elements in body container for content.

**`BloombergArticle` fields:**

| Field | Type | Example |
|-------|------|---------|
| `url` | `str` | Article URL |
| `title` | `str` | "Fed Signals Further Rate Cuts Amid Slowdown" |
| `content` | `str` | Full body as plain text (paragraphs joined by `\n\n`) |
| `authors` | `list[str]` | `["Craig Torres", "Liz Capo McCormick"]` |
| `published_at` | `str` | `2026-03-08T14:30:00Z` |
| `section` | `str` | "Markets" |
| `keywords` | `list[str]` | `["federal reserve", "interest rates"]` |
| `image_url` | `str` | Lead image URL |
| `lede` | `str` | Bloomberg-specific article summary / description |
| `fetched` | `bool` | `True` on success |
| `error` | `str \| None` | Error message on failure |

**Body filtering:** Sign-up prompts, newsletter CTAs, terms-of-service links,
and related teasers are stripped from article content.

---

## 6. rateprobability.com (`rateprobability.py`)

> **Transport:** Plain `requests.Session` — no Cloudflare or bot protection.

### RateProbabilityClient

Fetches **FedWatch-equivalent FOMC rate probabilities** from the
rateprobability.com JSON API (`/api/latest`). Updated every 2 minutes at source.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_probabilities()` | `FedRateProbability` | Full snapshot of current rate probabilities and historical comparisons |

**`FedRateProbability` fields:**

| Field | Type | Example |
|-------|------|---------|
| `as_of` | `str` | `"2026-03-08T14:30:00Z"` |
| `current_band` | `str` | `"4.25-4.50"` |
| `midpoint` | `float` | `4.375` |
| `effr` | `float` | `4.33` |
| `meetings` | `list[FedMeetingProbability]` | Per-meeting probability data |
| `snapshots` | `dict[str, list]` | Historical comparisons (1w, 3w, 6w, 10w ago) |

**`FedMeetingProbability` fields:**

| Field | Type | Example |
|-------|------|---------|
| `meeting_date` | `str` | `"2026-06-17"` |
| `implied_rate` | `float` | `4.125` |
| `prob_move_pct` | `float` | `72.5` |
| `is_cut` | `bool` | `True` |
| `num_moves` | `int` | `1` |
| `change_bps` | `float` | `-25.0` |

**Storage:** Upserted into `indicators` table as `FEDPROB_{meeting_date}`
series (source `rateprobability`), value = `implied_rate`.

---

## 7. NY Fed Markets API (`nyfed.py`)

> **Transport:** Plain `requests.Session` — official public API, no bot protection.

### NYFedRatesClient

Fetches **daily reference rates** (SOFR, EFFR, OBFR) from the NY Fed
Markets API (`markets.newyorkfed.org`).

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_sofr(last_n=5)` | `list[NYFedRate]` | Last N SOFR observations |
| `fetch_effr(last_n=5)` | `list[NYFedRate]` | Last N EFFR observations |
| `fetch_obfr(last_n=5)` | `list[NYFedRate]` | Last N OBFR observations |
| `fetch_all_rates(last_n=5)` | `list[NYFedRate]` | All three rate types with 0.5 s delay between |

**`NYFedRate` fields:**

| Field | Type | Example |
|-------|------|---------|
| `date` | `str` | `"2026-03-07"` |
| `type` | `str` | `"SOFR"`, `"EFFR"`, `"OBFR"` |
| `rate` | `float` | `4.31` |
| `percentile_1` | `float \| None` | `4.30` |
| `percentile_25` | `float \| None` | `4.31` |
| `percentile_75` | `float \| None` | `4.32` |
| `percentile_99` | `float \| None` | `4.34` |
| `volume_billions` | `float \| None` | `2180.0` |
| `target_rate_from` | `float \| None` | `4.25` (EFFR only) |
| `target_rate_to` | `float \| None` | `4.50` (EFFR only) |

**Storage:** Upserted into `indicators` table as `NYFED_SOFR`,
`NYFED_EFFR`, `NYFED_OBFR` series (source `nyfed`), value = rate.

---

## 8. Financial Times (`ft.py`)

> **Transport:** `curl_cffi` with TLS fingerprint impersonation. Cookies
> are exported from a real Chrome session via `browser_cookie3`.

### Setup

```bash
pip install browser-cookie3
```

**Cookie export** — log in to ft.com in your regular Chrome browser,
then export cookies:

```python
import browser_cookie3, json
from pathlib import Path

cj = list(browser_cookie3.chrome(domain_name=".ft.com"))
cj += list(browser_cookie3.chrome(domain_name="ft.com"))
seen, cookies = set(), []
for c in cj:
    key = (c.name, c.domain)
    if key not in seen and "ft.com" in c.domain:
        seen.add(key)
        cookies.append({"name": c.name, "value": c.value, "domain": c.domain,
                        "path": c.path, "expires": c.expires or -1,
                        "secure": bool(c.secure), "httpOnly": False, "sameSite": "Lax"})
out = Path.home() / ".analyst" / "ft_cookies.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(cookies, indent=2))
```

### FTNewsClient

Scrapes **article listings** from FT section pages by navigating
with Playwright, then parsing the rendered HTML via three strategies:
`__NEXT_DATA__` JSON → JSON-LD → DOM `<article>` elements.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(section="markets")` | `list[ScrapedNewsItem]` | Articles for a single section page |
| `fetch_all_news(sections, sleep_between=1.5)` | `list[ScrapedNewsItem]` | Multiple sections with 1.5 s delay, dedup by URL |

**Supported sections:** `markets`, `world`, `companies`, `opinion`,
`climate`, `technology`.

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Bank of England holds rates amid inflation uncertainty" |
| `url` | `https://www.ft.com/content/abc123-…` |
| `published_at` | `2026-03-08T14:30:00Z` |
| `description` | Article standfirst / summary |
| `category` | Section or primary category from JSON |
| `image_url` | Lead image URL |

### FTArticleClient

Fetches and parses **full FT articles** with structured metadata.
Requires an authenticated session (cookies from `login()`).

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_article(url)` | `FTArticle` | Single article with full text and metadata |
| `fetch_articles(urls, sleep_between=1.5)` | `list[FTArticle]` | Batch fetch with 1.5 s delay |

**Metadata sources (3-tier):**

1. **JSON-LD** (`@type: "Article"`): `headline`, `datePublished`, `author`,
   `articleSection`, `keywords`, `image`.
2. **OpenGraph meta tags**: `og:title`, `og:image`, `article:published_time`,
   `article:author`, `article:section`.
3. **DOM selectors**: `<h1>` for headline, `<a href="/stream/…">` for byline,
   `<time>` for date, `<p>` elements in body container for content.

**`FTArticle` fields:**

| Field | Type | Example |
|-------|------|---------|
| `url` | `str` | Article URL |
| `title` | `str` | "Bank of England holds rates amid inflation uncertainty" |
| `content` | `str` | Full body as plain text (paragraphs joined by `\n\n`) |
| `authors` | `list[str]` | `["Chris Giles", "Valentina Romei"]` |
| `published_at` | `str` | `2026-03-08T14:30:00Z` |
| `section` | `str` | "Markets" |
| `keywords` | `list[str]` | `["bank of england", "interest rates"]` |
| `image_url` | `str` | Lead image URL |
| `standfirst` | `str` | FT-specific subheading summary |
| `fetched` | `bool` | `True` on success |
| `error` | `str \| None` | Error message on failure |

**Body filtering:** Sign-up prompts, newsletter CTAs, subscriber barriers,
and topic-follow prompts are stripped from article content.

---

## 9. Wall Street Journal (`wsj.py`)

> **Transport:** `curl_cffi` with TLS fingerprint impersonation. WSJ's bot
> detection blocks Playwright, so cookies are exported from a real Chrome
> session via `browser_cookie3`.

### Setup

```bash
pip install browser-cookie3
```

**Cookie export** — log in to wsj.com in your regular Chrome browser,
then export cookies:

```python
import browser_cookie3, json
from pathlib import Path

cj = browser_cookie3.chrome(domain_name=".wsj.com")
cookies = [{"name": c.name, "value": c.value, "domain": c.domain,
            "path": c.path, "expires": c.expires or -1,
            "secure": bool(c.secure), "httpOnly": False, "sameSite": "Lax"}
           for c in cj]
out = Path.home() / ".analyst" / "wsj_cookies.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(cookies, indent=2))
```

### WSJNewsClient

Scrapes **article listings** from WSJ section pages by navigating
with Playwright, then parsing the rendered HTML via three strategies:
`__NEXT_DATA__` JSON → JSON-LD → DOM `<article>` elements.

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_news(section="markets")` | `list[ScrapedNewsItem]` | Articles for a single section page |
| `fetch_all_news(sections, sleep_between=1.5)` | `list[ScrapedNewsItem]` | Multiple sections with 1.5 s delay, dedup by URL |

**Supported sections:** `markets`, `economy`, `business`, `tech`,
`politics`, `opinion`, `world`.

**Fields per item:**

| Field | Example |
|-------|---------|
| `title` | "Treasury Yields Rise on Stronger-Than-Expected Jobs Data" |
| `url` | `https://www.wsj.com/finance/stocks/treasury-yields-…` |
| `published_at` | `2026-03-08T14:30:00Z` |
| `description` | Article dek / summary |
| `category` | Section or primary category from JSON |
| `image_url` | Lead image URL |

### WSJArticleClient

Fetches and parses **full WSJ articles** with structured metadata.
Requires an authenticated session (cookies from `login()`).

| Method | Returns | Description |
|--------|---------|-------------|
| `fetch_article(url)` | `WSJArticle` | Single article with full text and metadata |
| `fetch_articles(urls, sleep_between=1.5)` | `list[WSJArticle]` | Batch fetch with 1.5 s delay |

**Metadata sources (3-tier):**

1. **JSON-LD** (`@type: "Article"`): `headline`, `datePublished`, `author`,
   `articleSection`, `keywords`, `image`.
2. **OpenGraph/meta tags**: `og:title`, `og:image`, `article:published_time`,
   `article:section`, `<meta name="author">` for byline.
3. **DOM selectors**: `<h1>` for headline, `<a href="/author/…">` for byline,
   `<time>` for date, `<p class="…Paragraph…">` for body content.

**`WSJArticle` fields:**

| Field | Type | Example |
|-------|------|---------|
| `url` | `str` | Article URL |
| `title` | `str` | "Treasury Yields Rise on Stronger-Than-Expected Jobs Data" |
| `content` | `str` | Full body as plain text (paragraphs joined by `\n\n`) |
| `authors` | `list[str]` | `["Sam Goldfarb", "Matt Grossman"]` |
| `published_at` | `str` | `2026-03-08T14:30:00Z` |
| `section` | `str` | "Markets" |
| `keywords` | `list[str]` | `["treasurys", "bond market"]` |
| `image_url` | `str` | Lead image URL |
| `dek` | `str` | WSJ-specific sub-headline summary |
| `fetched` | `bool` | `True` on success |
| `error` | `str \| None` | Error message on failure |

**Body filtering:** Subscribe prompts, copyright notices, Dow Jones
legalese, and "What to Read Next" sections are stripped from article
content.

---

## Summary Matrix

| Site | Calendar | News | Articles | Indicators | Markets |
|------|:--------:|:----:|:--------:|:----------:|:-------:|
| **Investing.com** | `InvestingCalendarClient` | `InvestingNewsClient` | — | — | — |
| **ForexFactory** | `ForexFactoryCalendarClient` | `ForexFactoryNewsClient` | — | — | — |
| **TradingEconomics** | `TradingEconomicsCalendarClient` | `TradingEconomicsNewsClient` | — | `TradingEconomicsIndicatorsClient` | `TradingEconomicsMarketsClient` |
| **Reuters** | — | `ReutersNewsClient` | `ReutersArticleClient` | — | — |
| **Bloomberg** | — | `BloombergNewsClient` | `BloombergArticleClient` | — | — |
| **FT** | — | `FTNewsClient` | `FTArticleClient` | — | — |
| **WSJ** | — | `WSJNewsClient` | `WSJArticleClient` | — | — |
| **rateprobability.com** | — | — | — | `RateProbabilityClient` | — |
| **NY Fed** | — | — | — | `NYFedRatesClient` | — |

## Running Tests

```bash
# Unit tests only (no network, fast)
pytest tests/test_scrapers.py -m "not live" -v

# Live integration tests (hits real endpoints)
pytest tests/test_scrapers.py -m live -v

# All scraper tests
pytest tests/test_scrapers.py -v
```
