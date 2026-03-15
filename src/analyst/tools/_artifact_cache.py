"""Artifact cache tools for the research agent."""

from __future__ import annotations

import logging
from typing import Any

from analyst.analysis.artifact import ArtifactIdentity
from analyst.engine.live_types import AgentTool

logger = logging.getLogger(__name__)


class ArtifactLookupHandler:
    """Check if a fresh cached artifact exists."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        artifact_type = str(arguments.get("artifact_type", "")).strip()
        if not artifact_type:
            return {"status": "error", "error": "artifact_type is required"}
        parameters = arguments.get("parameters") or {}
        time_context = arguments.get("time_context") or {}

        identity = ArtifactIdentity(artifact_type, parameters, time_context)

        try:
            self._store.expire_stale_artifacts()
        except Exception:
            pass

        try:
            artifact = self._store.get_fresh_artifact(identity.artifact_id)
        except Exception as exc:
            logger.warning("Artifact lookup failed: %s", exc)
            return {"status": "error", "error": str(exc)}

        if artifact is None:
            return {
                "status": "miss",
                "artifact_id": identity.artifact_id,
                "message": "No fresh artifact found. Proceed with computation.",
            }
        return {
            "status": "hit",
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "result": artifact.result,
            "created_at": artifact.created_at,
            "expires_at": artifact.expires_at,
        }


class ArtifactStoreHandler:
    """Store a computed result as a cached artifact."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        artifact_type = str(arguments.get("artifact_type", "")).strip()
        if not artifact_type:
            return {"status": "error", "error": "artifact_type is required"}
        parameters = arguments.get("parameters") or {}
        time_context = arguments.get("time_context") or {}
        result = arguments.get("result")
        if not isinstance(result, dict):
            return {"status": "error", "error": "result must be a JSON object"}
        dependencies = arguments.get("dependencies") or []

        identity = ArtifactIdentity(artifact_type, parameters, time_context)

        try:
            artifact = self._store.upsert_artifact(identity, result, dependencies)
        except Exception as exc:
            logger.warning("Artifact store failed: %s", exc)
            return {"status": "error", "error": str(exc)}

        return {
            "status": "stored",
            "artifact_id": artifact.artifact_id,
            "artifact_type": artifact.artifact_type,
            "expires_at": artifact.expires_at,
        }


def build_artifact_lookup_tool(store: Any) -> AgentTool:
    """Factory: create a check_artifact_cache AgentTool."""
    handler = ArtifactLookupHandler(store)
    return AgentTool(
        name="check_artifact_cache",
        description=(
            "Check if a previously computed analysis artifact is still fresh in the cache. "
            "Call this BEFORE using data-fetching tools to avoid redundant computation. "
            "Provide the artifact_type (e.g. 'market_snapshot', 'macro_indicator', 'research_analysis'), "
            "the parameters dict that uniquely identifies this computation, and optionally "
            "a time_context dict for the relevant time window. Returns the cached result "
            "if fresh, or a 'miss' status if you need to compute it."
        ),
        parameters={
            "type": "object",
            "required": ["artifact_type", "parameters"],
            "properties": {
                "artifact_type": {
                    "type": "string",
                    "description": (
                        "Type: market_snapshot, macro_indicator, news_digest, "
                        "research_analysis, rate_analysis, portfolio_check, calendar_events"
                    ),
                },
                "parameters": {
                    "type": "object",
                    "description": "Parameters that uniquely identify this computation (e.g. {\"symbol\": \"SPX\"})",
                },
                "time_context": {
                    "type": "object",
                    "description": "Time window context (e.g. {\"date\": \"2026-03-15\"}). Defaults to {}.",
                },
            },
        },
        handler=handler,
    )


def build_artifact_store_tool(store: Any) -> AgentTool:
    """Factory: create a store_artifact AgentTool."""
    handler = ArtifactStoreHandler(store)
    return AgentTool(
        name="store_artifact",
        description=(
            "Store a computed analysis result as a cached artifact for future reuse. "
            "Call this AFTER computing a result with data tools. The artifact will be "
            "cached with an appropriate TTL based on its type. Future research runs can "
            "retrieve it via check_artifact_cache instead of recomputing."
        ),
        parameters={
            "type": "object",
            "required": ["artifact_type", "parameters", "result"],
            "properties": {
                "artifact_type": {
                    "type": "string",
                    "description": (
                        "Type: market_snapshot, macro_indicator, news_digest, "
                        "research_analysis, rate_analysis, portfolio_check, calendar_events"
                    ),
                },
                "parameters": {
                    "type": "object",
                    "description": "Parameters that uniquely identify this computation.",
                },
                "time_context": {
                    "type": "object",
                    "description": "Time window context. Defaults to {}.",
                },
                "result": {
                    "type": "object",
                    "description": "The computed result dict to cache.",
                },
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of artifact_ids this result depends on.",
                },
            },
        },
        handler=handler,
    )
