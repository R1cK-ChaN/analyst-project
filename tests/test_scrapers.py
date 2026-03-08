"""Tests for all scraper modules – calendar, news, indicators, and markets.

Tests marked @pytest.mark.live hit real endpoints and are skipped by default.
Run with:  pytest tests/test_scrapers.py -m live -v
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from analyst.ingestion.scrapers._common import (
    ScrapedIndicator,
    ScrapedMarketQuote,
    ScrapedNewsItem,
    categorize_event,
    generate_event_id,
    parse_numeric_value,
    to_utc_iso,
)
from analyst.ingestion.scrapers.investing import (
    InvestingCalendarClient,
    InvestingNewsClient,
    INVESTING_NEWS_CATEGORIES,
)
from analyst.ingestion.scrapers.forexfactory import (
    ForexFactoryCalendarClient,
    ForexFactoryNewsClient,
)
from analyst.ingestion.scrapers.tradingeconomics import (
    TradingEconomicsCalendarClient,
    TradingEconomicsNewsClient,
    TradingEconomicsIndicatorsClient,
    TradingEconomicsMarketsClient,
)


# ---------------------------------------------------------------------------
# Unit tests for _common helpers
# ---------------------------------------------------------------------------

class TestParseNumericValue:
    def test_plain_number(self):
        assert parse_numeric_value("1.5") == 1.5

    def test_with_commas(self):
        assert parse_numeric_value("1,234.5") == 1234.5

    def test_percentage(self):
        assert parse_numeric_value("3.2%") == 3.2

    def test_suffix_k(self):
        assert parse_numeric_value("1.5K") == 1500.0

    def test_suffix_m(self):
        assert parse_numeric_value("2.1M") == 2_100_000.0

    def test_suffix_b(self):
        assert parse_numeric_value("3B") == 3_000_000_000.0

    def test_none_input(self):
        assert parse_numeric_value(None) is None

    def test_empty_string(self):
        assert parse_numeric_value("") is None

    def test_non_numeric(self):
        assert parse_numeric_value("abc") is None


class TestCategorizeEvent:
    def test_inflation(self):
        assert categorize_event("CPI m/m") == "inflation"

    def test_employment(self):
        assert categorize_event("Nonfarm Payrolls") == "employment"

    def test_growth(self):
        assert categorize_event("GDP Growth Rate") == "growth"

    def test_policy(self):
        assert categorize_event("FOMC Statement") == "policy"

    def test_other(self):
        assert categorize_event("Something Random") == "other"


class TestGenerateEventId:
    def test_deterministic(self):
        a = generate_event_id("US", "CPI", "2026-03-01")
        b = generate_event_id("US", "CPI", "2026-03-01")
        assert a == b
        assert len(a) == 12

    def test_different_inputs(self):
        a = generate_event_id("US", "CPI", "2026-03-01")
        b = generate_event_id("EU", "CPI", "2026-03-01")
        assert a != b


class TestToUtcIso:
    def test_basic(self):
        result = to_utc_iso(date_value="2026-03-08", time_value="14:30")
        assert "2026-03-08" in result
        assert result.endswith("+00:00")

    def test_all_day(self):
        result = to_utc_iso(date_value="2026-03-08", time_value="All Day")
        assert result.endswith("+00:00")

    def test_none_time(self):
        result = to_utc_iso(date_value="2026-03-08")
        assert result.endswith("+00:00")


# ---------------------------------------------------------------------------
# Unit tests for dataclasses
# ---------------------------------------------------------------------------

class TestScrapedDataclasses:
    def test_news_item_creation(self):
        item = ScrapedNewsItem(
            source="test",
            title="Test Title",
            url="https://example.com",
            description="Test desc",
        )
        assert item.source == "test"
        assert item.title == "Test Title"
        assert item.raw_json == {}

    def test_indicator_creation(self):
        ind = ScrapedIndicator(
            source="te",
            country="US",
            name="GDP Growth Rate",
            last="1.4",
            previous="4.4",
        )
        assert ind.country == "US"
        assert ind.last == "1.4"

    def test_market_quote_creation(self):
        q = ScrapedMarketQuote(
            source="te",
            name="Bitcoin",
            asset_class="crypto",
            price="67184",
            change_pct="-0.13%",
        )
        assert q.asset_class == "crypto"


# ---------------------------------------------------------------------------
# Unit tests for news parsers (with mock HTML)
# ---------------------------------------------------------------------------

class TestInvestingNewsParsing:
    SAMPLE_HTML = """
    <html><body>
    <article class="news-analysis-v2_article__wW0pT flex w-full" data-test="article-item">
        <div class="news-analysis-v2_content__z0iLP w-full text-xs sm:flex-1">
            <a data-test="article-title-link"
               href="https://www.investing.com/news/economy-news/test-article-123">
                Test Article Title
            </a>
            <p data-test="article-description">This is the description.</p>
            <ul>
                <li class="flex items-center">
                    <div>
                        <span data-test="news-provider-name">Reuters</span>
                        <time data-test="article-publish-date"
                              datetime="2026-03-08 07:00:00">1 hour ago</time>
                    </div>
                </li>
            </ul>
        </div>
    </article>
    <article class="news-analysis-v2_article__wW0pT flex w-full" data-test="article-item">
        <div class="news-analysis-v2_content__z0iLP w-full text-xs sm:flex-1">
            <a data-test="article-title-link"
               href="https://www.investing.com/news/forex-news/forex-test-456">
                Forex Article
            </a>
            <p data-test="article-description">Forex desc.</p>
            <ul><li><div>
                <span data-test="news-provider-name">Investing.com</span>
                <time data-test="article-publish-date"
                      datetime="2026-03-08 06:30:00">90 minutes ago</time>
            </div></li></ul>
        </div>
    </article>
    </body></html>
    """

    def test_parse_rich_articles(self):
        client = InvestingNewsClient.__new__(InvestingNewsClient)
        items = client._parse_news_html(self.SAMPLE_HTML, "latest-news")
        assert len(items) == 2
        assert items[0].title == "Test Article Title"
        assert items[0].url == "https://www.investing.com/news/economy-news/test-article-123"
        assert items[0].author == "Reuters"
        assert items[0].published_at == "2026-03-08 07:00:00"
        assert items[0].description == "This is the description."
        assert items[0].category == "economy-news"
        assert items[1].category == "forex-news"

    def test_fallback_to_articleitem_format(self):
        html = """
        <html><body>
        <article class="js-article-item articleItem" data-id="999">
            <a class="title" href="/news/stock-market-news/stock-test-789">Stock News</a>
        </article>
        </body></html>
        """
        client = InvestingNewsClient.__new__(InvestingNewsClient)
        items = client._parse_news_html(html, "stock-market-news")
        assert len(items) == 1
        assert items[0].title == "Stock News"
        assert items[0].raw_json == {"data_id": "999"}

    def test_empty_html(self):
        client = InvestingNewsClient.__new__(InvestingNewsClient)
        assert client._parse_news_html("<html></html>", "latest-news") == []

    def test_category_from_url(self):
        assert InvestingNewsClient._category_from_url(
            "https://www.investing.com/news/economy-news/foo-123"
        ) == "economy-news"
        assert InvestingNewsClient._category_from_url("/no-match") == ""


class TestForexFactoryNewsParsing:
    SAMPLE_HTML = """
    <html><body>
    <div class="some-parent">
        <div class="news-block__title fadeout-end">
            <a href="/news/12345-test-article">Oil Surges on Mideast Tensions</a>
        </div>
        <div class="news-block__details fadeout-end darktext">
            From reuters.com|2 hr ago|5 comments
        </div>
        <div class="news-block__preview">Oil prices jumped sharply as tensions escalated.</div>
        <span class="universal-impact universal-impact__impact-high universal-impact__impact-high--ff"></span>
    </div>
    <div class="some-parent">
        <div class="news-block__title fadeout-end">
            <a href="/news/12346-another-article">Fed Meeting Minutes</a>
        </div>
        <div class="news-block__details fadeout-end">
            From @WallStJournal|30 min ago
        </div>
        <div class="news-block__preview">The Federal Reserve released its latest minutes.</div>
        <span class="universal-impact universal-impact__impact-medium universal-impact__impact-medium--ff"></span>
    </div>
    </body></html>
    """

    def test_parse_news_items(self):
        client = ForexFactoryNewsClient.__new__(ForexFactoryNewsClient)
        items = client._parse_news_html(self.SAMPLE_HTML)
        assert len(items) == 2

        assert items[0].title == "Oil Surges on Mideast Tensions"
        assert items[0].url == "https://www.forexfactory.com/news/12345-test-article"
        assert items[0].author == "reuters.com"
        assert items[0].importance == "high"
        assert items[0].description == "Oil prices jumped sharply as tensions escalated."
        assert items[0].raw_json["time_ago"] == "2 hr ago"
        assert items[0].raw_json["comments"] == 5

        assert items[1].title == "Fed Meeting Minutes"
        assert items[1].importance == "medium"
        assert items[1].author == "@WallStJournal"

    def test_parse_details_helper(self):
        src, t, c = ForexFactoryNewsClient._parse_details(
            "From bloomberg.com|4 hr ago|12 comments"
        )
        assert src == "bloomberg.com"
        assert t == "4 hr ago"
        assert c == 12

    def test_parse_details_no_comments(self):
        src, t, c = ForexFactoryNewsClient._parse_details("From reuters.com|1 hr ago")
        assert src == "reuters.com"
        assert t == "1 hr ago"
        assert c == 0

    def test_empty_html(self):
        client = ForexFactoryNewsClient.__new__(ForexFactoryNewsClient)
        assert client._parse_news_html("<html></html>") == []


class TestTradingEconomicsNewsParsing:
    SAMPLE_JSON = """[
        {
            "ID": 100,
            "title": "US GDP Grows 1.4%",
            "description": "The US economy expanded at a 1.4% rate.",
            "url": "/united-states/gdp-growth",
            "author": "John Doe",
            "country": "United States",
            "category": "GDP Growth Rate",
            "image": "",
            "importance": 3,
            "date": "2026-03-07T10:00:00",
            "expiration": "2026-04-06T23:59:00",
            "html": null,
            "type": null,
            "thumbnail": null
        },
        {
            "ID": 101,
            "title": "Crypto Update",
            "description": "Bitcoin fell 3%.",
            "url": "/crypto",
            "author": "CALCULATOR",
            "country": "Crypto",
            "category": "Crypto",
            "image": null,
            "importance": 1,
            "date": "2026-03-07T09:00:00",
            "expiration": "2026-03-08T09:00:00",
            "html": null,
            "type": null,
            "thumbnail": null
        }
    ]"""

    def test_parse_stream_json(self):
        client = TradingEconomicsNewsClient.__new__(TradingEconomicsNewsClient)
        items = client._parse_stream_json(self.SAMPLE_JSON)
        assert len(items) == 2

        assert items[0].title == "US GDP Grows 1.4%"
        assert items[0].url == "https://tradingeconomics.com/united-states/gdp-growth"
        assert items[0].author == "John Doe"
        assert items[0].category == "GDP Growth Rate"
        assert items[0].importance == "high"
        assert items[0].raw_json["country"] == "United States"

        assert items[1].importance == "low"

    def test_invalid_json(self):
        client = TradingEconomicsNewsClient.__new__(TradingEconomicsNewsClient)
        assert client._parse_stream_json("not json") == []

    def test_empty_array(self):
        client = TradingEconomicsNewsClient.__new__(TradingEconomicsNewsClient)
        assert client._parse_stream_json("[]") == []


class TestTradingEconomicsIndicatorsParsing:
    SAMPLE_HTML = """
    <html><body>
    <h3>Labour</h3>
    <table class="table table-hover">
        <tr><th></th><th>Last</th><th>Previous</th><th>Highest</th><th>Lowest</th><th></th><th></th></tr>
        <tr>
            <td><a href="/united-states/unemployment-rate">Unemployment Rate</a></td>
            <td>4.4</td><td>4.3</td><td>14.8</td><td>2.5</td><td>percent</td><td>Feb/26</td>
        </tr>
        <tr>
            <td><a href="/united-states/non-farm-payrolls">Non Farm Payrolls</a></td>
            <td>-92</td><td>126</td><td>4631</td><td>-20469</td><td>Thousand</td><td>Feb/26</td>
        </tr>
    </table>
    </body></html>
    """

    def test_parse_indicators(self):
        client = TradingEconomicsIndicatorsClient.__new__(TradingEconomicsIndicatorsClient)
        indicators = client._parse_indicators_html(self.SAMPLE_HTML, "united-states")
        assert len(indicators) == 2

        assert indicators[0].name == "Unemployment Rate"
        assert indicators[0].last == "4.4"
        assert indicators[0].previous == "4.3"
        assert indicators[0].highest == "14.8"
        assert indicators[0].lowest == "2.5"
        assert indicators[0].unit == "percent"
        assert indicators[0].date == "Feb/26"
        assert indicators[0].country == "US"
        assert indicators[0].category == "employment"
        assert "/unemployment-rate" in indicators[0].url

    def test_empty_html(self):
        client = TradingEconomicsIndicatorsClient.__new__(TradingEconomicsIndicatorsClient)
        assert client._parse_indicators_html("<html></html>", "us") == []


class TestTradingEconomicsMarketsParsing:
    SAMPLE_HTML = """
    <html><body>
    <div id="Commodity">
        <table class="table table-condensed">
            <tr><th></th><th>Actual</th><th>Chg</th><th>%Chg</th></tr>
            <tr><td><a href="/commodity/crude-oil">Crude Oil</a></td><td>90.900</td><td>9.89</td><td>12.21%</td></tr>
            <tr><td><a href="/commodity/gold">Gold</a></td><td>5158.89</td><td>74.70</td><td>1.47%</td></tr>
        </table>
    </div>
    <div id="Crypto">
        <table class="table table-condensed">
            <tr><th></th><th>Actual</th><th>Chg</th><th>%Chg</th></tr>
            <tr><td><a href="/btcusd:cur">Bitcoin</a></td><td>67184</td><td>85</td><td>-0.13%</td></tr>
        </table>
    </div>
    </body></html>
    """

    def test_parse_markets(self):
        client = TradingEconomicsMarketsClient.__new__(TradingEconomicsMarketsClient)
        quotes = client._parse_markets_html(self.SAMPLE_HTML)
        assert len(quotes) == 3

        assert quotes[0].name == "Crude Oil"
        assert quotes[0].asset_class == "commodity"
        assert quotes[0].price == "90.900"
        assert quotes[0].change == "9.89"
        assert quotes[0].change_pct == "12.21%"
        assert "/commodity/crude-oil" in quotes[0].url

        assert quotes[2].name == "Bitcoin"
        assert quotes[2].asset_class == "crypto"

    def test_empty_html(self):
        client = TradingEconomicsMarketsClient.__new__(TradingEconomicsMarketsClient)
        assert client._parse_markets_html("<html></html>") == []


# ---------------------------------------------------------------------------
# Live integration tests (require network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestInvestingLive:
    def test_fetch_news_latest(self):
        client = InvestingNewsClient()
        items = client.fetch_news("latest-news")
        assert len(items) > 0
        for item in items:
            assert item.source == "investing"
            assert item.title
            assert item.url


@pytest.mark.live
class TestForexFactoryLive:
    def test_fetch_news(self):
        client = ForexFactoryNewsClient()
        items = client.fetch_news()
        assert len(items) > 0
        for item in items:
            assert item.source == "forexfactory"
            assert item.title
            assert item.url.startswith("https://www.forexfactory.com/news/")


@pytest.mark.live
class TestTradingEconomicsLive:
    def test_fetch_news(self):
        client = TradingEconomicsNewsClient()
        items = client.fetch_news(count=5)
        assert len(items) > 0
        for item in items:
            assert item.source == "tradingeconomics"
            assert item.title
            assert item.published_at

    def test_fetch_indicators(self):
        client = TradingEconomicsIndicatorsClient()
        indicators = client.fetch_indicators("united-states")
        assert len(indicators) > 50
        names = {ind.name for ind in indicators}
        assert "Unemployment Rate" in names or "GDP Growth Rate" in names
        for ind in indicators:
            assert ind.country == "US"
            assert ind.last

    def test_fetch_markets(self):
        client = TradingEconomicsMarketsClient()
        quotes = client.fetch_markets()
        assert len(quotes) > 30
        classes = {q.asset_class for q in quotes}
        assert "commodity" in classes
        assert "crypto" in classes
        for q in quotes:
            assert q.name
            assert q.price
