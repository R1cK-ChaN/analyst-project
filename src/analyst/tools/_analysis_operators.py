"""Unified analysis operator tool — dispatches to registered operators."""

from __future__ import annotations

import logging
from typing import Any

from analyst.analysis.artifact import ArtifactIdentity
from analyst.analysis.operators import OPERATOR_REGISTRY, run_operator
from analyst.engine.live_types import AgentTool

logger = logging.getLogger(__name__)


class AnalysisOperatorHandler:
    """Dispatches to registered operators and auto-caches results as artifacts."""

    def __init__(self, store: Any | None = None) -> None:
        self._store = store

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        operator = str(arguments.get("operator", "")).strip()
        if not operator:
            available = ", ".join(sorted(OPERATOR_REGISTRY))
            return {"error": f"operator is required. Available: {available}"}

        inputs = arguments.get("inputs") or {}
        parameters = arguments.get("parameters") or {}

        context = {"store": self._store} if self._store else {}

        try:
            result = run_operator(operator, inputs, parameters, context=context)
        except KeyError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.warning("Operator '%s' failed: %s", operator, exc)
            return {"error": f"Operator '{operator}' failed: {exc}"}

        if "error" in result:
            return result

        # Auto-cache as artifact if store available
        if self._store is not None:
            try:
                identity = ArtifactIdentity(
                    artifact_type=operator,
                    parameters=_normalize_cache_key(inputs, parameters),
                )
                self._store.upsert_artifact(identity, result)
            except Exception:
                pass  # caching failure should not block result

        return result


def _normalize_cache_key(inputs: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic cache key from operator inputs and parameters.

    Excludes raw value arrays (too large / unique) — only includes
    structural identifiers like labels and parameter settings.
    """
    key: dict[str, Any] = {}
    for k, v in sorted(inputs.items()):
        if k in ("labels", "label_a", "label_b"):
            key[k] = v
        elif isinstance(v, list) and v:
            # Use a fingerprint instead of full array
            key[f"{k}_len"] = len(v)
            key[f"{k}_first"] = v[0]
            key[f"{k}_last"] = v[-1]
    for k, v in sorted(parameters.items()):
        key[f"param_{k}"] = v
    return key


def build_analysis_operator_tool(store: Any | None = None) -> AgentTool:
    """Factory: create a run_analysis AgentTool."""
    handler = AnalysisOperatorHandler(store)

    operators_desc = "\n".join(
        f"  - {spec.name}: {spec.description}"
        for spec in sorted(OPERATOR_REGISTRY.values(), key=lambda s: s.name)
    )

    return AgentTool(
        name="run_analysis",
        description=(
            "Run a built-in analysis operator on numeric data. Faster and more reliable "
            "than writing custom Python code. Results are auto-cached as artifacts.\n\n"
            "Available operators:\n"
            f"{operators_desc}\n\n"
            "Prefer these operators over run_python_analysis for standard computations."
        ),
        parameters={
            "type": "object",
            "required": ["operator", "inputs"],
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "Operator name: trend, change, rolling_stat, compare, correlation, spread",
                },
                "inputs": {
                    "type": "object",
                    "description": (
                        "Input data. Single-series operators: {\"values\": [1.0, 2.0, ...]}. "
                        "Two-series operators: {\"series_a\": [...], \"series_b\": [...]}. "
                        "Optional: {\"labels\": [\"2025-01\", ...]} for date labels."
                    ),
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Operator-specific parameters. "
                        "trend: {\"window\": N}. "
                        "change: {\"period\": N, \"mode\": \"absolute\"|\"percent\"}. "
                        "rolling_stat: {\"window\": N, \"stat\": \"mean\"|\"std\"|\"min\"|\"max\"|\"median\"}. "
                        "compare/correlation/spread: {\"label_a\": \"CPI\", \"label_b\": \"Wages\"}."
                    ),
                },
            },
        },
        handler=handler,
    )
