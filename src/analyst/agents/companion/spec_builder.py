from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

_ALLOWED_ANALYSIS_TYPES = {"general", "macro", "markets", "news", "portfolio"}
_ALLOWED_OUTPUT_FORMATS = {"summary", "briefing", "bullet_points", "risk_check", "timeline"}
_MAX_TASK_CHARS = 500
_MAX_TEXT_CHARS = 700


@dataclass(frozen=True)
class ResearchDelegationSpec:
    task: str
    goal: str
    analysis_type: str
    time_horizon: str
    output_format: str
    context: str


def build_research_delegation_spec(arguments: dict[str, Any]) -> ResearchDelegationSpec:
    task = _clean_text(arguments.get("task", ""), max_chars=_MAX_TASK_CHARS)
    if not task:
        raise ValueError("Missing required 'task' argument.")

    goal = _clean_text(arguments.get("goal", ""), max_chars=220)
    analysis_type = _normalize_choice(arguments.get("analysis_type", ""), _ALLOWED_ANALYSIS_TYPES, default="general")
    time_horizon = _clean_text(arguments.get("time_horizon", ""), max_chars=80)
    output_format = _normalize_choice(arguments.get("output_format", ""), _ALLOWED_OUTPUT_FORMATS, default="summary")
    context = _sanitize_context(arguments.get("context", ""))
    return ResearchDelegationSpec(
        task=task,
        goal=goal or "Give the companion a factual answer it can relay naturally.",
        analysis_type=analysis_type,
        time_horizon=time_horizon or "current",
        output_format=output_format,
        context=context,
    )


def render_research_delegation_prompt(spec: ResearchDelegationSpec) -> str:
    lines = [
        f"Primary task:\n{spec.task}",
        "",
        "Research brief:",
        f"- Goal: {spec.goal}",
        f"- Analysis type: {spec.analysis_type}",
        f"- Time horizon: {spec.time_horizon}",
        f"- Output format: {spec.output_format}",
    ]
    if spec.context:
        lines.extend(["", f"User-safe context:\n{spec.context}"])
    lines.extend(
        [
            "",
            "Response requirements:",
            "- Use tools if freshness or factual accuracy matters.",
            "- Be concise and concrete.",
            "- Distinguish facts from inference.",
            "- Do not mention internal role separation.",
        ]
    )
    return "\n".join(lines)


def _normalize_choice(raw_value: Any, allowed: set[str], *, default: str) -> str:
    normalized = _clean_text(raw_value, max_chars=40).lower().replace(" ", "_")
    return normalized if normalized in allowed else default


def _sanitize_context(raw_value: Any) -> str:
    raw_text = str(raw_value or "").strip()
    if not raw_text:
        return ""
    filtered_lines: list[str] = []
    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in (
                "client_profile",
                "topic_state",
                "current_thread",
                "speaker_memory",
                "delivery_history",
                "<profile_update>",
                "</profile_update>",
            )
        ):
            continue
        filtered_lines.append(line)
    return _clean_text("\n".join(filtered_lines), max_chars=_MAX_TEXT_CHARS)


def _clean_text(raw_value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(raw_value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
