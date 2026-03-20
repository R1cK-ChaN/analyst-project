from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from analyst.env import get_env_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeatherConfig:
    api_key: str
    lat: float = 1.3521
    lon: float = 103.8198
    cache_ttl_seconds: int = 3600
    timeout_seconds: int = 10

    @classmethod
    def from_env(cls) -> WeatherConfig | None:
        api_key = get_env_value("OPENWEATHERMAP_API_KEY")
        if not api_key:
            return None
        return cls(api_key=api_key)


class WeatherHandler:
    """Fetches current weather from OpenWeatherMap with in-memory caching."""

    def __init__(self, config: WeatherConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._cache: dict[str, Any] | None = None
        self._cache_time: float = 0.0

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self._config.cache_ttl_seconds:
            return self._cache

        try:
            resp = self._session.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": self._config.lat,
                    "lon": self._config.lon,
                    "appid": self._config.api_key,
                    "units": "metric",
                    "lang": "zh_cn",
                },
                timeout=self._config.timeout_seconds,
            )
            if resp.status_code >= 400:
                logger.warning("Weather API error %d: %s", resp.status_code, resp.text[:300])
                return {"error": f"Weather API error {resp.status_code}", "results": []}

            data = resp.json()
            main = data.get("main", {})
            weather_list = data.get("weather", [])
            description = weather_list[0].get("description", "") if weather_list else ""
            rain = data.get("rain", {})

            result: dict[str, Any] = {
                "summary": f"Singapore weather: {description}, {main.get('temp', '')}°C",
                "results": [{
                    "temperature": main.get("temp"),
                    "feels_like": main.get("feels_like"),
                    "description": description,
                    "humidity": main.get("humidity"),
                    "rain_1h_mm": rain.get("1h", 0),
                }],
                "result_count": 1,
            }
            self._cache = result
            self._cache_time = now
            return result

        except requests.RequestException as exc:
            logger.warning("Weather API request failed: %s", exc)
            return {"error": str(exc), "results": []}
