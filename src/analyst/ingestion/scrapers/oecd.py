"""OECD SDMX REST v2 API client — composite leading indicators and confidence.

Uses the OECD SDMX REST v2 API at ``sdmx.oecd.org`` which provides
free, unauthenticated access to SDMX-JSON formatted data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_QUARTER_MAP = {"Q1": "01", "Q2": "04", "Q3": "07", "Q4": "10"}


def _normalize_date(raw: str) -> str:
    """Normalize OECD date strings to YYYY-MM-DD.

    Handles: ``"2025-12"``  → ``"2025-12-01"``,
             ``"2025-Q4"``  → ``"2025-10-01"``,
             ``"2024"``     → ``"2024-01-01"``.
    """
    m = re.match(r"^(\d{4})-Q(\d)$", raw)
    if m:
        return f"{m.group(1)}-{_QUARTER_MAP.get('Q' + m.group(2), '01')}-01"
    if re.match(r"^\d{4}-\d{2}$", raw):
        return f"{raw}-01"
    if re.match(r"^\d{4}$", raw):
        return f"{raw}-01-01"
    return raw


@dataclass(frozen=True)
class OECDObservation:
    """A single observation from the OECD SDMX API."""

    series_id: str
    date: str
    value: float
    dataflow: str = ""


class OECDClient:
    """Client for the OECD SDMX REST v2 API (no API key required)."""

    BASE_URL = "https://sdmx.oecd.org/public/rest/v2/data/dataflow"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "AnalystEngine/1.0",
        })

    def get_data(
        self,
        dataflow_id: str,
        version: str,
        key: str,
        *,
        series_id: str,
        start_period: str | None = None,
        limit: int = 100,
    ) -> list[OECDObservation]:
        """Fetch observations from an OECD SDMX dataflow as JSON.

        Args:
            dataflow_id: OECD dataflow, e.g. ``"DSD_STES@DF_CLI"``.
            version: Dataflow version, e.g. ``"4.1"``.
            key: Dimension key filter, e.g. ``"USA.M.LI.IX.*.*.*.*.*"``.
            series_id: Logical series id for the returned records.
            start_period: Optional start filter, e.g. ``"2024"``.
            limit: Maximum observations to return.
        """
        url = f"{self.BASE_URL}/OECD.SDD.STES/{dataflow_id}/{version}/{key}"
        params: dict[str, str] = {
            "format": "jsondata",
        }
        if start_period:
            pass  # OECD v2 does not support startPeriod; use lastNObservations
        if limit:
            params["lastNObservations"] = str(limit)

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return self._parse_json(
            response.json(), series_id=series_id, dataflow=dataflow_id, limit=limit,
        )

    @staticmethod
    def _parse_json(
        data: dict,
        *,
        series_id: str,
        dataflow: str,
        limit: int,
    ) -> list[OECDObservation]:
        """Parse SDMX-JSON response into observations."""
        observations: list[OECDObservation] = []

        try:
            # OECD wraps in "data" envelope: data.dataSets, data.structures
            inner = data.get("data", data)
            datasets = inner["dataSets"]
            structures = inner["structures"]
        except (KeyError, TypeError):
            return observations

        if not datasets or not structures:
            return observations

        # Find TIME_PERIOD dimension in observation dimensions
        obs_dims = structures[0].get("dimensions", {}).get("observation", [])
        time_dim = None
        for dim in obs_dims:
            if dim.get("id") == "TIME_PERIOD":
                time_dim = dim
                break

        if time_dim is None:
            return observations

        # Build index → time period mapping
        time_map: dict[str, str] = {}
        for i, val in enumerate(time_dim.get("values", [])):
            time_map[str(i)] = val.get("id", val.get("value", ""))

        # Iterate all series keys in the first dataset
        all_series = datasets[0].get("series", {})
        for _series_key, series_data in all_series.items():
            for obs_idx, obs_array in series_data.get("observations", {}).items():
                period = time_map.get(obs_idx)
                if not period:
                    continue
                value = obs_array[0] if obs_array else None
                if value is None:
                    continue
                try:
                    observations.append(OECDObservation(
                        series_id=series_id,
                        date=_normalize_date(period),
                        value=float(value),
                        dataflow=dataflow,
                    ))
                except (ValueError, TypeError):
                    continue

        observations.sort(key=lambda o: o.date, reverse=True)
        return observations[:limit]
