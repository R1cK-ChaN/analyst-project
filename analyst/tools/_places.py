from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from analyst.env import get_env_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlacesConfig:
    api_key: str
    default_location: str = "Singapore"
    language: str = "zh-CN"
    lat: float = 1.3521
    lon: float = 103.8198
    radius_m: float = 25000.0
    timeout_seconds: int = 15

    @classmethod
    def from_env(cls) -> PlacesConfig | None:
        api_key = get_env_value("GOOGLE_PLACES_API_KEY")
        if not api_key:
            return None
        return cls(api_key=api_key)


_FIELD_MASK = (
    "places.displayName,"
    "places.formattedAddress,"
    "places.rating,"
    "places.currentOpeningHours,"
    "places.editorialSummary"
)


class PlacesHandler:
    """Searches Google Places API (New) — Text Search."""

    def __init__(self, config: PlacesConfig, session: requests.Session | None = None) -> None:
        self._config = config
        self._session = session or requests.Session()

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", ""))
        if not query:
            return {"error": "query is required", "results": []}

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._config.api_key,
            "X-Goog-FieldMask": _FIELD_MASK,
        }
        body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {
                        "latitude": self._config.lat,
                        "longitude": self._config.lon,
                    },
                    "radius": self._config.radius_m,
                },
            },
            "languageCode": self._config.language,
            "maxResultCount": 3,
        }

        try:
            resp = self._session.post(
                "https://places.googleapis.com/v1/places:searchText",
                headers=headers,
                json=body,
                timeout=self._config.timeout_seconds,
            )
            if resp.status_code >= 400:
                logger.warning("Places API error %d: %s", resp.status_code, resp.text[:300])
                return {"error": f"Places API error {resp.status_code}", "results": []}

            data = resp.json()
            places = data.get("places", [])
            results = []
            for place in places[:3]:
                display_name = place.get("displayName", {})
                editorial = place.get("editorialSummary", {})
                hours = place.get("currentOpeningHours", {})
                entry: dict[str, Any] = {
                    "name": display_name.get("text", ""),
                    "address": place.get("formattedAddress", ""),
                    "rating": place.get("rating"),
                    "open_now": hours.get("openNow"),
                    "summary": editorial.get("text", ""),
                }
                weekday_hours = hours.get("weekdayDescriptions")
                if weekday_hours:
                    entry["weekday_hours"] = weekday_hours
                results.append(entry)

            return {
                "summary": f"Found {len(results)} places for: {query}",
                "results": results,
                "result_count": len(results),
            }

        except requests.RequestException as exc:
            logger.warning("Places API request failed: %s", exc)
            return {"error": str(exc), "results": []}
