"""Fetch a web page and extract readable content as markdown."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.macro_data import MacroDataClient

from ._macro_data import MacroDataOperationHandler


@dataclass(frozen=True)
class FetchPageConfig:
    timeout: int = 20
    max_content_chars: int = 15_000
    max_return_chars: int = 8_000


def build_web_fetch_tool(
    config: FetchPageConfig | None = None,
    *,
    data_client: MacroDataClient | None = None,
) -> AgentTool:
    """Factory: create a web_fetch_page AgentTool backed by MacroDataClient."""
    resolved_config = config or FetchPageConfig()
    op_handler = MacroDataOperationHandler("web_fetch_page", data_client=data_client)

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        arguments.setdefault("timeout", resolved_config.timeout)
        arguments.setdefault("max_content_chars", resolved_config.max_content_chars)
        arguments.setdefault("max_return_chars", resolved_config.max_return_chars)
        return op_handler(arguments)

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
