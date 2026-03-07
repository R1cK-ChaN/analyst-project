from __future__ import annotations

from .types import HydratedMemoryContext, MemoryFactData, RenderBudget, RetrievedMemoryItem


def merge_hydrated_contexts(*contexts: HydratedMemoryContext) -> HydratedMemoryContext:
    blocks_by_name = {}
    facts_by_key: dict[str, MemoryFactData] = {}
    retrieved: list[RetrievedMemoryItem] = []
    messages = []
    summaries: list[str] = []

    for context in contexts:
        for block in context.blocks:
            blocks_by_name[block.name] = block
        for fact in context.semantic_facts:
            previous = facts_by_key.get(fact.key)
            if previous is None or fact.confidence >= previous.confidence:
                facts_by_key[fact.key] = fact
        retrieved.extend(context.retrieved_items)
        messages.extend(context.recent_messages)
        if context.summary:
            summaries.append(context.summary)

    retrieved.sort(key=lambda item: (item.score, item.created_at), reverse=True)
    messages.sort(key=lambda item: item.created_at)
    return HydratedMemoryContext(
        blocks=list(blocks_by_name.values()),
        semantic_facts=list(facts_by_key.values()),
        retrieved_items=retrieved,
        summary="\n".join(summaries),
        recent_messages=messages,
    )


def render_memory_context(
    context: HydratedMemoryContext,
    budget: RenderBudget | None = None,
) -> str:
    limits = budget or RenderBudget()
    sections: list[str] = []

    for block in context.blocks:
        if not block.value:
            continue
        sections.append(f"<{block.name}>{block.value}</{block.name}>")

    if context.semantic_facts:
        facts = sorted(
            context.semantic_facts,
            key=lambda item: (item.confidence, item.updated_at),
            reverse=True,
        )[: limits.max_facts_rendered]
        fact_lines = [f"- {fact.key}: {fact.value!r} (confidence={fact.confidence:.2f})" for fact in facts]
        sections.append("<known_facts>\n" + "\n".join(fact_lines) + "\n</known_facts>")

    if context.retrieved_items:
        lines = []
        for item in context.retrieved_items[: limits.max_retrieved_items]:
            content = item.content
            if len(content) > limits.max_retrieved_chars:
                content = content[: limits.max_retrieved_chars].rstrip() + "..."
            lines.append(f"- [{item.score:.2f}] {content}")
        sections.append("<relevant_memories>\n" + "\n".join(lines) + "\n</relevant_memories>")

    if context.summary:
        summary = context.summary
        if len(summary) > limits.max_summary_chars:
            summary = summary[: limits.max_summary_chars].rstrip() + "..."
        sections.append(f"<conversation_summary>{summary}</conversation_summary>")

    if context.recent_messages:
        lines = []
        for message in context.recent_messages[-limits.max_recent_messages :]:
            preview = message.content
            if len(preview) > 240:
                preview = preview[:240].rstrip() + "..."
            lines.append(f"[{message.created_at}] {message.role}: {preview}")
        sections.append("<recent_history>\n" + "\n".join(lines) + "\n</recent_history>")

    rendered = "\n\n".join(section for section in sections if section)
    if len(rendered) <= limits.total_chars:
        return rendered

    for tag in ("<recent_history>", "<conversation_summary>", "<known_facts>", "<relevant_memories>"):
        if len(rendered) <= limits.total_chars:
            break
        pieces = [piece for piece in rendered.split("\n\n") if not piece.startswith(tag)]
        rendered = "\n\n".join(pieces)

    return rendered[: limits.total_chars].rstrip()
