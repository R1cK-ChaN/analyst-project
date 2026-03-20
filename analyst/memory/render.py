from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderBudget:
    total_chars: int = 6000
    max_item_chars: int = 360
    max_recent_messages: int = 8
    max_research_items: int = 4
    max_trading_items: int = 4
    max_delivery_items: int = 4


def sub_agent_budget() -> RenderBudget:
    return RenderBudget(
        total_chars=2500,
        max_item_chars=200,
        max_recent_messages=0,
        max_research_items=2,
        max_trading_items=2,
        max_delivery_items=0,
    )


def trim_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def render_context_sections(
    sections: list[tuple[str, list[str]]],
    *,
    budget: RenderBudget | None = None,
) -> str:
    limits = budget or RenderBudget()
    ordered = [f"### {title}\n" + "\n".join(lines) for title, lines in sections if lines]
    rendered = "\n\n".join(ordered)
    if len(rendered) <= limits.total_chars:
        return rendered

    while len(rendered) > limits.total_chars and len(ordered) > 1:
        ordered.pop()
        rendered = "\n\n".join(ordered)

    return rendered[: limits.total_chars].rstrip()
