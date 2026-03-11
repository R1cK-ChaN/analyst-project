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
    _extract_datetime_en,
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

    def test_embargo_datetime_et_normalized_to_utc(self):
        html = (
            "Transmission of material in this release is embargoed until "
            "8:30 a.m. (ET) Wednesday, March 11, 2026"
        )
        patterns = [
            r"embargoed until\s*([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*(?:\([A-Z]{2,4}\)|[A-Z]{2,4})\s*\w+,\s*\w+\s+\d{1,2},\s*\d{4})",
        ]
        self.assertEqual(
            _extract_datetime_en(html, patterns, default_timezone="America/New_York"),
            "2026-03-11T12:30:00+00:00",
        )

    def test_embargo_datetime_with_release_code_normalized_to_utc(self):
        html = (
            "Transmission of material in this release is embargoed until USDL 26-0289 "
            "8:30 a.m. (ET) Friday, February 27, 2026"
        )
        patterns = [
            r"embargoed until.*?([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*(?:\([A-Z]{2,4}\)|[A-Z]{2,4})\s*\w+,\s*\w+\s+\d{1,2},\s*\d{4})",
        ]
        self.assertEqual(
            _extract_datetime_en(html, patterns, default_timezone="America/New_York"),
            "2026-02-27T13:30:00+00:00",
        )


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
                <h2>Consumer Price Index - March 2026</h2>
                <p>Transmission of material in this release is embargoed until
                8:30 a.m. (ET) Wednesday, March 11, 2026</p>
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
        self.assertEqual(item.published_at, "2026-03-11T12:30:00+00:00")
        self.assertEqual(item.published_precision, "exact")
        self.assertEqual(item.country, "US")
        self.assertEqual(item.data_category, "inflation")

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_bls_ppi_with_release_code(self, mock_get):
        mock_get.return_value = """
        <html>
        <head><title>BLS PPI</title></head>
        <body>
            <div id="news-release">
                <h2>Producer Price Index News Release</h2>
                <p>Transmission of material in this release is embargoed until USDL 26-0289
                8:30 a.m. (ET) Friday, February 27, 2026</p>
                <p>The Producer Price Index for final demand increased 0.5 percent.</p>
            </div>
        </body>
        </html>
        """
        client = USGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _US_SOURCES
        item = client._fetch_fixed_url("us_bls_ppi", _US_SOURCES["us_bls_ppi"])
        self.assertIsNotNone(item)
        self.assertEqual(item.published_at, "2026-02-27T13:30:00+00:00")
        self.assertEqual(item.published_precision, "exact")


class TestUSFetchListingRegex(unittest.TestCase):
    """Test listing-regex strategy with mocked HTTP."""

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_fomc_statement(self, mock_get):
        listing_html = """
        <html><body>
        <a href="/newsevents/pressreleases/2026-press-fomc.htm">2026 FOMC</a>
        </body></html>
        """
        archive_html = """
        <html><body>
        <a href="/newsevents/pressreleases/monetary20260128a.htm">Federal Reserve issues FOMC statement</a>
        </body></html>
        """
        detail_html = """
        <html><head><title>FOMC Statement</title></head>
        <body>
        <div id="content">
            <h1>Federal Reserve issues FOMC statement</h1>
            <p>January 28, 2026</p>
            <p>For release at 2:00 p.m. EST</p>
            <p>The Federal Open Market Committee decided to maintain the target range.</p>
        </div>
        </body></html>
        """
        mock_get.side_effect = [listing_html, archive_html, detail_html]
        client = USGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _US_SOURCES
        item = client._fetch_listing_regex("us_fed_fomc_statement", _US_SOURCES["us_fed_fomc_statement"])
        self.assertIsNotNone(item)
        self.assertEqual(item.source_id, "us_fed_fomc_statement")
        self.assertIn("FOMC", item.title)
        self.assertEqual(item.published_at, "2026-01-28T19:00:00+00:00")
        self.assertEqual(item.published_precision, "exact")


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
        self.assertEqual(item.published_at, "2026-02-15T01:30:00+00:00")
        self.assertEqual(item.published_precision, "exact")
        self.assertIn("居民消费价格", item.title)


