"""Fetch a web page and extract readable content as markdown."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.ingestion.news_fetcher import ArticleFetcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchPageConfig:
    timeout: int = 20
    max_content_chars: int = 15_000
    max_return_chars: int = 8_000


class FetchPageHandler:
    """Stateful callable that fetches and extracts page content via ArticleFetcher."""

    def __init__(self, config: FetchPageConfig) -> None:
        self._config = config
        self._fetcher: ArticleFetcher | None = None

    def _get_fetcher(self) -> ArticleFetcher:
        if self._fetcher is None:
            self._fetcher = ArticleFetcher(
                timeout=self._config.timeout,
                max_content_chars=self._config.max_content_chars,
            )
        return self._fetcher

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments.get("url", "")).strip()
        if not url:
            return {"error": "url is required", "content": "", "fetched": False}

        try:
            article = self._get_fetcher().fetch_article(url, rss_description="")
        except Exception as exc:
            logger.warning("web_fetch_page failed for %s: %s", url, exc)
            return {"error": str(exc), "content": "", "fetched": False}

        if not article.fetched:
            return {
                "error": article.error or "fetch failed",
                "content": "",
                "fetched": False,
            }

        content = article.content
        if len(content) > self._config.max_return_chars:
            content = content[: self._config.max_return_chars]

        return {
            "content": content,
            "fetched": True,
            "content_length": len(content),
        }


def build_web_fetch_tool(config: FetchPageConfig | None = None) -> AgentTool:
    """Factory: create a web_fetch_page AgentTool backed by ArticleFetcher."""
    resolved_config = config or FetchPageConfig()
    handler = FetchPageHandler(resolved_config)
    return AgentTool(
        name="web_fetch_page",
        description=(
            "Fetch a web page and extract its readable content as markdown. "
            "Use after web_search to read the full article body, verify claims, "
            "or get details not in the search snippet."
        ),
        parameters={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the web page to fetch.",
                },
            },
        },
        handler=handler,
    )
