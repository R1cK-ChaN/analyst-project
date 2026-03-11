"""Tests for URL canonicalization and content fingerprinting."""

from __future__ import annotations

from analyst.ingestion.url_canon import canonicalize_url, content_hash, normalize_title


class TestCanonicalizeUrl:
    def test_strips_utm_params(self):
        url = "https://reuters.com/article?utm_source=twitter&utm_medium=social"
        assert canonicalize_url(url) == "https://reuters.com/article"

    def test_strips_fbclid(self):
        url = "https://example.com/news?fbclid=abc123"
        assert canonicalize_url(url) == "https://example.com/news"

    def test_preserves_meaningful_params(self):
        url = "https://example.com/search?page=2&q=rates"
        result = canonicalize_url(url)
        assert "page=2" in result
        assert "q=rates" in result

    def test_removes_fragment(self):
        url = "https://example.com/article#section-3"
        assert canonicalize_url(url) == "https://example.com/article"

    def test_lowercases_scheme_and_host(self):
        url = "HTTPS://Reuters.COM/article"
        assert canonicalize_url(url) == "https://reuters.com/article"

    def test_sorts_query_params(self):
        url = "https://example.com/article?b=2&a=1"
        assert canonicalize_url(url) == "https://example.com/article?a=1&b=2"

    def test_normalizes_trailing_slash(self):
        url = "https://example.com/article/"
        assert canonicalize_url(url) == "https://example.com/article"

    def test_preserves_root_trailing_slash(self):
        url = "https://example.com/"
        assert canonicalize_url(url) == "https://example.com/"

    def test_identity_for_clean_url(self):
        url = "https://example.com/2024/01/article-title"
        assert canonicalize_url(url) == url

    def test_strips_multiple_tracking_params(self):
        url = "https://cnbc.com/article?utm_source=x&gclid=y&msclkid=z&page=3"
        result = canonicalize_url(url)
        assert "utm_source" not in result
        assert "gclid" not in result
        assert "msclkid" not in result
        assert "page=3" in result


class TestNormalizeTitle:
    def test_basic(self):
        assert normalize_title("Fed Raises Rates!") == "fed raises rates"

    def test_collapses_whitespace(self):
        assert normalize_title("  Fed   raises  rates  ") == "fed raises rates"

    def test_strips_punctuation(self):
        assert normalize_title("U.S. GDP: 3.2%") == "us gdp 32"


class TestContentHash:
    def test_same_hour(self):
        ts1 = 3600 * 100 + 100  # some time within hour 100
        ts2 = 3600 * 100 + 200  # same hour
        assert content_hash("Fed holds rates", ts1) == content_hash("Fed holds rates", ts2)

    def test_different_hour(self):
        ts1 = 3600 * 100
        ts2 = 3600 * 101
        assert content_hash("Fed holds rates", ts1) != content_hash("Fed holds rates", ts2)

    def test_boundary(self):
        """ts=3599 (hour 0) vs ts=3600 (hour 1) → different hashes."""
        assert content_hash("Test title", 3599) != content_hash("Test title", 3600)

    def test_case_insensitive(self):
        ts = 3600 * 100
        assert content_hash("Fed Holds Rates", ts) == content_hash("fed holds rates", ts)
