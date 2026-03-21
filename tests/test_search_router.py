"""Tests for the smart search router (places / weather / web)."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from analyst.tools._places import PlacesConfig, PlacesHandler
from analyst.tools._search_router import SmartSearchHandler, classify_query
from analyst.runtime.chat import _has_unsupported_specifics
from analyst.tools._weather import WeatherConfig, WeatherHandler


# ── classify_query ──────────────────────────────────────────────────


class TestClassifyQuery:
    def test_places_chinese(self):
        assert classify_query("推荐个咖啡馆") == "places"

    def test_places_english(self):
        assert classify_query("recommend a good restaurant") == "places"

    def test_places_mixed(self):
        assert classify_query("附近有什么好吃的") == "places"

    def test_places_bar(self):
        assert classify_query("酒吧在哪") == "places"

    def test_weather_chinese(self):
        assert classify_query("今天会下雨吗") == "weather"

    def test_weather_english(self):
        assert classify_query("what's the weather like") == "weather"

    def test_weather_umbrella(self):
        assert classify_query("要不要带伞") == "weather"

    def test_weather_temperature(self):
        assert classify_query("温度多少") == "weather"

    def test_places_give_me_names(self):
        assert classify_query("给我几个名字") == "places"

    def test_places_location_nearby(self):
        assert classify_query("bugis附近有什么") == "places"

    def test_places_opening_hours_chinese(self):
        assert classify_query("星巴克营业时间") == "places"

    def test_places_closing_time(self):
        assert classify_query("星巴克几点关门") == "places"

    def test_places_opening_hours_english(self):
        assert classify_query("starbucks opening hours") == "places"

    def test_places_what_time(self):
        assert classify_query("starbucks what time close") == "places"

    def test_places_when_open(self):
        assert classify_query("starbucks什么时候开") == "places"

    def test_places_open_until(self):
        assert classify_query("开到几点") == "places"

    def test_fallback_holiday(self):
        assert classify_query("明天什么假期") == "web"

    def test_fallback_news(self):
        assert classify_query("最新新闻") == "web"

    def test_fallback_generic(self):
        assert classify_query("Python asyncio tutorial") == "web"


# ── SmartSearchHandler routing ──────────────────────────────────────


class TestSmartSearchHandler:
    def test_routes_to_places(self):
        places = MagicMock(return_value={"summary": "places", "results": []})
        weather = MagicMock()
        web = MagicMock()
        handler = SmartSearchHandler(places, weather, web)

        result = handler({"query": "推荐个咖啡馆"})

        places.assert_called_once_with({"query": "推荐个咖啡馆"})
        weather.assert_not_called()
        web.assert_not_called()
        assert result["summary"] == "places"

    def test_routes_to_weather(self):
        places = MagicMock()
        weather = MagicMock(return_value={"summary": "weather", "results": []})
        web = MagicMock()
        handler = SmartSearchHandler(places, weather, web)

        result = handler({"query": "今天天气怎么样"})

        weather.assert_called_once()
        places.assert_not_called()
        web.assert_not_called()
        assert result["summary"] == "weather"

    def test_routes_to_web(self):
        places = MagicMock()
        weather = MagicMock()
        web = MagicMock(return_value={"summary": "web", "results": []})
        handler = SmartSearchHandler(places, weather, web)

        result = handler({"query": "明天什么假期"})

        web.assert_called_once()
        places.assert_not_called()
        weather.assert_not_called()
        assert result["summary"] == "web"

    def test_fallback_when_places_none(self):
        """When places handler is None (no API key), falls through to web."""
        web = MagicMock(return_value={"summary": "web fallback", "results": []})
        handler = SmartSearchHandler(places=None, weather=None, web=web)

        result = handler({"query": "推荐个咖啡馆"})

        web.assert_called_once()
        assert result["summary"] == "web fallback"

    def test_fallback_when_weather_none(self):
        """When weather handler is None, falls through to web."""
        web = MagicMock(return_value={"summary": "web fallback", "results": []})
        handler = SmartSearchHandler(places=None, weather=None, web=web)

        result = handler({"query": "今天会下雨吗"})

        web.assert_called_once()
        assert result["summary"] == "web fallback"


# ── PlacesHandler ───────────────────────────────────────────────────


class TestPlacesHandler:
    def test_returns_structured(self):
        config = PlacesConfig(api_key="fake-key")
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "places": [
                {
                    "displayName": {"text": "Common Man Coffee Roasters"},
                    "formattedAddress": "22 Martin Rd, Singapore",
                    "rating": 4.3,
                    "currentOpeningHours": {
                        "openNow": True,
                        "weekdayDescriptions": [
                            "星期一: 08:00–22:00",
                            "星期二: 08:00–22:00",
                        ],
                    },
                    "editorialSummary": {"text": "Specialty coffee in the CBD"},
                },
                {
                    "displayName": {"text": "Nylon Coffee Roasters"},
                    "formattedAddress": "4 Everton Park, Singapore",
                    "rating": 4.5,
                    "currentOpeningHours": {"openNow": False},
                    "editorialSummary": {},
                },
            ],
        }
        mock_session.post.return_value = mock_resp
        handler = PlacesHandler(config, session=mock_session)

        result = handler({"query": "quiet cafe near Tanjong Pagar"})

        assert result["result_count"] == 2
        assert result["results"][0]["name"] == "Common Man Coffee Roasters"
        assert result["results"][0]["open_now"] is True
        assert result["results"][0]["weekday_hours"] == [
            "星期一: 08:00–22:00",
            "星期二: 08:00–22:00",
        ]
        assert "weekday_hours" not in result["results"][1]
        assert result["results"][1]["rating"] == 4.5

    def test_empty_query(self):
        config = PlacesConfig(api_key="fake-key")
        handler = PlacesHandler(config)
        result = handler({"query": ""})
        assert result["error"] == "query is required"

    def test_api_error(self):
        config = PlacesConfig(api_key="fake-key")
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        mock_session.post.return_value = mock_resp
        handler = PlacesHandler(config, session=mock_session)

        result = handler({"query": "cafe"})
        assert "error" in result


# ── WeatherHandler ──────────────────────────────────────────────────


class TestWeatherHandler:
    def _mock_weather_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "main": {"temp": 31.2, "feels_like": 35.0, "humidity": 75},
            "weather": [{"description": "多云"}],
            "rain": {"1h": 0.5},
        }
        return mock_resp

    def test_returns_structured(self):
        config = WeatherConfig(api_key="fake-key")
        mock_session = MagicMock()
        mock_session.get.return_value = self._mock_weather_response()
        handler = WeatherHandler(config, session=mock_session)

        result = handler({"query": "今天天气"})

        assert result["result_count"] == 1
        assert result["results"][0]["temperature"] == 31.2
        assert result["results"][0]["description"] == "多云"
        assert result["results"][0]["rain_1h_mm"] == 0.5

    def test_cache_hit(self):
        config = WeatherConfig(api_key="fake-key", cache_ttl_seconds=3600)
        mock_session = MagicMock()
        mock_session.get.return_value = self._mock_weather_response()
        handler = WeatherHandler(config, session=mock_session)

        # First call fetches
        handler({"query": "天气"})
        # Second call should use cache
        handler({"query": "天气"})

        assert mock_session.get.call_count == 1

    def test_cache_expired(self):
        config = WeatherConfig(api_key="fake-key", cache_ttl_seconds=0)
        mock_session = MagicMock()
        mock_session.get.return_value = self._mock_weather_response()
        handler = WeatherHandler(config, session=mock_session)

        handler({"query": "天气"})
        handler({"query": "天气"})

        assert mock_session.get.call_count == 2


# ── Unsupported-specifics detector ─────────────────────────────────


class TestHasUnsupportedSpecifics:
    def test_no_specifics(self):
        assert _has_unsupported_specifics("那家店还不错", []) is False

    def test_time_chinese_no_tool(self):
        assert _has_unsupported_specifics("早上8点开门 晚上10点关", []) is True

    def test_time_english_no_tool(self):
        assert _has_unsupported_specifics("opens at 8am closes 10PM", []) is True

    def test_time_colon_no_tool(self):
        assert _has_unsupported_specifics("营业时间 08:00-22:00", []) is True

    def test_price_no_tool(self):
        assert _has_unsupported_specifics("大概$15左右", []) is True

    def test_specifics_with_tool_ok(self):
        audit = [{"tool_name": "web_search", "tool_call_id": "x", "arguments": {}, "status": ""}]
        assert _has_unsupported_specifics("早上8点开门", audit) is False

    def test_sgd_price_no_tool(self):
        assert _has_unsupported_specifics("S$5一杯", []) is True

    def test_yuan_price_no_tool(self):
        assert _has_unsupported_specifics("差不多30元", []) is True
