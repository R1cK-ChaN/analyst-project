"""Tests for the web_fetch_page tool and ArticleFetcher fetch/extract behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from analyst.ingestion.news_fetcher import ArticleContent, ArticleFetcher
from analyst.macro_data.service import LocalMacroDataService
from analyst.tools._web_fetch import FetchPageConfig, build_web_fetch_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
<article>
<h1>Breaking: Fed Holds Rates Steady</h1>
<p>The Federal Reserve held interest rates unchanged at its latest meeting,
citing ongoing uncertainty in the economic outlook.</p>
<p>Chair Powell noted that inflation has continued to moderate but remains
above the 2% target.</p>
</article>
<footer>Copyright 2025</footer>
</body>
</html>
"""

LONG_CONTENT = "A" * 20_000


def _make_response(html: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code=status_code, text=html, request=httpx.Request("GET", "https://example.com"))


# ---------------------------------------------------------------------------
# ArticleFetcher – fetch & extract behavior
# ---------------------------------------------------------------------------

class TestArticleFetcherExtraction:
    """Test actual fetch + readability + markdownify behavior with mocked HTTP."""

    def test_successful_fetch_extracts_markdown(self):
        fetcher = ArticleFetcher(timeout=5, max_content_chars=15_000)
        with patch.object(fetcher._client, "get", return_value=_make_response(SIMPLE_HTML)):
            result = fetcher.fetch_article("https://example.com/article", rss_description="fallback")

        assert result.fetched is True
        assert result.content_length > 0
        assert "Fed Holds Rates Steady" in result.content
        assert "inflation" in result.content.lower()

    def test_fetch_truncates_at_max_content_chars(self):
        big_html = f"<html><body><article><p>{LONG_CONTENT}</p></article></body></html>"
        fetcher = ArticleFetcher(timeout=5, max_content_chars=500)
        with patch.object(fetcher._client, "get", return_value=_make_response(big_html)):
            result = fetcher.fetch_article("https://example.com/big", rss_description="")

        assert result.fetched is True
        assert result.content_length <= 500

    def test_fetch_falls_back_on_http_error(self):
        fetcher = ArticleFetcher(timeout=5)
        resp = _make_response("Forbidden", status_code=403)
        resp.status_code = 403
        with patch.object(fetcher._client, "get", side_effect=httpx.HTTPStatusError("403", request=httpx.Request("GET", "https://nyt.com"), response=resp)):
            result = fetcher.fetch_article("https://nyt.com/article", rss_description="fallback text")

        assert result.fetched is False
        assert result.content == "fallback text"
        assert result.error is not None

    def test_fetch_falls_back_on_network_error(self):
        fetcher = ArticleFetcher(timeout=5)
        with patch.object(fetcher._client, "get", side_effect=httpx.ConnectError("Connection refused")):
            result = fetcher.fetch_article("https://down.example.com", rss_description="rss desc")

        assert result.fetched is False
        assert result.content == "rss desc"

    def test_fetch_falls_back_on_empty_readability(self):
        empty_html = "<html><body></body></html>"
        fetcher = ArticleFetcher(timeout=5)
        with patch.object(fetcher._client, "get", return_value=_make_response(empty_html)):
            result = fetcher.fetch_article("https://example.com/empty", rss_description="rss fallback")

        assert result.fetched is False
        assert result.content == "rss fallback"

    def test_google_news_resolution_success(self):
        fetcher = ArticleFetcher(timeout=5)
        # Stub _resolve_google_news_url to return a real URL, then stub the real fetch
        with patch.object(fetcher, "_resolve_google_news_url", return_value="https://bls.gov/cpi") as mock_resolve, \
             patch.object(fetcher._client, "get", return_value=_make_response(SIMPLE_HTML)):
            result = fetcher.fetch_article(
                "https://news.google.com/rss/articles/abc123",
                rss_description="",
            )

        mock_resolve.assert_called_once_with("https://news.google.com/rss/articles/abc123")
        assert result.fetched is True
        assert "Fed Holds Rates Steady" in result.content

    def test_google_news_resolution_failure_returns_fallback(self):
        fetcher = ArticleFetcher(timeout=5)
        with patch.object(fetcher, "_resolve_google_news_url", return_value=None):
            result = fetcher.fetch_article(
                "https://news.google.com/rss/articles/xyz789",
                rss_description="rss fallback",
            )

        assert result.fetched is False
        assert result.content == "rss fallback"
        assert "Google News" in (result.error or "")


# ---------------------------------------------------------------------------
# LocalMacroDataService._op_web_fetch_page (replaces FetchPageHandler tests)
# ---------------------------------------------------------------------------

class TestWebFetchPageOperation:
    def _make_service(self):
        return LocalMacroDataService(store=MagicMock())

    def test_missing_url_returns_error(self):
        svc = self._make_service()
        result = svc.invoke("web_fetch_page", {})
        assert result["fetched"] is False
        assert "url is required" in result["error"]

    def test_empty_url_returns_error(self):
        svc = self._make_service()
        result = svc.invoke("web_fetch_page", {"url": "  "})
        assert result["fetched"] is False

    def test_successful_fetch_returns_content(self):
        svc = self._make_service()
        mock_article = ArticleContent(
            content="# Headline\n\nSome article body text.",
            fetched=True,
            content_length=35,
        )
        with patch.object(ArticleFetcher, "fetch_article", return_value=mock_article):
            result = svc.invoke("web_fetch_page", {"url": "https://example.com/page"})

        assert result["fetched"] is True
        assert "Headline" in result["content"]

    def test_truncates_to_max_return_chars(self):
        svc = self._make_service()
        long_text = "x" * 200
        mock_article = ArticleContent(content=long_text, fetched=True, content_length=200)
        with patch.object(ArticleFetcher, "fetch_article", return_value=mock_article):
            result = svc.invoke("web_fetch_page", {
                "url": "https://example.com/long",
                "max_return_chars": 50,
            })

        assert result["fetched"] is True
        assert len(result["content"]) == 50

    def test_failed_fetch_returns_error(self):
        svc = self._make_service()
        mock_article = ArticleContent(
            content="",
            fetched=False,
            content_length=0,
            error="403 Forbidden",
        )
        with patch.object(ArticleFetcher, "fetch_article", return_value=mock_article):
            result = svc.invoke("web_fetch_page", {"url": "https://nyt.com/paywalled"})

        assert result["fetched"] is False
        assert result["error"] == "403 Forbidden"
        assert result["content"] == ""

    def test_exception_in_fetcher_returns_error(self):
        svc = self._make_service()
        with patch.object(ArticleFetcher, "fetch_article", side_effect=RuntimeError("boom")):
            result = svc.invoke("web_fetch_page", {"url": "https://example.com/crash"})

        assert result["fetched"] is False
        assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# build_web_fetch_tool factory
# ---------------------------------------------------------------------------

class TestBuildWebFetchTool:
    def test_returns_agent_tool_with_correct_schema(self):
        tool = build_web_fetch_tool()
        assert tool.name == "web_fetch_page"
        assert "url" in tool.parameters["required"]
        assert "url" in tool.parameters["properties"]
        assert "web page" in tool.description.lower()

    def test_custom_config_is_respected(self):
        config = FetchPageConfig(timeout=10, max_content_chars=5_000, max_return_chars=2_000)
        tool = build_web_fetch_tool(config)
        assert tool.handler is not None
        assert callable(tool.handler)

    def test_default_config(self):
        tool = build_web_fetch_tool()
        assert tool.handler is not None
        assert callable(tool.handler)
