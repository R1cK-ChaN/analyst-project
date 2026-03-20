from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

from analyst.engine.live_types import AgentTool
from analyst.env import get_env_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebSearchConfig:
    api_key: str
    model: str = "anthropic/claude-sonnet-4:online"
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: int = 30
    default_max_results: int = 5

    @classmethod
    def from_env(cls) -> WebSearchConfig:
        api_key = get_env_value("OPENROUTER_API_KEY", "LLM_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY or LLM_API_KEY is required for web search.")
        return cls(
            api_key=api_key,
            model=get_env_value("ANALYST_WEB_SEARCH_MODEL", default="anthropic/claude-sonnet-4:online"),
            base_url=get_env_value("OPENROUTER_BASE_URL", "LLM_BASE_URL", default="https://openrouter.ai/api/v1"),
        )


class WebSearchHandler:
    """Stateful callable that performs web searches via OpenRouter's plugins API."""

    def __init__(self, config: WebSearchConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", ""))
        if not query:
            return {"error": "query is required", "results": []}

        max_results = max(1, min(10, int(arguments.get("max_results", self._config.default_max_results))))

        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "messages": [{"role": "user", "content": query}],
            "plugins": [{"id": "web", "max_results": max_results}],
        }

        try:
            response = self._session.post(
                f"{self._config.base_url}/chat/completions",
                headers=headers,
                data=json.dumps(payload),
                timeout=self._config.timeout_seconds,
            )
            if response.status_code >= 400:
                logger.warning("Web search API error %d: %s", response.status_code, response.text[:300])
                return {"error": f"API error {response.status_code}", "results": []}

            body = response.json()
            choices = body.get("choices", [])
            if not choices:
                return {"error": "No response from search model", "results": []}

            message = choices[0].get("message", {})
            summary = message.get("content") or ""

            # Extract URL citations from annotations (nested under "url_citation" key)
            annotations = message.get("annotations", [])
            results = []
            for annotation in annotations:
                if annotation.get("type") == "url_citation":
                    citation = annotation.get("url_citation", annotation)
                    results.append({
                        "title": citation.get("title", ""),
                        "url": citation.get("url", ""),
                        "snippet": citation.get("content", ""),
                    })

            return {
                "summary": summary,
                "results": results,
                "result_count": len(results),
            }

        except requests.RequestException as exc:
            logger.warning("Web search request failed: %s", exc)
            return {"error": str(exc), "results": []}


def build_web_search_tool(
    config: WebSearchConfig | None = None,
    session: requests.Session | None = None,
) -> AgentTool:
    """Factory: create a web_search AgentTool backed by OpenRouter plugins API."""
    resolved_config = config or WebSearchConfig.from_env()
    handler = WebSearchHandler(resolved_config, session=session)
    return AgentTool(
        name="web_search",
        description=(
            "Search the web for current information. Use for real-time data, "
            "recent news, or facts not available in local tools. Returns a "
            "summary and a list of source URLs."
        ),
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query — be specific and include dates/context for best results.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-10, default 5).",
                },
            },
        },
        handler=handler,
    )
