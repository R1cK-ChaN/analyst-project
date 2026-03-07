from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from analyst.storage import SQLiteEngineStore

from .types import HydratedMemoryContext, MemoryPolicy, MemoryScopeKey


@dataclass
class MemorySession:
    scope: MemoryScopeKey
    store: SQLiteEngineStore
    policy: MemoryPolicy

    def set_block(
        self,
        name: str,
        value: str,
        *,
        label: str = "",
        description: str = "",
    ) -> None:
        self.store.upsert_memory_block(
            self.scope,
            name=name,
            value=value,
            label=label,
            description=description,
        )

    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        self.store.append_memory_message(self.scope, role=role, content=content, metadata=metadata or {})

    def add_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        self.store.append_memory_event(self.scope, event_type=event_type, data=data or {})

    def add_fact(
        self,
        key: str,
        value: Any,
        *,
        confidence: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.store.upsert_memory_fact(
            self.scope,
            fact_key=key,
            value=value,
            confidence=confidence,
            metadata=metadata or {},
        )

    def store_archival(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        self.store.insert_memory_archival(self.scope, content=content, metadata=metadata or {})

    def hydrate(self, query: str | None = None) -> HydratedMemoryContext:
        blocks = self.store.list_memory_blocks(self.scope)
        facts = self.store.list_memory_facts(self.scope)
        messages = self.store.list_memory_messages(
            self.scope,
            limit=self.policy.max_messages_loaded,
        )
        retrieved = []
        if query and query.strip():
            retrieved = self.store.search_memory_archival(
                self.scope,
                query=query,
                limit=self.policy.archival_search_limit,
            )

        max_recent = self.policy.render_budget.max_recent_messages
        summary = ""
        if len(messages) > max_recent:
            older = messages[:-max_recent]
            snippets = []
            for message in older[-4:]:
                preview = message.content
                if len(preview) > 120:
                    preview = preview[:120].rstrip() + "..."
                snippets.append(f"{message.role}: {preview}")
            if snippets:
                summary = "Earlier thread context:\n" + "\n".join(f"- {snippet}" for snippet in snippets)

        return HydratedMemoryContext(
            blocks=blocks,
            semantic_facts=facts,
            retrieved_items=retrieved,
            summary=summary,
            recent_messages=messages[-max_recent:],
        )
