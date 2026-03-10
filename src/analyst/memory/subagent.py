from __future__ import annotations

import json
import logging
from typing import Any

from analyst.contracts import utc_now
from analyst.storage import SQLiteEngineStore

from .render import RenderBudget, render_context_sections, trim_text

logger = logging.getLogger(__name__)


def sub_agent_budget() -> RenderBudget:
    return RenderBudget(
        total_chars=2500,
        max_item_chars=200,
        max_recent_messages=0,
        max_research_items=2,
        max_trading_items=2,
        max_delivery_items=0,
    )


def build_subagent_memory(
    store: SQLiteEngineStore,
    *,
    scope_tags: list[str],
    parent_agent: str,
) -> str:
    """Build a filtered, compressed memory context for a sub-agent.

    Sub-agents never see: client profiles, delivery queues, conversation history.
    Sub-agents can see: filtered regime snapshots, filtered analytical observations.
    """
    budget = sub_agent_budget()
    sections: list[tuple[str, list[str]]] = []

    # Regime snapshots (always included, filtered by tags if available)
    try:
        if scope_tags:
            snapshots = store.list_tagged_regime_snapshots(tags=scope_tags, limit=2)
        else:
            snapshots = store.list_recent_regime_snapshots(limit=2)
        regime_lines = [
            f"- {s.timestamp}: {trim_text(s.summary, max_chars=budget.max_item_chars)}"
            for s in snapshots
        ]
        if regime_lines:
            sections.append(("Regime Context", regime_lines))
    except Exception:
        logger.debug("Failed to fetch regime snapshots for sub-agent", exc_info=True)

    # Analytical observations (filtered by tags if available)
    try:
        if scope_tags:
            observations = store.list_tagged_observations(tags=scope_tags, limit=budget.max_research_items)
        else:
            observations = store.list_recent_analytical_observations(limit=budget.max_research_items)
        obs_lines = [
            f"- {o.observation_type}: {trim_text(o.summary, max_chars=budget.max_item_chars)}"
            for o in observations
        ]
        if obs_lines:
            sections.append(("Recent Observations", obs_lines))
    except Exception:
        logger.debug("Failed to fetch observations for sub-agent", exc_info=True)

    if not sections:
        return ""

    return render_context_sections(sections, budget=budget)


def record_subagent_run(
    *,
    store: SQLiteEngineStore,
    task_id: str,
    parent_agent: str,
    task_type: str,
    objective: str,
    scope_tags: list[str],
    result_status: str,
    summary: str,
    elapsed_seconds: float,
) -> None:
    """Persist an audit record for a sub-agent run."""
    store.save_subagent_run(
        task_id=task_id,
        parent_agent=parent_agent,
        task_type=task_type,
        objective=objective,
        scope_tags=scope_tags,
        status=result_status,
        summary=summary,
        elapsed_seconds=elapsed_seconds,
    )
