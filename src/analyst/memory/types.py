from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from analyst.storage.sqlite import (
    MemoryBlockRecord as MemoryBlockData,
    MemoryFactRecord as MemoryFactData,
    MemoryMessageRecord as MemoryMessageData,
    MemorySearchRecord as RetrievedMemoryItem,
    PublishedArtifactRecord,
)


class AgentKind(str, Enum):
    RESEARCH = "research"
    TRADER = "trader"
    SALES = "sales"


class MemoryVisibility(str, Enum):
    PRIVATE = "private"
    PUBLISHED = "published"


class MemoryScopeKind(str, Enum):
    GLOBAL = "global"
    TASK = "task"
    CLIENT = "client"
    THREAD = "thread"


@dataclass(frozen=True)
class MemoryScopeKey:
    tenant_id: str
    agent_kind: AgentKind
    visibility: MemoryVisibility
    scope_kind: MemoryScopeKind
    scope_id: str
    subject_id: str = ""
    thread_id: str = ""

    def storage_key(self) -> str:
        parts = [
            self.tenant_id,
            self.agent_kind.value,
            self.visibility.value,
            self.scope_kind.value,
            self.scope_id,
            self.subject_id,
            self.thread_id,
        ]
        return "::".join(part.replace("::", "__") for part in parts)


@dataclass(frozen=True)
class MemoryEventData:
    event_type: str
    created_at: str
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class HydratedMemoryContext:
    blocks: list[MemoryBlockData] = field(default_factory=list)
    semantic_facts: list[MemoryFactData] = field(default_factory=list)
    retrieved_items: list[RetrievedMemoryItem] = field(default_factory=list)
    summary: str = ""
    recent_messages: list[MemoryMessageData] = field(default_factory=list)


@dataclass(frozen=True)
class RenderBudget:
    total_chars: int = 6000
    max_facts_rendered: int = 20
    max_retrieved_items: int = 3
    max_retrieved_chars: int = 500
    max_summary_chars: int = 1200
    max_recent_messages: int = 8


@dataclass(frozen=True)
class MemoryPolicy:
    render_budget: RenderBudget = field(default_factory=RenderBudget)
    archival_search_limit: int = 3
    max_messages_loaded: int = 24