class TestJPFetchListingRegex(unittest.TestCase):
    """Test JP regex/archive strategies with mocked HTTP."""

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_boj_statement_pdf_from_archive(self, mock_get):
        listing_html = """
        <html><body>
        <a href="/en/mopo/mpmdeci/state_2026/index.htm">Statements on Monetary Policy</a>
        </body></html>
        """
        archive_html = """
        <html><body>
        <table><tr>
            <td>Jan. 23, 2026</td>
            <td><a href="/en/mopo/mpmdeci/mpr_2026/k260123a.pdf">Statement on Monetary Policy [PDF 171KB]</a></td>
        </tr></table>
        </body></html>
        """
        mock_get.side_effect = [listing_html, archive_html]
        client = JPGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _JP_SOURCES
        item = client._fetch_listing_regex("jp_boj_statement", _JP_SOURCES["jp_boj_statement"])
        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k260123a.pdf")
        self.assertEqual(item.title, "Statement on Monetary Policy")
        self.assertEqual(item.published_at, "2026-01-23")
        self.assertEqual(item.published_precision, "date_only")

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_boj_outlook_pdf_from_top_listing(self, mock_get):
        listing_html = """
        <html><body>
        <table><tr>
            <td>Jan. 26, 2026</td>
            <td><a href="/en/mopo/outlook/gor2601b.pdf">January 2026 (full text) [PDF 1117KB]</a></td>
        </tr></table>
        </body></html>
        """
        mock_get.return_value = listing_html
        client = JPGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _JP_SOURCES
        item = client._fetch_listing_regex("jp_boj_outlook", _JP_SOURCES["jp_boj_outlook"])
        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://www.boj.or.jp/en/mopo/outlook/gor2601b.pdf")
        self.assertEqual(item.title, "January 2026 (full text)")
        self.assertEqual(item.published_at, "2026-01-26")
        self.assertEqual(item.published_precision, "date_only")

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_boj_minutes_pdf_from_table_year(self, mock_get):
        listing_html = """
        <html><body>
        <table>
            <caption>Table : 2025</caption>
            <tr>
                <td>Jan. 23 (Thurs.), 24 (Fri.)</td>
                <td><a href="/en/mopo/mpmsche_minu/minu_2025/g250124.pdf">Mar. 25 (Tues.) [PDF 481KB]</a></td>
            </tr>
        </table>
        </body></html>
        """
        mock_get.return_value = listing_html
        client = JPGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _JP_SOURCES
        item = client._fetch_listing_regex("jp_boj_minutes", _JP_SOURCES["jp_boj_minutes"])
        self.assertIsNotNone(item)
        self.assertEqual(item.url, "https://www.boj.or.jp/en/mopo/mpmsche_minu/minu_2025/g250124.pdf")
        self.assertEqual(item.title, "Minutes of the Monetary Policy Meetings")
        self.assertEqual(item.published_at, "2025-03-25")
        self.assertEqual(item.published_precision, "date_only")

    @patch("analyst.ingestion.scrapers.gov_report._get_html")
    def test_fetch_cao_gdp_from_year_archive(self, mock_get):
        listing_html = """
        <html><body>
        <a href="/en/sna/data/sokuhou/files/toukei_top.html">Release Archive</a>
        </body></html>
        """
        release_archive_html = """
        <html><body>
        <a href="/en/sna/data/sokuhou/files/2025/toukei_2025.html">2025</a>
        </body></html>
        """
        year_archive_html = """
        <html><body>
        <table><tr>
            <td>Mar 10, 2026</td>
            <td><a href="/en/sna/data/sokuhou/files/2025/qe254_2/gdemenuea.html">
                Quarterly Estimates of GDP for Oct.-Dec.2025 (The Second preliminary Estimates)
            </a></td>
        </tr></table>
        </body></html>
        """
        detail_html = """
        <html><head><title>Oct.-Dec.2025 (The 2nd preliminary)</title></head>
        <body>
            <div id="main">
                <h1>Oct.-Dec.2025 (The 2nd preliminary)</h1>
                <p>Quarterly Estimates of GDP</p>
            </div>
        </body></html>
        """
        mock_get.side_effect = [listing_html, release_archive_html, year_archive_html, detail_html]
        client = JPGovReportClient()
        from analyst.ingestion.scrapers.gov_report import _JP_SOURCES
        item = client._fetch_source("jp_cao_gdp", _JP_SOURCES["jp_cao_gdp"])
        self.assertIsNotNone(item)
        self.assertIn("Oct.-Dec.2025", item.title)
        self.assertEqual(
            item.url,
            "https://www.esri.cao.go.jp/en/sna/data/sokuhou/files/2025/qe254_2/gdemenuea.html",
        )
        self.assertEqual(item.published_at, "2026-03-10")
        self.assertEqual(item.published_precision, "date_only")


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
        self.assertEqual(item.published_at, "2026-01-15T10:00:00+00:00")
        self.assertEqual(item.published_precision, "exact")


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
                published_at="2025-12-01T13:30:00+00:00",
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
        self.assertEqual(stored_doc.published_at, "2025-12-01T13:30:00+00:00")
        self.assertEqual(stored_doc.published_precision, "exact")
        self.assertEqual(
            stored_doc.published_epoch_ms,
            int(datetime(2025, 12, 1, 13, 30, tzinfo=timezone.utc).timestamp() * 1000),
        )
        stored_extra = mock_store.upsert_document_extra.call_args.args[0]
        self.assertEqual(stored_extra.extra_json["published_precision"], "exact")

    @patch("analyst.ingestion.sources.GovReportClient")
    def test_refresh_preserves_date_only_publish_dates(self, mock_client_cls):
        from analyst.ingestion.sources import GovReportIngestionClient

        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.fetch_all.return_value = [
            GovReportItem(
                source="gov_fed",
                source_id="us_fed_fomc_statement",
                title="FOMC Statement",
                url="https://federalreserve.gov/fomc",
                published_at="2025-12-01",
                institution="Federal Reserve",
                country="US",
                language="en",
                data_category="monetary_policy",
            ),
        ]
        mock_store = MagicMock()
        mock_store.document_exists.return_value = False
        mock_store.news_article_exists.return_value = False

        ingestion = GovReportIngestionClient()
        stats = ingestion.refresh(mock_store)
        self.assertEqual(stats.count, 1)
        stored_doc = mock_store.upsert_document.call_args.args[0]
        self.assertEqual(stored_doc.published_date, "2025-12-01")
        self.assertEqual(stored_doc.published_at, "2025-12-01")
        self.assertEqual(stored_doc.published_precision, "date_only")
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
