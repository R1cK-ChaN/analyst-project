"""Fetch a full article using domain-aware scraper routing."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from analyst.engine.live_types import AgentTool
from analyst.ingestion.news_fetcher import ArticleFetcher
from analyst.ingestion.scrapers import (
    BloombergArticleClient,
    FTArticleClient,
    ReutersArticleClient,
    WSJArticleClient,
)

logger = logging.getLogger(__name__)

_DOMAIN_MAP: dict[str, str] = {
    "bloomberg.com": "bloomberg",
    "ft.com": "ft",
    "wsj.com": "wsj",
    "reuters.com": "reuters",
}


def _detect_domain(url: str) -> str | None:
    """Return a short key if the URL belongs to a known financial news domain."""
    hostname = urlparse(url).hostname or ""
    for domain, key in _DOMAIN_MAP.items():
        if hostname == domain or hostname.endswith("." + domain):
            return key
    return None


class ArticleHandler:
    """Stateful callable that routes article fetching to the right scraper."""

    def __init__(self) -> None:
        self._generic_fetcher: ArticleFetcher | None = None

    def _get_generic_fetcher(self) -> ArticleFetcher:
        if self._generic_fetcher is None:
            self._generic_fetcher = ArticleFetcher(timeout=20, max_content_chars=15_000)
        return self._generic_fetcher

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments.get("url", "")).strip()
        if not url:
            return {"error": "url is required", "fetched": False}

        max_chars = min(int(arguments.get("max_chars", 6000)), 12000)
        domain_key = _detect_domain(url)

        try:
            if domain_key == "bloomberg":
                return self._fetch_bloomberg(url, max_chars)
            elif domain_key == "ft":
                return self._fetch_ft(url, max_chars)
            elif domain_key == "wsj":
                return self._fetch_wsj(url, max_chars)
            elif domain_key == "reuters":
                return self._fetch_reuters(url, max_chars)
            else:
                return self._fetch_generic(url, max_chars)
        except Exception as exc:
            logger.warning("fetch_article failed for %s: %s", url, exc)
            return {"error": str(exc), "fetched": False}

    def _fetch_bloomberg(self, url: str, max_chars: int) -> dict[str, Any]:
        with BloombergArticleClient() as client:
            article = client.fetch_article(url)
        if not article.fetched:
            return {"error": article.error or "fetch failed", "fetched": False}
        content = article.content[:max_chars]
        return {
            "source": "bloomberg",
            "title": article.title,
            "authors": article.authors,
            "published_at": article.published_at,
            "keywords": article.keywords,
            "lede": article.lede,
            "content": content,
            "content_length": len(content),
            "truncated": len(article.content) > max_chars,
            "fetched": True,
        }

    def _fetch_ft(self, url: str, max_chars: int) -> dict[str, Any]:
        with FTArticleClient() as client:
            article = client.fetch_article(url)
        if not article.fetched:
            return {"error": article.error or "fetch failed", "fetched": False}
        content = article.content[:max_chars]
        return {
            "source": "ft",
            "title": article.title,
            "authors": article.authors,
            "published_at": article.published_at,
            "keywords": article.keywords,
            "standfirst": article.standfirst,
            "content": content,
            "content_length": len(content),
            "truncated": len(article.content) > max_chars,
            "fetched": True,
        }

    def _fetch_wsj(self, url: str, max_chars: int) -> dict[str, Any]:
        with WSJArticleClient() as client:
            article = client.fetch_article(url)
        if not article.fetched:
            return {"error": article.error or "fetch failed", "fetched": False}
        content = article.content[:max_chars]
        return {
            "source": "wsj",
            "title": article.title,
            "authors": article.authors,
            "published_at": article.published_at,
            "keywords": article.keywords,
            "dek": article.dek,
            "content": content,
            "content_length": len(content),
            "truncated": len(article.content) > max_chars,
            "fetched": True,
        }

    def _fetch_reuters(self, url: str, max_chars: int) -> dict[str, Any]:
        article = ReutersArticleClient().fetch_article(url)
        if not article.fetched:
            return {"error": article.error or "fetch failed", "fetched": False}
        content = article.content[:max_chars]
        return {
            "source": "reuters",
            "title": article.title,
            "authors": article.authors,
            "published_at": article.published_at,
            "keywords": article.keywords,
            "content": content,
            "content_length": len(content),
            "truncated": len(article.content) > max_chars,
            "fetched": True,
        }

    def _fetch_generic(self, url: str, max_chars: int) -> dict[str, Any]:
        article = self._get_generic_fetcher().fetch_article(url, rss_description="")
        if not article.fetched:
            return {"error": article.error or "fetch failed", "fetched": False}
        content = article.content[:max_chars]
        return {
            "source": "generic",
            "title": getattr(article, "title", ""),
            "content": content,
            "content_length": len(content),
            "truncated": len(article.content) > max_chars,
            "fetched": True,
        }


def build_article_tool() -> AgentTool:
    """Factory: create a fetch_article AgentTool."""
    handler = ArticleHandler()
    return AgentTool(
        name="fetch_article",
        description=(
            "Fetch and extract a full article from a URL. Auto-detects domain and uses specialized "
            "scrapers for Bloomberg, FT, WSJ, and Reuters (with authenticated access for paywalled sites). "
            "Falls back to a generic extractor for other domains. Use this for financial news article URLs."
        ),
        parameters={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The article URL to fetch.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max content characters to return (default 6000, max 12000)",
                },
            },
        },
        handler=handler,
    )
