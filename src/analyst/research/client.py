from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from analyst.env import get_env_value

logger = logging.getLogger(__name__)


class ResearchClient(Protocol):
    def investigate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ResearchHttpConfig:
    base_url: str
    api_token: str = ""
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> ResearchHttpConfig | None:
        base_url = get_env_value("ANALYST_RESEARCH_BASE_URL", default="").strip()
        if not base_url:
            return None
        timeout_raw = get_env_value("ANALYST_RESEARCH_TIMEOUT_SECONDS", default="60").strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 60.0
        return cls(
            base_url=base_url.rstrip("/"),
            api_token=get_env_value("ANALYST_RESEARCH_API_TOKEN", default="").strip(),
            timeout_seconds=max(timeout_seconds, 5.0),
        )


class HttpResearchClient:
    def __init__(self, config: ResearchHttpConfig) -> None:
        self._config = config

    def investigate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"
        response = httpx.post(
            f"{self._config.base_url}/v1/ops/investigate",
            headers=headers,
            json={"arguments": arguments},
            timeout=self._config.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("research-service response must be an object")
        return payload


def coerce_research_client(
    *,
    client: ResearchClient | None = None,
) -> ResearchClient | None:
    if client is not None:
        return client
    config = ResearchHttpConfig.from_env()
    if config is not None:
        return HttpResearchClient(config)
    return None
