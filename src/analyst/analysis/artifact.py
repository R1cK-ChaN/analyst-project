"""Core data model for analysis artifacts — identity, caching, and TTL."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_TTL_SECONDS: dict[str, int] = {
    "market_snapshot": 3600,       # 1 hour
    "macro_indicator": 86400,      # 24 hours
    "news_digest": 7200,           # 2 hours
    "research_analysis": 14400,    # 4 hours
    "rate_analysis": 3600,         # 1 hour
    "portfolio_check": 3600,       # 1 hour
    "calendar_events": 3600,       # 1 hour
}

_DEFAULT_TTL = 7200  # 2 hours fallback


@dataclass(frozen=True)
class ArtifactIdentity:
    """Deterministic identity for a cached analysis artifact.

    The ``artifact_id`` property produces a stable 16-hex-char key from
    (artifact_type, parameters, time_context).  Same inputs always yield
    the same key.
    """

    artifact_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    time_context: dict[str, Any] = field(default_factory=dict)

    @property
    def artifact_id(self) -> str:
        params_json = json.dumps(self.parameters, sort_keys=True, ensure_ascii=False)
        time_json = json.dumps(self.time_context, sort_keys=True, ensure_ascii=False)
        raw = f"{self.artifact_type}:{params_json}:{time_json}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Artifact:
    """A cached analysis result stored in SQLite."""

    id: int
    artifact_id: str
    artifact_type: str
    parameters: dict[str, Any]
    time_context: dict[str, Any]
    dependencies: list[str]
    result: dict[str, Any]
    created_at: str
    expires_at: str


def compute_expiry(artifact_type: str, created_at: datetime | None = None) -> str:
    """Return an ISO expiry timestamp based on artifact type TTL."""
    base = created_at or datetime.now(timezone.utc)
    ttl = DEFAULT_TTL_SECONDS.get(artifact_type, _DEFAULT_TTL)
    return (base + timedelta(seconds=ttl)).isoformat()
