"""Unit tests for the gov_report scraper parsing helpers."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from analyst.ingestion.scrapers.gov_report import (
    GovReportClient,
    GovReportItem,
    USGovReportClient,
    CNGovReportClient,
    JPGovReportClient,
    EUGovReportClient,
    _extract_content,
    _extract_date_cn,
    _extract_date_en,
    _extract_title,
    _html_to_markdown,
    _link_matches_keywords,
    _resolve_url,
)


class TestExtractDateEn(unittest.TestCase):
    def test_month_day_year(self):
        html = "Released January 15, 2026"
        patterns = [
            r"(?:Released|Issued)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
        ]
        self.assertEqual(_extract_date_en(html, patterns), "2026-01-15")

    def test_iso_date(self):
        html = "Date: 2025-12-01"
        patterns = [r"(\d{4}-\d{2}-\d{2})"]
        self.assertEqual(_extract_date_en(html, patterns), "2025-12-01")

    def test_no_match(self):
        html = "No date here"
        patterns = [r"(\d{4}-\d{2}-\d{2})"]
        self.assertIsNone(_extract_date_en(html, patterns))

    def test_day_month_year(self):
        html = "Published 15 January 2026"
        patterns = [r"(\d{1,2} \w+ \d{4})"]
        self.assertEqual(_extract_date_en(html, patterns), "2026-01-15")


class TestExtractDateCn(unittest.TestCase):
    def test_chinese_date(self):
        html = "发布时间：2025年12月1日"
        self.assertEqual(_extract_date_cn(html), "2025-12-01")

    def test_meta_pubdate(self):
        html = '<meta name="PubDate" content="2025/11/15 09:00">'
        self.assertEqual(_extract_date_cn(html), "2025-11-15")

    def test_slash_format(self):
        html = "日期 2025/03/20"
        self.assertEqual(_extract_date_cn(html), "2025-03-20")

    def test_no_date(self):
        html = "<p>没有日期的页面</p>"
        self.assertIsNone(_extract_date_cn(html))


class TestExtractTitle(unittest.TestCase):
    def test_h1_match(self):
        html = "<html><head><title>Page</title></head><body><h1>Main Title</h1></body></html>"
        self.assertEqual(_extract_title(html, ["h1", "title"]), "Main Title")

    def test_fallback_to_title_tag(self):
        html = "<html><head><title>Fallback</title></head><body><p>text</p></body></html>"
        self.assertEqual(_extract_title(html, ["h1"]), "Fallback")

    def test_empty(self):
        html = "<html><body></body></html>"
        self.assertEqual(_extract_title(html, ["h1", "h2"]), "")


class TestExtractContent(unittest.TestCase):
    def test_selector_match(self):
        html = '<html><body><div id="content">Hello</div><div id="other">Bye</div></body></html>'
        result = _extract_content(html, ["#content"])
        self.assertIn("Hello", result)
        self.assertNotIn("Bye", result)

    def test_noise_removal(self):
        html = "<html><body><script>evil()</script><div id='main'>Clean</div></body></html>"
        result = _extract_content(html, ["#main"])
        self.assertNotIn("evil", result)
        self.assertIn("Clean", result)

    def test_fallback_to_body(self):
        html = "<html><body><p>Body content</p></body></html>"
        result = _extract_content(html, ["#nonexistent"])
        self.assertIn("Body content", result)


class TestHtmlToMarkdown(unittest.TestCase):
    def test_basic_conversion(self):
        html = "<h1>Title</h1><p>Paragraph text.</p>"
        md = _html_to_markdown(html)
        self.assertIn("# Title", md)
        self.assertIn("Paragraph text.", md)

    def test_noise_stripped(self):
        html = "<div><nav>Menu</nav><p>Content</p><script>x()</script></div>"
        md = _html_to_markdown(html)
        self.assertNotIn("Menu", md)
        self.assertNotIn("x()", md)
        self.assertIn("Content", md)

    def test_max_chars(self):
        html = "<p>" + "A" * 20000 + "</p>"
        md = _html_to_markdown(html, max_chars=100)
        self.assertLessEqual(len(md), 100)


class TestResolveUrl(unittest.TestCase):
    def test_absolute(self):
        self.assertEqual(
            _resolve_url("https://example.com/page", "https://base.com"),
            "https://example.com/page",
        )

    def test_relative(self):
        result = _resolve_url("/path/to/page.html", "https://example.com")
        self.assertEqual(result, "https://example.com/path/to/page.html")

    def test_relative_nested(self):
        result = _resolve_url("subdir/page.html", "https://example.com/dir")
        self.assertIn("example.com", result)
        self.assertIn("subdir/page.html", result)


class TestLinkMatchesKeywords(unittest.TestCase):
    def _make_tag(self, text, href=""):
        from bs4 import BeautifulSoup
        html = f'<a href="{href}">{text}</a>'
        return BeautifulSoup(html, "html.parser").find("a")

    def test_text_match(self):
        tag = self._make_tag("GDP Report Q4 2025")
        self.assertTrue(_link_matches_keywords(tag, ["gdp"]))

    def test_no_match(self):
        tag = self._make_tag("Weather Forecast")
        self.assertFalse(_link_matches_keywords(tag, ["gdp"]))

    def test_href_match(self):
        tag = self._make_tag("Click here", "/releases/gdp.html")
        self.assertTrue(_link_matches_keywords(tag, ["gdp"]))

    def test_extra_keywords(self):
        tag = self._make_tag("Caixin China Manufacturing PMI")
        self.assertTrue(_link_matches_keywords(tag, ["caixin"], ["pmi", "china"]))

    def test_extra_keywords_missing(self):
        tag = self._make_tag("Caixin Report")
        self.assertFalse(_link_matches_keywords(tag, ["caixin"], ["pmi", "china"]))


class TestGovReportItem(unittest.TestCase):
    def test_frozen(self):
        item = GovReportItem(
            source="gov_bls",
            source_id="us_bls_cpi",
            title="CPI Report",
            url="https://bls.gov/cpi",
            published_at="2025-12-01",
            institution="BLS",
            country="US",
            language="en",
            data_category="inflation",
        )
        self.assertEqual(item.source, "gov_bls")
        with self.assertRaises(AttributeError):
            item.title = "new"  # type: ignore[misc]


class TestClientInstantiation(unittest.TestCase):
    def test_us_client(self):
        client = USGovReportClient()
        self.assertIsNotNone(client.session)

    def test_cn_client(self):
        client = CNGovReportClient()
        self.assertIsNotNone(client.session)

    def test_jp_client(self):
        client = JPGovReportClient()
        self.assertIsNotNone(client.session)

    def test_eu_client(self):
        client = EUGovReportClient()
        self.assertIsNotNone(client.session)

    def test_facade(self):
        client = GovReportClient()
        self.assertIsInstance(client.us, USGovReportClient)
        self.assertIsInstance(client.cn, CNGovReportClient)
        self.assertIsInstance(client.jp, JPGovReportClient)
        self.assertIsInstance(client.eu, EUGovReportClient)


class TestUSFetchFixedUrl(unittest.TestCase):
    """Test fixed-URL strategy with mocked HTTP."""

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_bls_cpi(self, mock_get):
        mock_get.return_value = """
        <html>
        <head><title>BLS CPI</title></head>
        <body>
            <div id="news-release">
                <h2>Consumer Price Index - January 2026</h2>
                <p>Released February 12, 2026</p>
                <p>The Consumer Price Index rose 0.3 percent.</p>
            </div>
        </body>
        </html>
        """
        client = USGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _US_SOURCES
        item = client._fetch_fixed_url("us_bls_cpi", _US_SOURCES["us_bls_cpi"])
        self.assertIsNotNone(item)
        self.assertEqual(item.source_id, "us_bls_cpi")
        self.assertIn("Consumer Price Index", item.title)
        self.assertEqual(item.published_at, "2026-02-12")
        self.assertEqual(item.country, "US")
        self.assertEqual(item.data_category, "inflation")


class TestUSFetchListingRegex(unittest.TestCase):
    """Test listing-regex strategy with mocked HTTP."""

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_fomc_statement(self, mock_get):
        listing_html = """
        <html><body>
        <a href="/newsevents/pressreleases/monetary20260130a.htm">Jan 2026 Statement</a>
        </body></html>
        """
        detail_html = """
        <html><head><title>FOMC Statement</title></head>
        <body>
        <div id="content">
            <h1>Federal Reserve issues FOMC statement</h1>
            <p>Released January 30, 2026</p>
            <p>The Federal Open Market Committee decided to maintain the target range.</p>
        </div>
        </body></html>
        """
        mock_get.side_effect = [listing_html, detail_html]
        client = USGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _US_SOURCES
        item = client._fetch_listing_regex("us_fed_fomc_statement", _US_SOURCES["us_fed_fomc_statement"])
        self.assertIsNotNone(item)
        self.assertEqual(item.source_id, "us_fed_fomc_statement")
        self.assertIn("FOMC", item.title)
        self.assertEqual(item.published_at, "2026-01-30")


class TestCNFetchListingKeywords(unittest.TestCase):
    """Test CN keyword strategy with mocked HTTP."""

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_nbs_cpi(self, mock_get):
        listing_html = """
        <html><body>
        <a href="/sj/zxfb/202602/t20260215_12345.html">2026年1月份居民消费价格同比上涨0.5%</a>
        <a href="/sj/zxfb/202602/t20260215_12346.html">其他数据</a>
        </body></html>
        """
        detail_html = """
        <html>
        <head>
            <title>居民消费价格</title>
            <meta name="PubDate" content="2026/02/15 09:30">
        </head>
        <body>
        <h1>2026年1月份居民消费价格同比上涨0.5%</h1>
        <div class="TRS_Editor">
            <p>国家统计局今天发布了2026年1月份全国居民消费价格指数。</p>
        </div>
        </body></html>
        """
        mock_get.side_effect = [listing_html, detail_html]
        client = CNGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _CN_SOURCES
        item = client._fetch_listing_keywords("cn_nbs_cpi", _CN_SOURCES["cn_nbs_cpi"])
        self.assertIsNotNone(item)
        self.assertEqual(item.source_id, "cn_nbs_cpi")
        self.assertEqual(item.country, "CN")
        self.assertEqual(item.language, "zh")
        self.assertEqual(item.published_at, "2026-02-15")
        self.assertIn("居民消费价格", item.title)


class TestEURssFetch(unittest.TestCase):
    """Test RSS strategy with mocked feedparser."""

    @patch("analyst.ingestion.scrapers.gov_report.feedparser.parse")
    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_ecb_press_rss(self, mock_get, mock_parse):
        mock_parse.return_value = MagicMock(
            entries=[
                MagicMock(
                    **{
                        "get.side_effect": lambda k, d="": {
                            "link": "https://www.ecb.europa.eu/press/pr/date/2026/html/test.en.html",
                            "title": "ECB Press Release",
                            "published": "Wed, 15 Jan 2026 10:00:00 GMT",
                            "summary": "<p>ECB decided to keep rates unchanged.</p>",
                        }.get(k, d),
                    }
                )
            ]
        )
        mock_get.return_value = """
        <html><head><title>ECB Press</title></head>
        <body>
        <h1 class="ecb-pressHeadline">ECB Press Release</h1>
        <div class="ecb-pressContent">
            <p>15 January 2026</p>
            <p>The Governing Council decided to keep rates unchanged.</p>
        </div>
        </body></html>
        """
        client = EUGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _EU_SOURCES
        item = client._fetch_rss("eu_ecb_press", _EU_SOURCES["eu_ecb_press"])
        self.assertIsNotNone(item)
        self.assertEqual(item.source_id, "eu_ecb_press")
        self.assertEqual(item.country, "EU")
        self.assertIn("ECB", item.title)


class TestGovReportIngestionClient(unittest.TestCase):
    """Test the ingestion client wiring."""

    @patch("analyst.ingestion.sources.GovReportClient")
    def test_refresh(self, mock_client_cls):
        from analyst.ingestion.sources import GovReportIngestionClient

        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.fetch_all.return_value = [
            GovReportItem(
                source="gov_bls",
                source_id="us_bls_cpi",
                title="CPI Report",
                url="https://bls.gov/cpi",
                published_at="2025-12-01",
                institution="BLS",
                country="US",
                language="en",
                data_category="inflation",
                importance="high",
                content_markdown="# CPI\nThe CPI rose.",
            ),
        ]
        mock_store = MagicMock()
        mock_store.document_exists.return_value = False
        mock_store.news_article_exists.return_value = False

        ingestion = GovReportIngestionClient()
        stats = ingestion.refresh(mock_store)
        self.assertEqual(stats.source, "gov_reports")
        self.assertEqual(stats.count, 1)
        mock_store.upsert_document.assert_called_once()
        mock_store.upsert_news_article.assert_called_once()
        stored_doc = mock_store.upsert_document.call_args.args[0]
        self.assertEqual(stored_doc.published_date, "2025-12-01")
        self.assertEqual(stored_doc.published_at, "2025-12-01T00:00:00+00:00")
        self.assertEqual(
            stored_doc.published_epoch_ms,
            int(datetime(2025, 12, 1, tzinfo=timezone.utc).timestamp() * 1000),
        )

    @patch("analyst.ingestion.sources.GovReportClient")
    def test_refresh_skips_existing(self, mock_client_cls):
        from analyst.ingestion.sources import GovReportIngestionClient

        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.fetch_all.return_value = [
            GovReportItem(
                source="gov_bls",
                source_id="us_bls_cpi",
                title="CPI Report",
                url="https://bls.gov/cpi",
                published_at="2025-12-01",
                institution="BLS",
                country="US",
                language="en",
                data_category="inflation",
            ),
        ]
        mock_store = MagicMock()
        mock_store.news_article_exists.return_value = True

        ingestion = GovReportIngestionClient()
        stats = ingestion.refresh(mock_store)
        self.assertEqual(stats.count, 0)
        mock_store.upsert_news_article.assert_not_called()


if __name__ == "__main__":
    unittest.main()
