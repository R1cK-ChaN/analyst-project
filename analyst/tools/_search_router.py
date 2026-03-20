from __future__ import annotations

import logging
from typing import Any, Literal

from analyst.engine.live_types import AgentTool

from ._places import PlacesConfig, PlacesHandler
from ._weather import WeatherConfig, WeatherHandler
from ._web_search import WebSearchConfig, WebSearchHandler

logger = logging.getLogger(__name__)

_PLACES_KEYWORDS = frozenset({
    "推荐", "附近", "餐厅", "咖啡馆", "酒吧", "书店", "健身房",
    "在哪", "去哪", "好吃", "好喝", "开门", "营业",
    "cafe", "restaurant", "bar", "gym", "library", "recommend",
})

_WEATHER_KEYWORDS = frozenset({
    "天气", "下雨", "温度", "热不热", "冷不冷", "weather",
    "rain", "umbrella", "伞", "晒",
})


def classify_query(query: str) -> Literal["places", "weather", "web"]:
    q = query.lower()
    if any(kw in q for kw in _PLACES_KEYWORDS):
        return "places"
    if any(kw in q for kw in _WEATHER_KEYWORDS):
        return "weather"
    return "web"


class SmartSearchHandler:
    """Wraps PlacesHandler, WeatherHandler, WebSearchHandler behind keyword routing."""

    def __init__(
        self,
        places: PlacesHandler | None,
        weather: WeatherHandler | None,
        web: WebSearchHandler,
    ) -> None:
        self._places = places
        self._weather = weather
        self._web = web

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query", "")
        category = classify_query(query)
        if category == "places" and self._places is not None:
            return self._places(arguments)
        if category == "weather" and self._weather is not None:
            return self._weather(arguments)
        return self._web(arguments)


def _try_build_places() -> PlacesHandler | None:
    config = PlacesConfig.from_env()
    if config is None:
        logger.debug("GOOGLE_PLACES_API_KEY not set — places search disabled")
        return None
    return PlacesHandler(config)


def _try_build_weather() -> WeatherHandler | None:
    config = WeatherConfig.from_env()
    if config is None:
        logger.debug("OPENWEATHERMAP_API_KEY not set — weather search disabled")
        return None
    return WeatherHandler(config)


def build_smart_search_tool(
    web_config: WebSearchConfig | None = None,
) -> AgentTool:
    """Factory: create a web_search AgentTool with smart routing to Places/Weather APIs."""
    places = _try_build_places()
    weather = _try_build_weather()
    web = WebSearchHandler(web_config or WebSearchConfig.from_env())
    handler = SmartSearchHandler(places, weather, web)
    return AgentTool(
        name="web_search",
        description=(
            "Search for information: places, weather, news, facts. "
            "Use for recommendations, real-time data, or anything you're not sure about."
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
