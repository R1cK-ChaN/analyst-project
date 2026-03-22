from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from analyst.engine.live_types import AgentTool
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
    "places.userRatingCount,"
    "places.priceLevel,"
    "places.priceRange,"
    "places.currentOpeningHours,"
    "places.editorialSummary,"
    "places.websiteUri,"
    "places.googleMapsUri"
)


_PRICE_LEVEL_LABELS: dict[str, str] = {
    "PRICE_LEVEL_FREE": "免费",
    "PRICE_LEVEL_INEXPENSIVE": "$",
    "PRICE_LEVEL_MODERATE": "$$",
    "PRICE_LEVEL_EXPENSIVE": "$$$",
    "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$",
}


def _format_price_range(price_range: dict[str, Any]) -> str:
    """Format priceRange into 'SGD 80-120' style string."""
    start = price_range.get("startPrice", {})
    end = price_range.get("endPrice", {})
    currency = start.get("currencyCode") or end.get("currencyCode") or ""
    start_units = start.get("units", "")
    end_units = end.get("units", "")
    if start_units and end_units:
        return f"{currency} {start_units}-{end_units}"
    if start_units:
        return f"{currency} {start_units}+"
    if end_units:
        return f"{currency} ≤{end_units}"
    return ""


def _format_place(place: dict[str, Any]) -> dict[str, Any]:
    """Extract a clean structured dict from a raw Google Places API result."""
    display_name = place.get("displayName", {})
    editorial = place.get("editorialSummary", {})
    hours = place.get("currentOpeningHours", {})

    entry: dict[str, Any] = {}

    name = display_name.get("text", "")
    if name:
        entry["name"] = name

    address = place.get("formattedAddress", "")
    if address:
        entry["address"] = address

    rating = place.get("rating")
    rating_count = place.get("userRatingCount")
    if rating is not None:
        entry["rating"] = rating
    if rating_count:
        entry["rating_count"] = rating_count

    # Price: prefer priceRange, fall back to priceLevel
    price_range = place.get("priceRange")
    price_level = place.get("priceLevel")
    if price_range:
        formatted = _format_price_range(price_range)
        if formatted:
            entry["price_range"] = formatted
    elif price_level and price_level in _PRICE_LEVEL_LABELS:
        entry["price_level"] = _PRICE_LEVEL_LABELS[price_level]

    maps_uri = place.get("googleMapsUri", "")
    if maps_uri:
        entry["maps_url"] = re.sub(r"&g_mp=[^&]*", "", maps_uri)

    website = place.get("websiteUri")
    if website:
        entry["website"] = website

    open_now = hours.get("openNow")
    if open_now is not None:
        entry["open_now"] = open_now

    weekday_hours = hours.get("weekdayDescriptions")
    if weekday_hours:
        entry["hours"] = weekday_hours

    summary = editorial.get("text", "")
    if summary:
        entry["summary"] = summary

    return entry


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
            # Sort by review count descending — most authoritative result first
            places.sort(key=lambda p: p.get("userRatingCount", 0), reverse=True)
            results = []
            for place in places[:3]:
                results.append(_format_place(place))

            return {
                "summary": f"Found {len(results)} places for: {query}",
                "results": results,
                "result_count": len(results),
            }

        except requests.RequestException as exc:
            logger.warning("Places API request failed: %s", exc)
            return {"error": str(exc), "results": []}


def build_places_search_tool(
    config: PlacesConfig | None = None,
    session: requests.Session | None = None,
) -> AgentTool | None:
    """Factory: create a search_places AgentTool backed by Google Places API.

    Returns None if GOOGLE_PLACES_API_KEY is not set.
    """
    resolved = config or PlacesConfig.from_env()
    if resolved is None:
        return None
    handler = PlacesHandler(resolved, session=session)
    return AgentTool(
        name="search_places",
        description=(
            "Search for nearby places: restaurants, cafes, supermarkets, shops, "
            "gyms, libraries, etc. Returns structured data for each place: "
            "name, address, rating (with review count), price range, opening "
            "hours, website, and Google Maps link. Use this for any "
            "location-based query or place recommendation."
        ),
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Describe what you're looking for, including location context. "
                        "Example: 'Japanese restaurant near Bugis Singapore', "
                        "'supermarket near Tiong Bahru'."
                    ),
                },
            },
        },
        handler=handler,
    )
